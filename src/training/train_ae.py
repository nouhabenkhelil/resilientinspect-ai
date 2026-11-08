"""Entrainement B0/A1 par categorie ; apprentissage train, selection val, jamais test."""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from dataclasses import dataclass
from itertools import islice
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
import yaml

from resilientinspect.data.audit import _sha256
from resilientinspect.data.dataset import MVTecDataset
from resilientinspect.data.prepare import validate_preparation_settings
from resilientinspect.models.autoencoder import ConvAutoencoder


CATEGORIES = ("bottle", "hazelnut", "leather")


def load_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schema_version") != 1 or config.get("variant") not in ("B0", "A1"):
        raise ValueError("Configuration d'entrainement B0/A1 schema_version=1 attendue.")
    if config.get("category") not in CATEGORIES or type(config.get("seed")) is not int or not 0 <= config["seed"] < 2**32:
        raise ValueError("Categorie ou seed invalide.")
    schemas = {
        "root": {"schema_version", "variant", "category", "model_config", "dataset_config", "seed", "training", "smoke", "tracking"},
        "training": {"batch_size", "max_epochs", "optimizer", "learning_rate", "adam_betas", "adam_eps", "weight_decay",
                     "loss", "mixed_precision", "num_workers", "cpu_threads", "early_stopping"},
        "smoke": {"batch_size", "max_epochs", "max_batches_per_split"}, "tracking": {"experiment_name"},
    }
    for section, keys in schemas.items():
        values = config if section == "root" else config.get(section)
        if not isinstance(values, dict) or set(values) != keys:
            raise ValueError(f"Champs absents ou inconnus dans {section}.")
    training, smoke = config["training"], config["smoke"]
    for name in ("batch_size", "max_epochs", "cpu_threads"):
        if type(training[name]) is not int or training[name] < 1:
            raise ValueError(f"{name} doit etre un entier positif.")
    if type(training["num_workers"]) is not int or training["num_workers"] < 0:
        raise ValueError("num_workers doit etre un entier positif ou nul.")
    allowed_losses = ("l1",) if config["variant"] == "B0" else ("l1", "l1_ssim")
    if training["optimizer"] != "adam" or training["loss"] not in allowed_losses or training["mixed_precision"] is not False:
        raise ValueError("Adam, perte L1 (B0) ou L1/L1+SSIM (A1), mixed_precision=false requis.")
    for name in ("learning_rate", "adam_eps", "weight_decay"):
        value = training[name]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (name != "weight_decay" and value == 0):
            raise ValueError(f"{name} invalide.")
    betas = training["adam_betas"]
    if not isinstance(betas, list) or len(betas) != 2 or any(type(b) not in (int, float) or not 0 <= b < 1 for b in betas):
        raise ValueError("Adam exige deux betas dans [0,1[.")
    stop = training["early_stopping"]
    if type(stop["patience"]) is not int or stop["patience"] < 1:
        raise ValueError("patience doit etre un entier positif.")
    if type(stop["min_delta"]) not in (int, float) or not math.isfinite(stop["min_delta"]) or stop["min_delta"] < 0:
        raise ValueError("min_delta doit etre fini et positif ou nul.")
    if (type(smoke["max_epochs"]) is not int or smoke["max_epochs"] != 1
            or type(smoke["max_batches_per_split"]) is not int or not 1 <= smoke["max_batches_per_split"] <= 2
            or type(smoke["batch_size"]) is not int or not 1 <= smoke["batch_size"] <= 2):
        raise ValueError("Smoke limite a une epoque, deux batches par split et batch size <=2.")
    if not isinstance(config["tracking"]["experiment_name"], str) or not config["tracking"]["experiment_name"].strip():
        raise ValueError("Nom d'experience MLflow vide.")
    return config


def seed_everything(seed: int, cpu_threads: int) -> None:
    """Determinisme strict ; ne garantit pas l'identite entre versions ou devices."""
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(cpu_threads)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.set_float32_matmul_precision("highest")


def seed_worker(worker_id: int) -> None:
    seed = torch.initial_seed() % 2**32
    random.seed(seed)
    np.random.seed(seed)


def resolve_device(requested: str) -> torch.device:
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(requested)
    if device.type not in ("cpu", "cuda"):
        raise ValueError("Device attendu : cpu, cuda, cuda:N ou auto.")
    if device.type == "cuda" and (not torch.cuda.is_available()
                                  or (device.index is not None and device.index >= torch.cuda.device_count())):
        raise ValueError("Device CUDA demande mais indisponible ; aucun repli CPU silencieux.")
    return device


def build_loaders(manifest: Path, root: Path, category: str, training: dict[str, Any],
                  seed: int, device: torch.device, augmentation: dict[str, Any] | None = None) -> dict[str, DataLoader]:
    if category not in CATEGORIES:
        raise ValueError("Categorie inconnue.")
    frozen_path = Path(manifest).with_name("preparation.json")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if frozen["manifest_sha256"].get(Path(manifest).name) != _sha256(Path(manifest)):
        raise ValueError("Manifeste different de son empreinte figee.")
    loaders = {}
    for offset, split in enumerate(("train", "val")):
        dataset = MVTecDataset(manifest, root, split=split, categories=[category], verify_hashes=True)
        if any(row["label"] != "0" or row["source_split"] != "train" or row["mask_path"] for row in dataset.rows):
            raise ValueError("Train/val exigent uniquement des normaux issus du train officiel.")
        if augmentation is not None and split == "train":
            from resilientinspect.data.augment import TrainAugmentedDataset
            dataset = TrainAugmentedDataset(dataset, augmentation, seed)
        loaders[split] = DataLoader(
            dataset, batch_size=training["batch_size"], shuffle=split == "train", drop_last=False,
            num_workers=training["num_workers"], pin_memory=device.type == "cuda",
            generator=torch.Generator().manual_seed(seed + offset), worker_init_fn=seed_worker,
        )
    return loaders


@dataclass
class EarlyStopping:
    patience: int
    min_delta: float = 0.0
    reference: float = math.inf
    bad_epochs: int = 0

    def update(self, validation_loss: float) -> bool:
        """Retourne True apres patience epoques sans amelioration significative."""
        if not math.isfinite(validation_loss):
            raise ValueError("Perte de validation non finie.")
        if validation_loss < self.reference - self.min_delta:
            self.reference, self.bad_epochs = validation_loss, 0
        else:
            self.bad_epochs += 1
        return self.bad_epochs >= self.patience


def run_epoch(model: nn.Module, loader: DataLoader, device: torch.device,
              optimizer: torch.optim.Optimizer | None = None, max_batches: int | None = None,
              criterion: nn.Module | None = None) -> dict[str, Any]:
    training = optimizer is not None
    model.train(training)
    total, count, batches, paths = 0.0, 0, 0, []
    component_totals = {}
    iterator = islice(loader, max_batches) if max_batches is not None else iter(loader)
    with torch.set_grad_enabled(training):
        for batch in iterator:
            if any(split != ("train" if training else "val") for split in batch["split"]):
                raise ValueError("Split interdit dans la boucle d'entrainement/validation.")
            images = batch["image"].to(device, non_blocking=device.type == "cuda")
            if training:
                optimizer.zero_grad(set_to_none=True)
            reconstruction = model(images)
            components = criterion.components(reconstruction, images) if criterion is not None else {}
            loss = components["loss"] if criterion is not None else nn.functional.l1_loss(reconstruction, images, reduction="mean")
            if not torch.isfinite(loss):
                raise ValueError("Perte non finie ; run interrompu sans selection invalide.")
            if training:
                loss.backward()
                finite = [torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None]
                if not finite or not torch.stack(finite).all():
                    raise ValueError("Gradients non finis ; mise a jour refusee.")
                optimizer.step()
            size = images.shape[0]
            total += float(loss.detach()) * size
            for name, value in components.items():
                if name != "loss":
                    component_totals[name] = component_totals.get(name, 0.0) + float(value.detach()) * size
            count += size
            batches += 1
            paths.extend(batch["image_path"])
    if not count:
        raise ValueError("Aucun mini-batch disponible.")
    return {"loss": total / count, "images": count, "batches": batches, "image_paths": paths,
            **{name: value / count for name, value in component_totals.items()}}


def save_best_checkpoint(path: Path, model: nn.Module, optimizer: torch.optim.Optimizer,
                         *, epoch: int, val_loss: float, metadata: dict[str, Any]) -> None:
    temporary = path.with_suffix(".pt.tmp")
    torch.save({"model_state_dict": {key: value.detach().cpu().clone() for key, value in model.state_dict().items()},
                "optimizer_state_dict": optimizer.state_dict(), "epoch": epoch, "val_loss": val_loss,
                **metadata}, temporary)
    temporary.replace(path)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _plot_history(history: list[dict[str, Any]], path: Path, category: str, scope: str, run_id: str,
                  variant: str = "B0", loss_name: str = "L1") -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(path.parent / ".matplotlib"))
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    figure = Figure(figsize=(7, 4.5), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    for split in ("train", "val"):
        axis.plot([row["epoch"] for row in history], [row[f"{split}_loss"] for row in history],
                  marker="o", label=f"{split} {loss_name}")
    axis.set(title=f"{variant} | {category} | {scope} | {run_id[:8]}", xlabel="Epoque", ylabel=f"{loss_name} moyenne")
    axis.legend()
    axis.grid(alpha=0.2)
    figure.savefig(path, dpi=140)
    figure.clear()


def run_training(config_path: Path, *, root: Path, manifest: Path, output_dir: Path,
                 category: str | None = None, device: str = "auto", smoke: bool = False) -> dict[str, Any]:
    """Nouvelle instance B0/A1 et nouvel Adam par appel ; aucun resume implicite."""
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    variant = config["variant"]
    category = config["category"] if category is None else category
    root, manifest, output_dir = Path(root).resolve(), Path(manifest).resolve(), Path(output_dir).resolve()
    project = Path(__file__).resolve().parents[2]
    if any(output_dir.is_relative_to(project / protected) for protected in ("artifacts/b0_runs", "reports/evaluation/b0")):
        raise ValueError("Sorties interdites dans les poids ou resultats B0 figes.")
    if not root.is_dir():
        raise ValueError("Racine du dataset absente.")
    for destination in (output_dir, output_dir / "mlflow.db", output_dir / "mlartifacts"):
        resolved = destination.resolve()
        if resolved.is_relative_to(root) or resolved.is_relative_to(manifest.parent) or destination.is_symlink():
            raise ValueError("Les sorties doivent rester hors des donnees et manifestes.")
    dataset_config_path = (config_path.parent / config["dataset_config"]).resolve()
    dataset_config = yaml.safe_load(dataset_config_path.read_text(encoding="utf-8"))
    validate_preparation_settings(dataset_config)
    model_config_path = (config_path.parent / config["model_config"]).resolve()
    model_config = yaml.safe_load(model_config_path.read_text(encoding="utf-8"))
    if variant == "B0" and (model_config["model"]["name"] != "B0" or model_config["model"]["kwargs"]["channels"] != [16, 32, 64, 128]
            or model_config["loss"]["name"] != "l1" or model_config["loss"]["kwargs"] != {"reduction": "mean"}):
        raise ValueError("Architecture B0 et perte L1 validees requises.")
    if variant == "A1":
        from .a1_config import validate_a1_config
        validate_a1_config(model_config, config["training"]["loss"])
    seed_everything(config["seed"], config["training"]["cpu_threads"])
    target_device = resolve_device(device)
    if variant == "A1" and target_device.type == "cpu" and not smoke:
        raise ValueError("A1 complet reserve a CUDA ; utiliser --smoke pour la verification CPU.")
    effective = deepcopy(config)
    effective["category"] = category
    effective["scope"] = "smoke" if smoke else "full"
    effective["device"] = str(target_device)
    training = effective["training"]
    max_batches = None
    if smoke:
        training.update(batch_size=config["smoke"]["batch_size"], max_epochs=1, num_workers=0)
        max_batches = config["smoke"]["max_batches_per_split"]
    effective["max_batches_per_split"] = max_batches
    augmentation, criterion = None, None
    if variant == "A1":
        from resilientinspect.models.autoencoder_improved import ImprovedAutoencoder
        from .losses import ReconstructionLoss
        effective["architecture"] = deepcopy(model_config)
        augmentation = model_config["augmentation"]
        criterion = ReconstructionLoss(**model_config["loss"]).to(target_device)
        model = ImprovedAutoencoder(**model_config["model"]["kwargs"]).to(target_device)
    else:
        model = ConvAutoencoder(**model_config["model"]["kwargs"]).to(target_device)
    loaders = build_loaders(manifest, root, category, training, config["seed"], target_device, augmentation=augmentation)
    optimizer = torch.optim.Adam(model.parameters(), lr=training["learning_rate"], betas=tuple(training["adam_betas"]),
                                 eps=training["adam_eps"], weight_decay=training["weight_decay"])
    stopper = EarlyStopping(**training["early_stopping"])
    # Le tracking est obligatoire, explicite et local ; pas d'autolog ni d'installation de paquets.
    from mlflow import MlflowClient, __version__ as mlflow_version
    output_dir.mkdir(parents=True, exist_ok=True)
    tracking_uri = f"sqlite:///{(output_dir / 'mlflow.db').as_posix()}"
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment_name = config["tracking"]["experiment_name"]
    experiment = client.get_experiment_by_name(experiment_name)
    experiment_id = experiment.experiment_id if experiment else client.create_experiment(
        experiment_name, artifact_location=(output_dir / "mlartifacts").as_uri())
    scope = effective["scope"]
    run_name = f"{variant}-{category}-{scope}-seed{config['seed']}"
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2],
                         capture_output=True, text=True, check=False)
    git_sha = git.stdout.strip() if git.returncode == 0 else "unavailable"
    source_paths = [config_path, model_config_path, dataset_config_path, Path(__file__),
                    Path(__file__).parents[2] / "pyproject.toml", Path(__file__).parents[1] / "models/autoencoder.py",
                    *(Path(__file__).parents[1] / "data" / name for name in ("dataset.py", "prepare.py", "audit.py"))]
    if variant == "A1":
        source_paths.extend([Path(__file__).with_name("losses.py"), Path(__file__).with_name("a1_config.py"),
                             Path(__file__).parents[1] / "models/autoencoder_improved.py", Path(__file__).parents[1] / "data/augment.py"])
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=Path(__file__).resolve().parents[2],
                           capture_output=True, text=True, check=False)
    provenance = {"manifest_sha256": _sha256(manifest), "manifest_path": str(manifest), "dataset_root": str(root), "git_sha": git_sha,
                  "git_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
                  "source_sha256": {str(path): _sha256(path) for path in source_paths}}
    tags = {"mlflow.runName": run_name, "variant": variant, "category": category,
            "scope": scope, "seed": str(config["seed"]), "dataset_version": provenance["manifest_sha256"],
            "git_sha": git_sha, "selection_split": "val", "test_used": "false"}
    mlrun = client.create_run(experiment_id, tags=tags)
    run_id = mlrun.info.run_id
    run_dir = output_dir / category / f"{scope}_{run_id}"
    history, best_loss, best_epoch = [], math.inf, 0
    seen = {"train": set(), "val": set()}
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "effective_config.yaml").write_text(yaml.safe_dump(effective, sort_keys=False), encoding="utf-8")
        (run_dir / "architecture.yaml").write_bytes(model_config_path.read_bytes())
        (run_dir / "dataset_config.yaml").write_bytes(dataset_config_path.read_bytes())
        (run_dir / "source").mkdir()
        for path in source_paths:
            (run_dir / "source" / path.name).write_bytes(path.read_bytes())
        environment = {"python": sys.version.split()[0], "torch": str(torch.__version__), "numpy": np.__version__,
                       "mlflow": mlflow_version, "device": str(target_device), "cuda_runtime": torch.version.cuda,
                       "gpu_name": torch.cuda.get_device_name(target_device) if target_device.type == "cuda" else None,
                       "cpu_threads": torch.get_num_threads(), "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                       "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"], "mixed_precision": False,
                       "cudnn_version": torch.backends.cudnn.version() if target_device.type == "cuda" else None,
                       "packages": {name: version(name) for name in ("Pillow", "PyYAML", "matplotlib", "sqlalchemy", "alembic")}}
        _write_json(run_dir / "environment.json", environment)
        _write_json(run_dir / "provenance.json", provenance)
        loss_name = "L1_mean" if variant == "B0" else training["loss"]
        params = {"variant": variant, "category": category, "scope": scope, "seed": config["seed"],
                  "batch_size": training["batch_size"], "max_epochs": training["max_epochs"],
                  "learning_rate": training["learning_rate"], "optimizer": "Adam", "loss": loss_name,
                  "adam_betas": str(training["adam_betas"]), "adam_eps": training["adam_eps"],
                  "weight_decay": training["weight_decay"], "patience": stopper.patience, "min_delta": stopper.min_delta,
                  "mixed_precision": False, "num_workers": training["num_workers"], "device": str(target_device),
                  "image_size": "256x256", "preprocessing": "letterbox_bilinear_nearest_div255",
                  "parameters": sum(p.numel() for p in model.parameters()), "max_batches_per_split": str(max_batches),
                  "train_available": len(loaders["train"].dataset), "val_available": len(loaders["val"].dataset),
                  "torch_version": str(torch.__version__), "manifest_sha256": provenance["manifest_sha256"]}
        if variant == "A1":
            params.update({f"architecture.{name}": value for name, value in model_config["model"]["kwargs"].items()})
            params.update({f"loss.{name}": value for name, value in model_config["loss"].items()})
            params.update({f"augmentation.{name}": value for name, value in model_config["augmentation"].items()})
        for name, value in params.items():
            client.log_param(run_id, name, value)
        with (run_dir / "history.csv").open("w", newline="", encoding="utf-8") as stream:
            fields = ["epoch", "train_loss", "val_loss", "train_images", "val_images", "train_batches", "val_batches"]
            if variant == "A1":
                component_names = ["l1_loss"] + (["ssim_loss"] if training["loss"] == "l1_ssim" else [])
                fields.extend(f"{split}_{name}" for split in ("train", "val") for name in component_names)
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            for epoch in range(1, training["max_epochs"] + 1):
                if hasattr(loaders["train"].dataset, "set_epoch"):
                    loaders["train"].dataset.set_epoch(epoch)
                kwargs = {"criterion": criterion} if criterion is not None else {}
                train = run_epoch(model, loaders["train"], target_device, optimizer, max_batches, **kwargs)
                validation = run_epoch(model, loaders["val"], target_device, max_batches=max_batches, **kwargs)
                for split, result in (("train", train), ("val", validation)):
                    seen[split].update(result["image_paths"])
                row = {"epoch": epoch, "train_loss": train["loss"], "val_loss": validation["loss"],
                       "train_images": train["images"], "val_images": validation["images"],
                       "train_batches": train["batches"], "val_batches": validation["batches"]}
                if variant == "A1":
                    row.update({f"{split}_{name}": result[name] for split, result in (("train", train), ("val", validation))
                                for name in component_names})
                history.append(row)
                writer.writerow(row)
                stream.flush()
                for metric in fields[1:]:
                    client.log_metric(run_id, metric, row[metric], step=epoch)
                if validation["loss"] < best_loss:
                    best_loss, best_epoch = validation["loss"], epoch
                    save_best_checkpoint(run_dir / "best.pt", model, optimizer, epoch=epoch, val_loss=best_loss,
                                         metadata={"variant": variant, "category": category, "scope": scope,
                                                   "seed": config["seed"], "effective_config": effective,
                                                   **({"architecture": deepcopy(model_config)} if variant == "A1" else {}),
                                                   "manifest_sha256": provenance["manifest_sha256"]})
                print(json.dumps({"category": category, "scope": scope, **row}), flush=True)
                if stopper.update(validation["loss"]):
                    break
        summary = {"status": "completed", "run_id": run_id, "run_dir": str(run_dir), "tracking_uri": tracking_uri,
                   "category": category, "variant": variant, "scope": scope, "epochs_completed": len(history),
                   "best_epoch": best_epoch, "best_val_loss": best_loss, "selection_split": "val", "test_used": False,
                   "stopped_early": stopper.bad_epochs >= stopper.patience, "history": history,
                   "checkpoint_sha256": _sha256(run_dir / "best.pt"), **provenance}
        _write_json(run_dir / "summary.json", summary)
        _write_json(run_dir / "data_usage.json", {split: sorted(paths) for split, paths in seen.items()})
        _plot_history(history, run_dir / "loss_curves.png", category, scope, run_id, variant=variant, loss_name=loss_name)
        client.log_metric(run_id, "best_val_loss", best_loss, step=best_epoch)
        client.log_param(run_id, "best_epoch", best_epoch)
        for artifact in run_dir.iterdir():
            if artifact.is_file():
                client.log_artifact(run_id, str(artifact))
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
    parser.add_argument("--config", type=Path, default=Path("configs/train_ae_b0.yaml"))
    parser.add_argument("--root", type=Path, default=Path("data/raw/mvtec_ad"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/manifest.csv"))
    parser.add_argument("--category", choices=CATEGORIES, default=None)
    parser.add_argument("--device", default="auto", help="cpu, cuda, cuda:N ou auto")
    parser.add_argument("--output-dir", type=Path, default=None, help="Defaut : artifacts/training (B0), artifacts/a1_runs (A1)")
    parser.add_argument("--smoke", action="store_true", help="1 epoque, batch size 2, au plus 2 batches par split")
    args = parser.parse_args(argv)
    try:
        output = args.output_dir or Path("artifacts/a1_runs" if load_config(args.config)["variant"] == "A1" else "artifacts/training")
        result = run_training(args.config, root=args.root, manifest=args.manifest, output_dir=output,
                              category=args.category, device=args.device, smoke=args.smoke)
    except (OSError, ValueError, KeyError, RuntimeError, ImportError) as exc:
        print(f"Entrainement impossible : {exc}", file=sys.stderr)
        return 1
    print(json.dumps({key: result[key] for key in ("run_id", "run_dir", "category", "scope", "best_epoch", "best_val_loss")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
