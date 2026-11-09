"""T0/T1/T2 : apprentissage commun sur paires synthetiques train/val, jamais test."""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from importlib.metadata import version
from itertools import islice
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
import yaml

from resilientinspect.data.audit import _sha256
from resilientinspect.data import synthetic
from resilientinspect.evaluation.evaluate_ae import (
    _json_bytes, manifest_digest, overlap_metrics, ranking_metrics,
)
from resilientinspect.models import transfer
from .train_ae import EarlyStopping, resolve_device, save_best_checkpoint, seed_everything

PROJECT = Path(__file__).resolve().parents[2]
CATEGORIES = ("bottle", "hazelnut", "leather")


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    schemas = {
        "root": {"schema_version", "variant", "categories", "seed", "model", "synthetic_config", "training", "calibration", "smoke", "tracking"},
        "model": {"name", "head_dropout", "unfreeze_stages", "weights"},
        "training": {"batch_size", "max_epochs", "optimizer", "head_lr", "backbone_lr", "weight_decay", "loss", "mixed_precision", "num_workers", "cpu_threads", "early_stopping"},
        "calibration": {"method", "quantile", "quantile_method", "decision"},
        "smoke": {"batch_size", "max_epochs", "max_batches_per_split"},
        "tracking": {"experiment_name"},
    }
    for name, keys in schemas.items():
        section = config if name == "root" else config.get(name) if isinstance(config, dict) else None
        if not isinstance(section, dict) or set(section) != keys:
            raise ValueError(f"Schema transfert incomplet ou inconnu : {name}.")
    if (config["schema_version"] != 1 or config["variant"] not in ("T0", "T1", "T2")
            or config["categories"] != list(CATEGORIES)
            or type(config["seed"]) is not int or not 0 <= config["seed"] < 2**32
            or not isinstance(config["synthetic_config"], str) or not config["synthetic_config"]):
        raise ValueError("Variante, categories, seed ou configuration synthetique invalide.")
    variant, model, training = config["variant"], config["model"], config["training"]
    stages = {"T0": list(range(9)), "T1": [], "T2": [6, 7, 8]}[variant]
    if model != {"name": "efficientnet_b0", "head_dropout": 0.2, "unfreeze_stages": stages,
                 "weights": "random" if variant == "T0" else "IMAGENET1K_V1"}:
        raise ValueError("Architecture, tete et politique de gel T0/T1/T2 fixes requises.")
    for key in ("batch_size", "max_epochs", "cpu_threads"):
        if type(training[key]) is not int or training[key] < 1:
            raise ValueError(f"{key} doit etre entier positif.")
    if (training["optimizer"] != "adam" or training["loss"] != "bce_with_logits"
            or training["mixed_precision"] is not False or training["num_workers"] != 0
            or type(training["num_workers"]) is not int):
        raise ValueError("Adam/BCE logits, FP32 et workers=0 requis.")
    for key in ("head_lr", "backbone_lr", "weight_decay"):
        value = training[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} invalide.")
    if (training["head_lr"] <= 0 or (variant == "T0" and training["backbone_lr"] != training["head_lr"])
            or (variant == "T1" and training["backbone_lr"] != 0)
            or (variant == "T2" and not 0 < training["backbone_lr"] < training["head_lr"])):
        raise ValueError("Learning rates incoherents avec la variante.")
    stop = training["early_stopping"]
    if (not isinstance(stop, dict) or set(stop) != {"patience", "min_delta"}
            or type(stop["patience"]) is not int or stop["patience"] < 1
            or type(stop["min_delta"]) not in (int, float)
            or not math.isfinite(stop["min_delta"]) or stop["min_delta"] < 0):
        raise ValueError("Early stopping invalide.")
    if config["calibration"] != {"method": "normal_quantile", "quantile": 0.95,
                                 "quantile_method": "higher", "decision": "strictly_greater"}:
        raise ValueError("Calibration normale val quantile95% higher strictement > requise.")
    smoke = config["smoke"]
    if (type(smoke["max_epochs"]) is not int or smoke["max_epochs"] != 1
            or any(type(smoke[key]) is not int or not 1 <= smoke[key] <= 2
                   for key in ("batch_size", "max_batches_per_split"))):
        raise ValueError("Smoke limite a 1 epoque, batch<=2 et <=2 batches par split.")
    if config["tracking"]["experiment_name"] != "resilientinspect-transfer":
        raise ValueError("Experience MLflow distincte resilientinspect-transfer requise.")
    return config


def _safe_output(path: Path, root: Path, manifest: Path, *, parent: Path | None = None) -> None:
    resolved = path.resolve()
    if any(resolved.is_relative_to(protected.resolve()) for protected in (root, manifest.parent)):
        raise ValueError("Sorties transfert interdites dans donnees ou manifestes.")
    if resolved.is_relative_to(PROJECT) and not resolved.is_relative_to(PROJECT / "artifacts/transfer_runs"):
        raise ValueError("Sorties projet transfert limitees a artifacts/transfer_runs ; B0/A1 proteges.")
    if path.is_symlink() or (parent is not None and not resolved.is_relative_to(parent.resolve())):
        raise ValueError("Lien/jonction de sortie hors du repertoire autorise.")


def classification_metrics(labels: np.ndarray, scores: np.ndarray, threshold: float = 0.5) -> dict[str, Any]:
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Seuil de classification fini dans [0,1] requis.")
    labels, scores = np.asarray(labels).ravel(), np.asarray(scores).ravel()
    ranked = ranking_metrics(labels, scores)
    predicted = scores > threshold
    counts = overlap_metrics(labels, predicted)
    return {"accuracy": float(np.mean(labels == predicted)), "auroc": ranked["auroc"], "ap": ranked["ap"],
            "undefined_reason": ranked["undefined_reason"], "f1": counts["dice"],
            **{key: counts[key] for key in ("tp", "fp", "fn")},
            "tn": int(np.count_nonzero((labels == 0) & ~predicted)), "threshold": threshold,
            "positive_class": 1, "anomaly_fraction": float(labels.mean())}


def run_epoch(model: nn.Module, loader: DataLoader, device: torch.device,
              optimizer: torch.optim.Optimizer | None = None, max_batches: int | None = None) -> dict[str, Any]:
    training = optimizer is not None
    expected_split = "train" if training else "val"
    model.train(training)
    total, samples, batches, rows = 0.0, 0, 0, []
    selected_batches = loader if max_batches is None else islice(loader, max_batches)
    with torch.enable_grad() if training else torch.no_grad():
        for batch in selected_batches:
            if any(split != expected_split for split in batch["split"]):
                raise ValueError("Split interdit : apprentissage train et validation val exclusivement.")
            labels = batch["label"].to(device=device, dtype=torch.float32)
            images = batch["image"].to(device)
            if (images.ndim != 4 or images.shape[1:] != (3, 256, 256) or not torch.isfinite(images).all()
                    or labels.shape != (images.shape[0],) or not torch.isin(labels, torch.tensor([0., 1.], device=device)).all()):
                raise ValueError("RGB BCHW 256x256 finis et labels binaires requis.")
            if optimizer is not None:
                optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            if logits.shape != labels.shape or not torch.isfinite(logits).all():
                raise ValueError("Un logit binaire fini par image requis.")
            loss = nn.functional.binary_cross_entropy_with_logits(logits, labels)
            if not torch.isfinite(loss):
                raise ValueError("Perte BCE non finie.")
            if optimizer is not None:
                loss.backward()
                gradients = [p.grad for p in model.parameters() if p.grad is not None]
                if not gradients or any(not torch.isfinite(gradient).all() for gradient in gradients):
                    raise ValueError("Gradients absents ou non finis ; pas de mise a jour.")
                optimizer.step()
            size = labels.numel()
            total += float(loss.detach()) * size
            samples += size
            batches += 1
            for i, score in enumerate(logits.detach().sigmoid().cpu().tolist()):
                rows.append({"sample_id": batch["sample_id"][i], "image_path": batch["image_path"][i],
                             "split": expected_split, "label": int(labels[i]), "score": score})
    if samples == 0:
        raise ValueError("Aucun exemple disponible.")
    metrics = classification_metrics(np.array([row["label"] for row in rows]), np.array([row["score"] for row in rows]))
    return {"loss": total / samples, "images": samples, "batches": batches, **metrics, "predictions": rows}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_bytes(_json_bytes(payload))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _plot_history(history: list[dict[str, Any]], path: Path, title: str) -> None:
    os.environ["MPLCONFIGDIR"] = str(path.parent / ".matplotlib")
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    figure = Figure(figsize=(12, 7), layout="constrained")
    FigureCanvasAgg(figure)
    for axis, key in zip(figure.subplots(2, 3).flat, ("loss", "accuracy", "auroc", "ap", "f1", "images")):
        for split in ("train", "val"):
            values = [np.nan if row[f"{split}_{key}"] is None else row[f"{split}_{key}"] for row in history]
            axis.plot([row["epoch"] for row in history], values, marker="o", label=f"{split} synthetique")
        axis.set(title=key, xlabel="Epoque")
        axis.grid(alpha=0.2)
        axis.legend()
    figure.suptitle(title + " | seuil des courbes 0.5")
    figure.savefig(path, dpi=120)
    figure.clear()


def _plot_validation(rows: list[dict[str, Any]], threshold: float, path: Path, title: str) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from sklearn.metrics import precision_recall_curve, roc_curve
    labels = np.array([row["label"] for row in rows])
    scores = np.array([row["score"] for row in rows])
    figure = Figure(figsize=(10, 7), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(2, 2)
    if np.unique(labels).size == 2:
        fpr, tpr, _ = roc_curve(labels, scores)
        precision, recall, _ = precision_recall_curve(labels, scores)
        axes[0, 0].plot(fpr, tpr)
        axes[0, 1].plot(recall, precision)
    axes[0, 0].set(title="ROC val synthetique", xlabel="FPR", ylabel="TPR")
    axes[0, 1].set(title="PR val synthetique", xlabel="Recall", ylabel="Precision")
    groups = [scores[labels == label] for label in (0, 1)]
    available = [(name, group) for name, group in zip(("normal", "synthetique"), groups) if group.size]
    axes[1, 0].boxplot([group for _, group in available], tick_labels=[name for name, _ in available])
    axes[1, 0].axhline(threshold, color="red", label="seuil normal val")
    axes[1, 0].set(title="Scores val", ylabel="P(anomalie synthetique)")
    axes[1, 0].legend()
    values = classification_metrics(labels, scores, threshold)
    confusion = np.array([[values["tn"], values["fp"]], [values["fn"], values["tp"]]])
    axes[1, 1].imshow(confusion, cmap="Blues")
    for (y, x), number in np.ndenumerate(confusion):
        axes[1, 1].text(x, y, str(number), ha="center", va="center")
    axes[1, 1].set(title="Confusion au seuil val", xlabel="Prediction (0 normal, 1 anomalie)", ylabel="Label", xticks=[0, 1], yticks=[0, 1])
    figure.suptitle(title + " | validation synthetique uniquement")
    figure.savefig(path, dpi=120)
    figure.clear()


def run_training(config_path: Path, *, root: Path, manifest: Path, output_dir: Path,
                 category: str, seed: int | None = None, device: str = "auto", smoke: bool = False,
                 synthetic_plan: Path | None = None, imagenet_weights: Path | None = None,
                 allow_download: bool = False) -> dict[str, Any]:
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    seed = config["seed"] if seed is None else seed
    if category not in CATEGORIES or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Categorie ou seed invalide.")
    target_device = resolve_device(device)
    if target_device.type == "cpu" and not smoke:
        raise ValueError("Entrainement transfert complet reserve a CUDA ; utiliser --smoke sur CPU.")
    root, manifest, output_dir = Path(root).resolve(), Path(manifest).resolve(), Path(output_dir)
    _safe_output(output_dir, root, manifest)
    for child in ("mlflow.db", "mlartifacts", "synthetic_plans", config["variant"]):
        _safe_output(output_dir / child, root, manifest, parent=output_dir)
    output_dir = output_dir.resolve()
    if not root.is_dir():
        raise ValueError("Racine dataset absente.")
    digest = manifest_digest(manifest)
    synthetic_config_path = (config_path.parent / config["synthetic_config"]).resolve()
    synthetic_config = synthetic.load_synthetic_config(synthetic_config_path)
    plan = synthetic.prepare_synthetic_plan(manifest, synthetic_config, seed)
    if synthetic_plan is not None:
        plan_path = Path(synthetic_plan)
        if json.loads(plan_path.read_text(encoding="utf-8")) != plan:
            raise ValueError("Plan synthetique absent, perime ou incompatible.")
    else:
        plan_path = output_dir / "synthetic_plans" / f"seed{seed}_{digest[:12]}_{plan['config_sha256'][:12]}.json"
        _safe_output(plan_path, root, manifest, parent=output_dir)
        synthetic.write_synthetic_plan(plan, plan_path)
    plan_digest = _sha256(plan_path)
    effective = deepcopy(config)
    effective.update(seed=seed, category=category, scope="smoke" if smoke else "full", device=str(target_device),
                     normalization=synthetic_config["normalization"], image_size=synthetic_config["image_size"])
    training = effective["training"]
    max_batches = config["smoke"]["max_batches_per_split"] if smoke else None
    effective["max_batches_per_split"] = max_batches
    if smoke:
        training.update(batch_size=config["smoke"]["batch_size"], max_epochs=1)
    seed_everything(seed, training["cpu_threads"])
    model = transfer.build_transfer_model(config["variant"], seed=seed, imagenet_weights=imagenet_weights,
                                          allow_download=allow_download).to(target_device)
    loaders = {}
    for offset, split in enumerate(("train", "val")):
        dataset = synthetic.SyntheticAnomalyDataset(manifest, root, category=category, split=split,
                                                    config=synthetic_config, seed=seed, plan=plan)
        loaders[split] = DataLoader(dataset, batch_size=training["batch_size"], shuffle=split == "train",
                                    num_workers=0, drop_last=False, pin_memory=target_device.type == "cuda",
                                    generator=torch.Generator().manual_seed(seed + offset))
    optimizer = torch.optim.Adam(transfer.parameter_groups(model, head_lr=training["head_lr"],
                                                           backbone_lr=training["backbone_lr"]),
                                  weight_decay=training["weight_decay"])
    stopper = EarlyStopping(**training["early_stopping"])
    parameter_report = transfer.trainable_parameter_report(model)
    from mlflow import MlflowClient, __version__ as mlflow_version
    output_dir.mkdir(parents=True, exist_ok=True)
    tracking_uri = f"sqlite:///{(output_dir / 'mlflow.db').as_posix()}"
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name(config["tracking"]["experiment_name"])
    experiment_id = experiment.experiment_id if experiment else client.create_experiment(
        config["tracking"]["experiment_name"], artifact_location=(output_dir / "mlartifacts").as_uri())
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT, capture_output=True, text=True, check=False)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT, capture_output=True, text=True, check=False)
    source_paths = [config_path, synthetic_config_path, Path(__file__), Path(transfer.__file__), Path(synthetic.__file__),
                    PROJECT / "src/data/dataset.py", PROJECT / "src/data/prepare.py", PROJECT / "src/data/audit.py",
                    PROJECT / "src/training/train_ae.py", PROJECT / "src/evaluation/evaluate_ae.py", PROJECT / "pyproject.toml"]
    provenance = {"manifest_sha256": digest, "synthetic_plan_sha256": plan_digest, "synthetic_plan_path": str(plan_path),
                  "manifest_path": str(manifest), "dataset_root": str(root),
                  "git_sha": git.stdout.strip() if git.returncode == 0 else "unavailable",
                  "git_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
                  "source_sha256": {str(path): _sha256(path) for path in source_paths},
                  "weight_provenance": model.weight_provenance}
    tags = {"mlflow.runName": f"{config['variant']}-{category}-{effective['scope']}-seed{seed}",
            "variant": config["variant"], "category": category, "scope": effective["scope"], "seed": str(seed),
            "dataset_version": digest, "synthetic_plan_sha256": plan_digest, "git_sha": provenance["git_sha"],
            "selection_split": "val_synthetic", "test_used": "false"}
    run_id = client.create_run(experiment_id, tags=tags).info.run_id
    run_dir = output_dir / config["variant"] / category / f"seed{seed}" / f"{effective['scope']}_{run_id}"
    _safe_output(run_dir, root, manifest, parent=output_dir)
    history, best_loss, best_epoch = [], math.inf, 0
    seen = {"train": set(), "val": set()}
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
        _safe_output(run_dir / ".matplotlib", root, manifest, parent=run_dir)
        effective_path = run_dir / "effective_config.yaml"
        effective_path.write_text(yaml.safe_dump(effective, sort_keys=False), encoding="utf-8")
        (run_dir / "synthetic_plan.json").write_bytes(plan_path.read_bytes())
        _write_json(run_dir / "trainable_parameters.json", parameter_report)
        _write_json(run_dir / "weight_provenance.json", model.weight_provenance)
        _write_json(run_dir / "provenance.json", provenance)
        environment = {"python": sys.version.split()[0], "torch": str(torch.__version__), "numpy": np.__version__,
                       "torchvision": version("torchvision"), "mlflow": mlflow_version, "scikit_learn": version("scikit-learn"),
                       "device": str(target_device), "cuda_runtime": torch.version.cuda,
                       "gpu_name": torch.cuda.get_device_name(target_device) if target_device.type == "cuda" else None,
                       "cpu_threads": torch.get_num_threads(), "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                       "mixed_precision": False}
        _write_json(run_dir / "environment.json", environment)
        (run_dir / "source").mkdir()
        for path in source_paths:
            (run_dir / "source" / path.name).write_bytes(path.read_bytes())
        params = {"variant": config["variant"], "category": category, "seed": seed, "scope": effective["scope"],
                  "batch_size": training["batch_size"], "max_epochs": training["max_epochs"], "optimizer": "Adam",
                  "head_lr": training["head_lr"], "backbone_lr": training["backbone_lr"], "weight_decay": training["weight_decay"],
                  "loss": "bce_with_logits", "metric_threshold": 0.5, "patience": stopper.patience, "min_delta": stopper.min_delta,
                  "mixed_precision": False, "image_size": "256x256", "train_examples": len(loaders["train"].dataset),
                  "val_examples": len(loaders["val"].dataset), "parameters": parameter_report["total_parameters"],
                  "trainable_parameters": parameter_report["trainable_parameters"], "synthetic_plan_sha256": plan_digest,
                  "imagenet_source": json.dumps(model.weight_provenance, sort_keys=True)}
        for name, value in params.items():
            client.log_param(run_id, name, value)
        for epoch in range(1, training["max_epochs"] + 1):
            train = run_epoch(model, loaders["train"], target_device, optimizer, max_batches)
            validation = run_epoch(model, loaders["val"], target_device, max_batches=max_batches)
            row = {"epoch": epoch}
            for split, result in (("train", train), ("val", validation)):
                seen[split].update(item["image_path"] for item in result["predictions"])
                row.update({f"{split}_{name}": result[name] for name in ("loss", "accuracy", "auroc", "ap", "f1", "images", "batches", "tn", "tp", "fp", "fn")})
            history.append(row)
            _write_csv(run_dir / "history.csv", history)
            for name, value in row.items():
                if name != "epoch" and value is not None:
                    client.log_metric(run_id, name, value, step=epoch)
            if validation["loss"] < best_loss:
                best_loss, best_epoch = validation["loss"], epoch
                save_best_checkpoint(run_dir / "best.pt", model, optimizer, epoch=epoch, val_loss=best_loss,
                                     metadata={"variant": config["variant"], "category": category, "seed": seed,
                                               "scope": effective["scope"], "effective_config": effective,
                                               "weight_provenance": model.weight_provenance, "manifest_sha256": digest,
                                               "synthetic_plan_sha256": plan_digest})
            print(json.dumps({"variant": config["variant"], "category": category, "scope": effective["scope"], **row}), flush=True)
            if stopper.update(validation["loss"]):
                break
        saved = torch.load(run_dir / "best.pt", map_location="cpu", weights_only=True)
        model.load_state_dict(saved["model_state_dict"], strict=True)
        selected_validation = run_epoch(model, loaders["val"], target_device, max_batches=max_batches)
        rows = selected_validation["predictions"]
        normal_scores = np.array([row["score"] for row in rows if row["label"] == 0])
        if not normal_scores.size:
            raise ValueError("Calibration exige au moins un normal de validation synthetique.")
        threshold = float(np.quantile(normal_scores, 0.95, method="higher"))
        calibration = {"variant": config["variant"], "category": category, "seed": seed, "scope": effective["scope"],
                       "calibration_split": "val_synthetic", "normal_only": True, "image_threshold": threshold,
                       "validation_normal_images": int(normal_scores.size), "validation_images": len(rows),
                       "method": "normal_quantile", "quantile": 0.95, "quantile_method": "higher", "decision": "strictly_greater",
                       "checkpoint_sha256": _sha256(run_dir / "best.pt"), "manifest_sha256": digest,
                       "synthetic_plan_sha256": plan_digest, "effective_config_sha256": _sha256(effective_path),
                       "train_code_sha256": _sha256(Path(__file__)), "model_code_sha256": _sha256(Path(transfer.__file__)),
                       "synthetic_code_sha256": _sha256(Path(synthetic.__file__)),
                       "shared_evaluation_code_sha256": _sha256(PROJECT / "src/evaluation/evaluate_ae.py"),
                       "dataset_code_sha256": _sha256(PROJECT / "src/data/dataset.py"),
                       "normalization": effective["normalization"], "image_size": effective["image_size"], "environment": environment,
                       "validation_scores": rows, "empirical_normal_fpr": float(np.mean(normal_scores > threshold))}
        _write_json(run_dir / "calibration.json", calibration)
        (run_dir / "calibration.sha256").write_text(_sha256(run_dir / "calibration.json") + "\n", encoding="ascii")
        for row in rows:
            row.update(predicted_label=int(row["score"] > threshold), image_threshold=threshold)
        _write_csv(run_dir / "validation_predictions.csv", rows)
        validation_metrics = {"split": "val_synthetic", "loss": selected_validation["loss"], "images": len(rows),
                              **classification_metrics(np.array([row["label"] for row in rows]), np.array([row["score"] for row in rows]), threshold)}
        _write_json(run_dir / "validation_metrics.json", validation_metrics)
        title = f"{config['variant']} | {category} | {effective['scope']} | seed{seed} | {run_id[:8]}"
        _plot_history(history, run_dir / "learning_curves.png", title)
        _plot_validation(rows, threshold, run_dir / "validation_diagnostics.png", title)
        summary = {"status": "completed", "variant": config["variant"], "category": category, "seed": seed,
                   "scope": effective["scope"], "run_id": run_id, "run_dir": str(run_dir), "tracking_uri": tracking_uri,
                   "epochs_completed": len(history), "best_epoch": best_epoch, "best_val_loss": best_loss,
                   "selection_split": "val_synthetic", "test_used": False, "history": history,
                   "stopped_early": stopper.bad_epochs >= stopper.patience,
                   "checkpoint_sha256": _sha256(run_dir / "best.pt"), "trainable_parameters": parameter_report,
                   "calibration_sha256": _sha256(run_dir / "calibration.json"), "validation_metrics": validation_metrics,
                   **provenance}
        _write_json(run_dir / "summary.json", summary)
        _write_json(run_dir / "data_usage.json", {split: sorted(paths) for split, paths in seen.items()})
        client.log_metric(run_id, "best_val_loss", best_loss, step=best_epoch)
        for name, value in validation_metrics.items():
            if type(value) in (int, float):
                client.log_metric(run_id, f"selected_val_{name}", value, step=best_epoch)
        client.log_param(run_id, "best_epoch", best_epoch)
        for path in run_dir.iterdir():
            if path.is_file():
                client.log_artifact(run_id, str(path))
        client.log_artifacts(run_id, str(run_dir / "source"), artifact_path="source")
        client.set_terminated(run_id, status="FINISHED")
        return summary
    except BaseException as exc:
        if run_dir.exists():
            _write_json(run_dir / "failure.json", {"status": "failed", "error": str(exc), "run_id": run_id})
            client.log_artifact(run_id, str(run_dir / "failure.json"))
        client.set_terminated(run_id, status="FAILED")
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/train_t0.yaml"))
    parser.add_argument("--category", choices=CATEGORIES, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--root", type=Path, default=Path("data/raw/mvtec_ad"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/manifest.csv"))
    parser.add_argument("--synthetic-plan", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/transfer_runs"))
    parser.add_argument("--device", default="auto")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--imagenet-weights", type=Path)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_training(args.config, root=args.root, manifest=args.manifest, output_dir=args.output_dir,
                              category=args.category, seed=args.seed, device=args.device, smoke=args.smoke,
                              synthetic_plan=args.synthetic_plan, imagenet_weights=args.imagenet_weights,
                              allow_download=args.allow_download)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError) as exc:
        print(f"Entrainement transfert impossible : {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"run_id": result["run_id"], "output": result["run_dir"], "variant": result["variant"], "scope": result["scope"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
