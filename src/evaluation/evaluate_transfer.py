"""Evaluation image reelle future : checkpoints full et validation explicite SHA."""

from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import torch
from torch.utils.data import DataLoader
import yaml

from resilientinspect.data.audit import _sha256
from resilientinspect.data.dataset import MVTecDataset
from resilientinspect.data import synthetic
from resilientinspect.models import transfer
from resilientinspect.training import train_transfer
from resilientinspect.training.train_ae import resolve_device, seed_everything
from . import evaluate_ae as shared

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = PROJECT / "configs/evaluate_transfer.yaml"


def load_protocol(path: Path) -> dict[str, Any]:
    protocol = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    expected = {"schema_version": 1, "protocol_id": "transfer_binary_imagenet256_valnormal95_v1",
                "categories": list(shared.CATEGORIES), "image_size": [256, 256],
                "normalization": {"mean": list(synthetic.IMAGENET_MEAN), "std": list(synthetic.IMAGENET_STD)},
                "score": "sigmoid_anomaly_logit", "calibration_split": "val_synthetic_normal",
                "threshold_quantile": 0.95, "quantile_method": "higher", "decision": "strictly_greater",
                "pixel_metrics": False, "batch_size": 4, "cpu_threads": 2}
    if protocol != expected:
        raise ValueError("Protocole de classification de transfert inconnu ou modifie.")
    return protocol


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def inspect_run(run_dir: Path, manifest: Path) -> dict[str, Any]:
    """Controle de provenance uniquement ; aucune construction de Dataset."""
    path = run_dir / "best.pt"
    summary = _json(run_dir / "summary.json")
    saved = torch.load(path, map_location="cpu", weights_only=True)
    if (saved.get("scope") != "full" or summary.get("scope") != "full"
            or summary.get("status") != "completed" or summary.get("test_used") is not False
            or summary.get("selection_split") != "val_synthetic"
            or summary.get("checkpoint_sha256") != _sha256(path)
            or saved.get("epoch") != summary.get("best_epoch")
            or saved.get("val_loss") != summary.get("best_val_loss")):
        raise ValueError("Evaluation reelle exige un run full termine sans test, jamais un smoke.")
    effective_path = run_dir / "effective_config.yaml"
    effective = yaml.safe_load(effective_path.read_text(encoding="utf-8"))
    if (effective != saved.get("effective_config") or effective.get("max_batches_per_split", "missing") is not None
            or any(summary.get(key) != saved.get(key) for key in ("variant", "category", "seed", "manifest_sha256", "synthetic_plan_sha256"))):
        raise ValueError("Configuration effective ou resume incompatible avec le checkpoint.")
    if (effective.get("image_size") != [256, 256]
            or effective.get("normalization") != {"mean": list(synthetic.IMAGENET_MEAN), "std": list(synthetic.IMAGENET_STD)}):
        raise ValueError("Normalisation ImageNet et geometrie 256x256 fixes requises.")
    digest = shared.manifest_digest(manifest)
    if saved.get("manifest_sha256") != digest:
        raise ValueError("Manifeste different de celui du modele.")
    plan_path = run_dir / "synthetic_plan.json"
    plan = _json(plan_path)
    if (_sha256(plan_path) != saved.get("synthetic_plan_sha256")
            or plan != synthetic.prepare_synthetic_plan(manifest, plan["config"], saved["seed"])):
        raise ValueError("Plan synthetique perime ou incompatible.")
    calibration_path = run_dir / "calibration.json"
    calibration = _json(calibration_path)
    if (calibration_path.with_suffix(".sha256").read_text(encoding="ascii").strip() != _sha256(calibration_path)
            or summary.get("calibration_sha256") != _sha256(calibration_path)):
        raise ValueError("Calibration modifiee.")
    expected = {"variant": saved["variant"], "category": saved["category"], "seed": saved["seed"], "scope": "full",
                "calibration_split": "val_synthetic", "normal_only": True, "method": "normal_quantile",
                "quantile": 0.95, "quantile_method": "higher", "decision": "strictly_greater",
                "checkpoint_sha256": _sha256(path), "manifest_sha256": digest,
                "synthetic_plan_sha256": _sha256(plan_path), "effective_config_sha256": _sha256(effective_path),
                "train_code_sha256": _sha256(Path(train_transfer.__file__)),
                "model_code_sha256": _sha256(Path(transfer.__file__)),
                "synthetic_code_sha256": _sha256(Path(synthetic.__file__)),
                "shared_evaluation_code_sha256": _sha256(Path(shared.__file__)),
                "dataset_code_sha256": _sha256(PROJECT / "src/data/dataset.py"),
                "normalization": effective["normalization"], "image_size": [256, 256]}
    if any(calibration.get(key) != value for key, value in expected.items()):
        raise ValueError("Calibration perimee ou incompatible avec le protocole de transfert.")
    environment = _json(run_dir / "environment.json")
    current = {"python": sys.version.split()[0], "torch": str(torch.__version__), "numpy": np.__version__,
               "torchvision": version("torchvision"), "scikit_learn": version("scikit-learn")}
    if calibration.get("environment") != environment or any(environment.get(key) != value for key, value in current.items()):
        raise ValueError("Environnement different de la calibration ; revue et recalibration requises.")
    scores = calibration.get("validation_scores", [])
    recipes = {row["sample_id"]: row for row in plan["recipes"]
               if row["split"] == "val" and row["category"] == saved["category"]}
    if len(scores) != len(recipes) or {row["sample_id"] for row in scores} != set(recipes):
        raise ValueError("La calibration doit couvrir la validation synthetique complete.")
    for row in scores:
        recipe = recipes[row["sample_id"]]
        if (row["split"] != "val" or row["image_path"] != recipe["image_path"] or row["label"] != recipe["label"]
                or type(row["score"]) not in (int, float) or not np.isfinite(row["score"]) or not 0 <= row["score"] <= 1):
            raise ValueError("Scores de calibration invalides.")
    normals = [row["score"] for row in scores if row["label"] == 0]
    threshold = calibration.get("image_threshold")
    if (not normals or type(threshold) not in (int, float) or not np.isfinite(threshold)
            or threshold != float(np.quantile(normals, 0.95, method="higher"))):
        raise ValueError("Seuil incompatible avec les seuls normaux de validation synthetique.")
    # Validation stricte de l'architecture et des poids sans aucun appel ImageNet.
    transfer.load_transfer_checkpoint(path)
    return {"variant": saved["variant"], "category": saved["category"], "seed": saved["seed"],
            "checkpoint_sha256": _sha256(path), "manifest_sha256": digest,
            "calibration_sha256": _sha256(calibration_path), "synthetic_plan_sha256": _sha256(plan_path),
            "image_threshold": threshold, "inference_executed": False, "test_executed": False}


def _safe_output(output: Path, root: Path, manifest: Path, run_dir: Path) -> None:
    shared._safe_output(output, root, manifest, run_dir)
    if output.resolve().is_relative_to(PROJECT) and not output.resolve().is_relative_to(PROJECT / "reports/transfer"):
        raise ValueError("Sorties de transfert limitees a reports/transfer dans le depot ; B0/A1 proteges.")


def evaluate_run(run_dir: Path, *, protocol_path: Path, approved_sha256: str | None,
                 manifest: Path, root: Path, output: Path, device: torch.device) -> dict[str, Any]:
    shared.require_approval(protocol_path, approved_sha256)  # Avant checkpoint, manifeste et Dataset test.
    protocol = load_protocol(protocol_path)
    _safe_output(output, root, manifest, run_dir)
    metadata = inspect_run(run_dir, manifest)
    seed_everything(metadata["seed"], protocol["cpu_threads"])
    model = transfer.load_transfer_checkpoint(run_dir / "best.pt", device)
    dataset = MVTecDataset(manifest, root, split="test", categories=[metadata["category"]], verify_hashes=True)
    # Classification image : aucun masque officiel n'est necessaire ou ouvert.
    dataset.rows = [{**row, "mask_path": "", "mask_sha256": ""} for row in sorted(dataset.rows, key=lambda row: row["image_path"])]
    loader = DataLoader(dataset, batch_size=protocol["batch_size"], shuffle=False, num_workers=0)
    rows = []
    with torch.inference_mode():
        for batch in loader:
            scores = model(synthetic.normalize_image(batch["image"].to(device))).sigmoid().cpu().tolist()
            for index, score in enumerate(scores):
                rows.append({"image_path": batch["image_path"][index], "category": metadata["category"], "split": "test",
                             "label": int(batch["label"][index]), "defect_type": batch["defect_type"][index], "score": score,
                             "image_threshold": metadata["image_threshold"], "predicted_label": int(score > metadata["image_threshold"])})
    metrics = train_transfer.classification_metrics(np.array([row["label"] for row in rows]),
                                                   np.array([row["score"] for row in rows]), metadata["image_threshold"])
    report = {**metadata, "split": "test_real_mvtec", "inference_executed": True, "test_executed": True,
              "protocol": protocol, "protocol_sha256": _sha256(protocol_path), "metrics": metrics, "images": len(rows),
              "evaluation_code_sha256": _sha256(Path(__file__)), "environment": shared._environment(device),
              "pixel_metrics_computed": False, "gradcam_is_segmentation": False}
    shared._write_csv(output / "predictions.csv", rows)
    shared._write_once(output / "metrics.json", shared._json_bytes(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("inspect", "evaluate"), default="inspect")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/manifest.csv"))
    parser.add_argument("--root", type=Path, default=Path("data/raw/mvtec_ad"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/transfer/evaluation"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--approved-protocol-sha256")
    args = parser.parse_args(argv)
    try:
        if args.stage == "evaluate":
            shared.require_approval(args.protocol, args.approved_protocol_sha256)
        load_protocol(args.protocol)
        _safe_output(args.output_dir, args.root, args.manifest, args.run_dir)
        if args.stage == "inspect":
            print(json.dumps(inspect_run(args.run_dir, args.manifest)))
        else:
            metadata = inspect_run(args.run_dir, args.manifest)
            output = args.output_dir / metadata["variant"] / metadata["category"] / f"seed{metadata['seed']}" / metadata["checkpoint_sha256"][:12] / _sha256(args.protocol)[:12]
            report = evaluate_run(args.run_dir, protocol_path=args.protocol, approved_sha256=args.approved_protocol_sha256,
                                  manifest=args.manifest, root=args.root, output=output, device=resolve_device(args.device))
            print(json.dumps({"output": str(output), "metrics": report["metrics"]}))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError) as exc:
        print(f"Evaluation transfert impossible : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
