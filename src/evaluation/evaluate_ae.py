"""B0 : calibration sur val normale, evaluation test seulement apres revue SHA."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from importlib.metadata import version
import csv
import io
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader
import yaml

from resilientinspect.data.audit import _sha256
from resilientinspect.data.dataset import MVTecDataset
from resilientinspect.models.autoencoder import ConvAutoencoder
from resilientinspect.training.train_ae import resolve_device, seed_everything

CATEGORIES = ("bottle", "hazelnut", "leather")


@dataclass(frozen=True)
class Checkpoint:
    category: str
    path: str
    run_id: str
    sha256: str
    manifest_sha256: str
    best_epoch: int


def load_protocol(path: Path) -> dict[str, Any]:
    protocol = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    fixed = {"schema_version": 1, "protocol_id": "b0_l1_top01_quantiles_v1", "categories": list(CATEGORIES),
             "anomaly_map": "rgb_mean_absolute_error", "smoothing": "none", "resolution": [256, 256],
             "padding": "exclude_valid_mask_zero", "quantile_method": "higher", "decision": "strictly_greater"}
    variable = {"image_top_fraction", "image_threshold_quantile", "pixel_threshold_quantile",
                "figures_per_defect", "batch_size", "cpu_threads", "seed"}
    if not isinstance(protocol, dict) or set(protocol) != set(fixed) | variable:
        raise ValueError("Schema de protocole inconnu ou incomplet.")
    if any(protocol[key] != value for key, value in fixed.items()):
        raise ValueError("Contrat L1 256x256, sans lissage, attendu.")
    for key in ("image_top_fraction", "image_threshold_quantile", "pixel_threshold_quantile"):
        value = protocol[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError(f"{key} doit etre dans ]0,1].")
    for key in ("figures_per_defect", "batch_size", "cpu_threads"):
        if type(protocol[key]) is not int or protocol[key] < 1:
            raise ValueError(f"{key} doit etre un entier positif.")
    if type(protocol["seed"]) is not int or not 0 <= protocol["seed"] < 2**32:
        raise ValueError("Seed invalide.")
    return protocol


def manifest_digest(manifest: Path) -> str:
    digest = _sha256(manifest)
    frozen = json.loads(manifest.with_name("preparation.json").read_text(encoding="utf-8"))
    if frozen["manifest_sha256"].get(manifest.name) != digest:
        raise ValueError("Manifeste different de son empreinte figee.")
    return digest


def discover_checkpoints(runs_root: Path) -> tuple[dict[str, Checkpoint], list[dict[str, str]]]:
    """category/full_*/best.pt ; pas de choix silencieux entre runs distincts."""
    root = Path(runs_root).resolve()
    candidates: dict[str, list[Checkpoint]] = {category: [] for category in CATEGORIES}
    excluded = []
    for path in sorted(root.rglob("best.pt")):
        parts = path.relative_to(root).parts
        reason = None
        if any(part.lower() in ("mlartifacts", "mlruns") for part in parts):
            reason = "mlflow_copy"
        elif any(part.startswith("smoke_") for part in parts):
            reason = "smoke"
        elif len(parts) != 3 or parts[0] not in CATEGORIES or not parts[1].startswith("full_"):
            reason = "non_canonical_layout"
        if reason:
            excluded.append({"path": str(path), "reason": reason})
            continue
        summary = json.loads(path.with_name("summary.json").read_text(encoding="utf-8"))
        effective = yaml.safe_load(path.with_name("effective_config.yaml").read_text(encoding="utf-8"))
        category = parts[0]
        if summary.get("scope") == "smoke" or effective.get("scope") == "smoke":
            excluded.append({"path": str(path), "reason": "smoke_metadata"})
            continue
        if (summary.get("status") != "completed" or summary.get("scope") != "full"
                or summary.get("category") != category or summary.get("selection_split") != "val"
                or summary.get("test_used") is not False or effective.get("variant") != "B0"
                or effective.get("scope") != "full" or effective.get("category") != category
                or effective.get("max_batches_per_split", "missing") is not None):
            raise ValueError(f"Run complet B0 invalide : {path.parent}")
        epoch = summary["best_epoch"]
        if type(epoch) is not int or not 1 <= epoch <= summary["epochs_completed"]:
            raise ValueError("Epoque du checkpoint incoherente.")
        digest = _sha256(path)
        if digest != summary["checkpoint_sha256"]:
            raise ValueError(f"Empreinte checkpoint invalide : {path}")
        candidates[category].append(Checkpoint(category, str(path), summary["run_id"], digest,
                                                summary["manifest_sha256"], epoch))
    selected = {}
    for category, items in candidates.items():
        if not items:
            raise ValueError(f"Aucun checkpoint complet canonique pour {category}.")
        if len({item.sha256 for item in items}) != 1:
            raise ValueError(f"Plusieurs runs complets distincts pour {category} : selection explicite requise.")
        selected[category] = items[0]
        excluded.extend({"path": item.path, "reason": "identical_checkpoint_copy"} for item in items[1:])
    return selected, excluded


def load_model(checkpoint: Checkpoint, device: torch.device, expected_manifest: str) -> ConvAutoencoder:
    if checkpoint.manifest_sha256 != expected_manifest or _sha256(Path(checkpoint.path)) != checkpoint.sha256:
        raise ValueError("Checkpoint ou manifeste different de la selection.")
    saved = torch.load(checkpoint.path, map_location="cpu", weights_only=True)
    effective = saved.get("effective_config", {})
    if (saved.get("variant") != "B0" or saved.get("scope") != "full" or saved.get("category") != checkpoint.category
            or saved.get("manifest_sha256") != expected_manifest or saved.get("epoch") != checkpoint.best_epoch
            or effective.get("scope") != "full" or effective.get("variant") != "B0"
            or effective.get("category") != checkpoint.category
            or effective.get("max_batches_per_split", "missing") is not None):
        raise ValueError("Le contenu du checkpoint n'est pas un B0 complet coherent.")
    model = ConvAutoencoder()
    model.load_state_dict(saved["model_state_dict"], strict=True)
    if not all(torch.isfinite(tensor).all() for tensor in model.state_dict().values()):
        raise ValueError("Poids ou buffers non finis.")
    return model.to(device).eval().requires_grad_(False)


def anomaly_maps(images: torch.Tensor, reconstruction: torch.Tensor) -> torch.Tensor:
    if images.ndim != 4 or images.shape[1] != 3 or images.shape != reconstruction.shape:
        raise ValueError("Deux tenseurs RGB BCHW de meme forme sont requis.")
    if not torch.isfinite(images).all() or not torch.isfinite(reconstruction).all():
        raise ValueError("Image ou reconstruction non finie.")
    if images.min() < 0 or images.max() > 1 or reconstruction.min() < 0 or reconstruction.max() > 1:
        raise ValueError("Pixels attendus dans [0,1].")
    return (images - reconstruction).abs().mean(dim=1)


def valid_values(error: np.ndarray, valid: np.ndarray) -> np.ndarray:
    if error.ndim != 2 or error.shape != valid.shape or not np.isfinite(error).all():
        raise ValueError("Carte finie et validite de meme geometrie requises.")
    if not np.isin(valid, [0, 1]).all() or not np.any(valid) or error.min() < 0 or error.max() > 1:
        raise ValueError("Pixels valides absents ou carte hors [0,1].")
    return error[np.asarray(valid, dtype=bool)]


def image_score(error: np.ndarray, valid: np.ndarray, top_fraction: float = 0.01) -> float:
    if not 0 < top_fraction <= 1:
        raise ValueError("Fraction top-k invalide.")
    values = valid_values(error, valid)
    k = math.ceil(top_fraction * values.size)
    return float(np.partition(values, values.size - k)[-k:].mean(dtype=np.float64))


def calibrate_records(records: list[dict[str, Any]], protocol: dict[str, Any]) -> dict[str, Any]:
    if not records or any(row["split"] != "val" or row["label"] != 0 or row["source_split"] != "train"
                          or row["mask_path"] for row in records):
        raise ValueError("Calibration reservee aux normaux val issus du train officiel.")
    scores = [image_score(row["error"], row["valid"], protocol["image_top_fraction"]) for row in records]
    pixels = np.concatenate([valid_values(row["error"], row["valid"]) for row in records])
    image_threshold = float(np.quantile(scores, protocol["image_threshold_quantile"], method="higher"))
    pixel_threshold = float(np.quantile(pixels, protocol["pixel_threshold_quantile"], method="higher"))
    return {"image_threshold": image_threshold, "pixel_threshold": pixel_threshold,
            "validation_images": len(records), "validation_pixels": int(pixels.size),
            "empirical_image_fpr": float(np.mean(np.asarray(scores) > image_threshold)),
            "empirical_pixel_fpr": float(np.mean(pixels > pixel_threshold)),
            "validation_scores": [{"image_path": row["image_path"], "score": score} for row, score in zip(records, scores)]}


def ranking_metrics(labels: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, roc_auc_score
    labels, scores = np.asarray(labels).ravel(), np.asarray(scores).ravel()
    if labels.size == 0 or labels.shape != scores.shape or not np.isin(labels, [0, 1]).all() or not np.isfinite(scores).all():
        raise ValueError("Labels binaires et scores finis apparies requis.")
    if np.unique(labels).size < 2:
        return {"auroc": None, "ap": None, "undefined_reason": "both_classes_required"}
    return {"auroc": float(roc_auc_score(labels, scores)), "ap": float(average_precision_score(labels, scores)),
            "undefined_reason": None}


def overlap_metrics(target: np.ndarray, predicted: np.ndarray) -> dict[str, Any]:
    if target.shape != predicted.shape or not np.isin(target, [0, 1]).all() or not np.isin(predicted, [0, 1]).all():
        raise ValueError("Masques binaires de meme forme requis.")
    target, predicted = target.astype(bool), predicted.astype(bool)
    tp, fp, fn = (int(np.count_nonzero(values)) for values in (target & predicted, ~target & predicted, target & ~predicted))
    return {"tp": tp, "fp": fp, "fn": fn,
            "dice": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
            "iou": tp / (tp + fp + fn) if tp + fp + fn else None}


def summarize_records(records: list[dict[str, Any]], calibration: dict[str, Any], protocol: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not records or any(row["split"] != "test" for row in records):
        raise ValueError("Le rapport final exige un split test explicite.")
    it, pt = _thresholds(calibration)
    rows, pixel_labels, pixel_scores = [], [], []
    for record in records:
        error, valid, mask = record["error"], record["valid"].astype(bool), record["mask"]
        values = valid_values(error, record["valid"])
        if mask.shape != valid.shape or not np.isin(mask, [0, 1]).all() or record["label"] not in (0, 1):
            raise ValueError("Ground truth invalide.")
        if record["label"] == 0 and mask.any():
            raise ValueError("Un normal ne peut pas avoir de masque positif.")
        score = image_score(error, valid, protocol["image_top_fraction"])
        rows.append({"image_path": record["image_path"], "category": record["category"], "split": "test",
                     "label": record["label"], "defect_type": record["defect_type"], "mask_path": record["mask_path"],
                     "score": score, "image_threshold": it, "pixel_threshold": pt, "predicted_label": int(score > it),
                     "valid_pixels": int(valid.sum()), "empty_anomalous_mask": bool(record["label"] == 1 and not mask[valid].any()),
                     **overlap_metrics(mask[valid], values > pt)})
        pixel_labels.append(mask[valid].astype(np.uint8))
        pixel_scores.append(values)
    tp, fp, fn = (sum(row[key] for row in rows) for key in ("tp", "fp", "fn"))
    metrics = {"images": len(rows), "anomalous_images": sum(row["label"] for row in rows),
               "valid_pixels": sum(row["valid_pixels"] for row in rows),
               "image": ranking_metrics(np.array([row["label"] for row in rows]), np.array([row["score"] for row in rows])),
               "pixel": ranking_metrics(np.concatenate(pixel_labels), np.concatenate(pixel_scores)),
               "segmentation_micro": {"tp": tp, "fp": fp, "fn": fn,
                                      "dice": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
                                      "iou": tp / (tp + fp + fn) if tp + fp + fn else None},
               "empty_anomalous_masks": sum(row["empty_anomalous_mask"] for row in rows)}
    labels = np.array([row["label"] for row in rows])
    predictions = np.array([row["predicted_label"] for row in rows])
    image_overlap = overlap_metrics(labels, predictions)
    metrics["image_decision"] = {"tn": int(np.count_nonzero((labels == 0) & (predictions == 0))),
                                 "tp": image_overlap["tp"], "fp": image_overlap["fp"], "fn": image_overlap["fn"],
                                 "f1": image_overlap["dice"], "positive_class": 1}
    for key in ("dice", "iou"):
        values = [row[key] for row in rows if row["label"] == 1 and row[key] is not None]
        metrics[f"{key}_macro_anomalous"] = float(np.mean(values)) if values else None
        metrics[f"{key}_macro_anomalous_n"] = len(values)
    return metrics, rows


def infer_records(model: ConvAutoencoder, manifest: Path, root: Path, category: str, split: str,
                  protocol: dict[str, Any], device: torch.device) -> list[dict[str, Any]]:
    if split not in ("val", "test"):
        raise ValueError("Inference limitee a val ou test.")
    dataset = MVTecDataset(manifest, root, split=split, categories=[category], verify_hashes=True)
    dataset.rows.sort(key=lambda row: row["image_path"])
    if split == "val" and any(row["label"] != "0" or row["source_split"] != "train" or row["mask_path"] for row in dataset.rows):
        raise ValueError("Validation normale officielle requise.")
    loader = DataLoader(dataset, batch_size=protocol["batch_size"], shuffle=False, num_workers=0,
                        generator=torch.Generator().manual_seed(protocol["seed"]))
    records = []
    model.eval()
    with torch.inference_mode():
        for batch in loader:
            images = batch["image"].to(device)
            reconstructed = model(images)
            errors = anomaly_maps(images, reconstructed).cpu().numpy()
            for index, error in enumerate(errors):
                row = {"image_path": batch["image_path"][index], "mask_path": batch["mask_path"][index], "category": category,
                       "split": split, "source_split": "train" if split == "val" else "test",
                       "defect_type": batch["defect_type"][index], "label": int(batch["label"][index]),
                       "error": error.copy(), "valid": batch["valid_mask"][index, 0].numpy().astype(bool)}
                if split == "test":
                    row.update(image=images[index].cpu().numpy(), reconstruction=reconstructed[index].cpu().numpy(),
                               mask=batch["mask"][index, 0].numpy().astype(bool))
                records.append(row)
    return records


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _write_once(path: Path, data: bytes) -> None:
    if path.is_symlink() or (path.exists() and path.read_bytes() != data):
        raise ValueError(f"Resultat existant different, aucun ecrasement : {path}")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _write_once(path, stream.getvalue().encode("utf-8"))


def binding(protocol_path: Path, checkpoint: Checkpoint, digest: str) -> dict[str, str]:
    return {"protocol_sha256": _sha256(protocol_path), "checkpoint_sha256": checkpoint.sha256,
            "manifest_sha256": digest, "evaluation_code_sha256": _sha256(Path(__file__)),
            "dataset_code_sha256": _sha256(Path(__file__).parents[1] / "data/dataset.py")}


def _safe_output(output: Path, root: Path, manifest: Path, runs_root: Path) -> None:
    if any(output.resolve().is_relative_to(path.resolve()) for path in (root, manifest.parent, runs_root)):
        raise ValueError("Sorties interdites dans les donnees, manifestes ou checkpoints.")


def _environment(device: torch.device) -> dict[str, Any]:
    return {"python": sys.version.split()[0], "device": str(device), "torch": str(torch.__version__),
            "numpy": np.__version__, "scikit_learn": version("scikit-learn"), "cuda_runtime": torch.version.cuda}


def calibrate_category(checkpoint: Checkpoint, *, protocol_path: Path, root: Path, manifest: Path,
                       output: Path, device: torch.device) -> dict[str, Any]:
    _safe_output(output, root, manifest, Path(checkpoint.path).parents[2])
    protocol = load_protocol(protocol_path)
    seed_everything(protocol["seed"], protocol["cpu_threads"])
    digest = manifest_digest(manifest)
    records = infer_records(load_model(checkpoint, device, digest), manifest, root, checkpoint.category, "val", protocol, device)
    result = {"category": checkpoint.category, "calibration_split": "val", "normal_only": True,
              "checkpoint": asdict(checkpoint), "environment": _environment(device),
              **binding(protocol_path, checkpoint, digest), **calibrate_records(records, protocol)}
    _write_once(output / "calibration.json", _json_bytes(result))
    _write_once(output / "calibration.sha256", (_sha256(output / "calibration.json") + "\n").encode("ascii"))
    _write_csv(output / "calibration_scores.csv", result["validation_scores"])
    return result


def require_approval(protocol_path: Path, approved_sha256: str | None) -> None:
    if approved_sha256 != _sha256(protocol_path):
        raise ValueError("Test bloque : validation du protocole requise (--approved-protocol-sha256 exact).")


def _thresholds(calibration: dict[str, Any]) -> tuple[float, float]:
    values = calibration["image_threshold"], calibration["pixel_threshold"]
    if not all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1 for value in values):
        raise ValueError("Seuils invalides.")
    return values


def _figures(records: list[dict[str, Any]], protocol: dict[str, Any], checkpoint: Checkpoint, output: Path) -> list[str]:
    os.environ.setdefault("MPLCONFIGDIR", str(output / ".matplotlib"))
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    counts, figures = {}, []
    for row in sorted(records, key=lambda row: (row["defect_type"], row["image_path"])):
        defect = row["defect_type"]
        if counts.get(defect, 0) >= protocol["figures_per_defect"]:
            continue
        counts[defect] = counts.get(defect, 0) + 1
        figure = Figure(figsize=(12, 3.4), layout="constrained")
        FigureCanvasAgg(figure)
        axes = figure.subplots(1, 4)
        arrays = (row["image"].transpose(1, 2, 0), row["reconstruction"].transpose(1, 2, 0), row["error"], row["mask"])
        for index, (axis, array, title) in enumerate(zip(axes, arrays, ("Entree RGB 256x256", "Reconstruction", "Erreur L1 RGB moyenne", "Masque GT nearest"))):
            artist = axis.imshow(array, interpolation="nearest", cmap="magma" if index == 2 else "gray", vmin=0, vmax=1)
            axis.set_title(title, fontsize=10)
            axis.axis("off")
            if index == 2:
                figure.colorbar(artist, ax=axis, fraction=0.04)
        figure.suptitle(f"{checkpoint.category} | test/{defect} | {Path(row['image_path']).name} | B0 {checkpoint.run_id[:8]}")
        filename = f"{defect}_{Path(row['image_path']).stem}.png"
        stream = io.BytesIO()
        figure.savefig(stream, format="png", dpi=120)
        _write_once(output / "figures" / filename, stream.getvalue())
        figure.clear()
        figures.append(filename)
    return figures


def evaluate_category(checkpoint: Checkpoint, *, protocol_path: Path, approved_sha256: str | None,
                      root: Path, manifest: Path, output: Path, device: torch.device) -> dict[str, Any]:
    require_approval(protocol_path, approved_sha256)  # Avant de construire le Dataset test.
    _safe_output(output, root, manifest, Path(checkpoint.path).parents[2])
    protocol = load_protocol(protocol_path)
    seed_everything(protocol["seed"], protocol["cpu_threads"])
    digest = manifest_digest(manifest)
    calibration_path = output / "calibration.json"
    if calibration_path.with_suffix(".sha256").read_text(encoding="ascii").strip() != _sha256(calibration_path):
        raise ValueError("Calibration modifiee : empreinte invalide ; aucun test execute.")
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    expected = binding(protocol_path, checkpoint, digest)
    if (any(calibration.get(key) != value for key, value in expected.items()) or calibration.get("category") != checkpoint.category
            or calibration.get("calibration_split") != "val" or calibration.get("normal_only") is not True):
        raise ValueError("Calibration perimee ou incompatible ; aucun test execute.")
    _thresholds(calibration)  # Un artefact invalide ne doit pas declencher d'inference test.
    records = infer_records(load_model(checkpoint, device, digest), manifest, root, checkpoint.category, "test", protocol, device)
    metrics, rows = summarize_records(records, calibration, protocol)
    report = {"category": checkpoint.category, "split": "test", "checkpoint": asdict(checkpoint), **expected,
              "calibration_sha256": _sha256(calibration_path), "image_threshold": calibration["image_threshold"],
              "pixel_threshold": calibration["pixel_threshold"], "metrics": metrics,
              "resolution": [256, 256], "padding_excluded": True, "environment": _environment(device)}
    report["figures"] = _figures(records, protocol, checkpoint, output)
    _write_csv(output / "predictions.csv", rows)
    _write_once(output / "metrics.json", _json_bytes(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("inspect", "calibrate", "evaluate"), default="inspect")
    parser.add_argument("--protocol", type=Path, default=Path("configs/evaluate_ae_b0.yaml"))
    parser.add_argument("--runs-root", type=Path, default=Path("artifacts/b0_runs"))
    parser.add_argument("--root", type=Path, default=Path("data/raw/mvtec_ad"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/manifest.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/evaluation/b0"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--approved-protocol-sha256")
    args = parser.parse_args(argv)
    try:
        protocol = load_protocol(args.protocol)
        if args.stage == "evaluate":
            require_approval(args.protocol, args.approved_protocol_sha256)
        _safe_output(args.output_dir, args.root, args.manifest, args.runs_root)
        digest = manifest_digest(args.manifest)
        selected, excluded = discover_checkpoints(args.runs_root)
        seed_everything(protocol["seed"], protocol["cpu_threads"])
        device = resolve_device(args.device)
        destination = args.output_dir / _sha256(args.protocol)[:12]
        if args.stage == "inspect":
            for checkpoint in selected.values():
                load_model(checkpoint, device, digest)
            inventory = {"selected": {category: asdict(checkpoint) for category, checkpoint in selected.items()},
                         "excluded": excluded, "protocol_sha256": _sha256(args.protocol), "inference_executed": False, "test_executed": False}
            _write_once(destination / "checkpoint_inventory.json", _json_bytes(inventory))
            print(json.dumps(inventory, indent=2))
        else:
            reports = []
            for category, checkpoint in selected.items():
                output = destination / category
                if args.stage == "calibrate":
                    calibrate_category(checkpoint, protocol_path=args.protocol, root=args.root, manifest=args.manifest, output=output, device=device)
                else:
                    reports.append(evaluate_category(checkpoint, protocol_path=args.protocol, approved_sha256=args.approved_protocol_sha256,
                                                     root=args.root, manifest=args.manifest, output=output, device=device))
            if reports:
                rows = [{"category": report["category"], "image_auroc": report["metrics"]["image"]["auroc"],
                         "image_ap": report["metrics"]["image"]["ap"], "image_f1": report["metrics"]["image_decision"]["f1"],
                         "pixel_auroc": report["metrics"]["pixel"]["auroc"],
                         "pixel_ap": report["metrics"]["pixel"]["ap"], "dice_micro": report["metrics"]["segmentation_micro"]["dice"],
                         "iou_micro": report["metrics"]["segmentation_micro"]["iou"]} for report in reports]
                _write_csv(destination / "category_metrics.csv", rows)
                macro = {}
                for key in rows[0]:
                    if key != "category":
                        values = [row[key] for row in rows if row[key] is not None]
                        macro[key] = {"mean": float(np.mean(values)) if values else None, "categories": len(values)}
                _write_once(destination / "macro_metrics.json", _json_bytes(macro))
            print(json.dumps({"stage": args.stage, "output": str(destination), "categories": list(selected)}))
    except (OSError, ValueError, KeyError, RuntimeError, ImportError) as exc:
        print(f"Evaluation impossible : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
