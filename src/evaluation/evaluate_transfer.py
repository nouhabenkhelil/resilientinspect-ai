"""Evaluation image reelle future : checkpoints full et validation explicite SHA."""

from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import platform
import re
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
# Fixe avant toute mesure CPU. Voir reports/experiments/transfer_portability.md.
PARITY_POLICY = {"policy_id": "transfer_fp32_cpu_v1", "atol": 1e-5, "rtol": 1e-4,
                 "decision_changes": "both_scores_within_atol_of_original_threshold"}


def _environment() -> dict[str, Any]:
    return {**shared._environment(torch.device("cpu")), "torchvision": version("torchvision"),
            "pillow": version("Pillow"), "platform": platform.platform(), "machine": platform.machine(),
            "cpu_threads": torch.get_num_threads(),
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
            "float32_matmul_precision": torch.get_float32_matmul_precision(), "mixed_precision": False}


def _environment_changes(training: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    changes = {}
    for key in ("python", "torch", "numpy", "torchvision", "scikit_learn"):
        original, local = training.get(key), current[key]
        if not isinstance(original, str) or re.fullmatch(r"\d+\.\d+\.\d+(?:[+.-][\w.]+)?", original) is None:
            raise ValueError(f"Version d'entrainement invalide : {key}.")
        if original.split(".")[0] != local.split(".")[0]:
            raise ValueError(f"Incompatibilite majeure d'environnement : {key} {original} -> {local}.")
        if original != local:
            changes[key] = {"training": original, "evaluation": local}
    return changes


def _verify_sources(run_dir: Path, summary: dict[str, Any], saved: dict[str, Any]) -> dict[str, str]:
    """Resout les chemins Kaggle par les noms connus, sans executer de code archive."""
    provenance = _json(run_dir / "provenance.json")
    paths = [PROJECT / f"configs/train_{saved['variant'].lower()}.yaml",
             PROJECT / "configs/synthetic_transfer.yaml", Path(train_transfer.__file__),
             Path(transfer.__file__), Path(synthetic.__file__), PROJECT / "src/data/dataset.py",
             PROJECT / "src/data/prepare.py", PROJECT / "src/data/audit.py",
             PROJECT / "src/training/train_ae.py", Path(shared.__file__), PROJECT / "pyproject.toml"]
    recorded = provenance.get("source_sha256", {})
    expected_names = {path.name for path in paths}
    hashes = {Path(name.replace("\\", "/")).name: digest for name, digest in recorded.items()}
    if len(hashes) != len(recorded) or set(hashes) != expected_names or recorded != summary.get("source_sha256"):
        raise ValueError("Inventaire SHA256 des sources d'entrainement incoherent.")
    if any(provenance.get(key) != saved.get(key) for key in ("manifest_sha256", "synthetic_plan_sha256", "weight_provenance")):
        raise ValueError("Provenance differente du checkpoint.")
    for path in paths:
        if _sha256(path) != hashes[path.name] or _sha256(run_dir / "source" / path.name) != hashes[path.name]:
            raise ValueError(f"Source ou configuration d'entrainement modifiee : {path.name}.")
    return hashes


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
    if summary.get("checkpoint_sha256") != _sha256(path):
        raise ValueError("Checkpoint modifie (SHA256).")
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
    if calibration.get("environment") != environment:
        raise ValueError("Environnement Kaggle different de la calibration archivee.")
    current = _environment()
    changes = _environment_changes(environment, current)
    source_hashes = _verify_sources(run_dir, summary, saved)
    scores = calibration.get("validation_scores", [])
    recipes = {row["sample_id"]: row for row in plan["recipes"]
               if row["split"] == "val" and row["category"] == saved["category"]}
    if (not recipes or len(scores) != len(recipes) or {row["sample_id"] for row in scores} != set(recipes)
            or calibration.get("validation_images") != len(scores)
            or calibration.get("validation_normal_images") != sum(row["label"] == 0 for row in scores)):
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
    model = transfer.load_transfer_checkpoint(path)
    for name, value in model.state_dict().items():
        original = saved["model_state_dict"][name]
        if original.dtype != value.dtype or original.shape != value.shape or not torch.equal(original, value):
            raise ValueError(f"Poids incompatibles avec le modele charge : {name}.")
    return {"variant": saved["variant"], "category": saved["category"], "seed": saved["seed"],
            "checkpoint_sha256": _sha256(path), "manifest_sha256": digest,
            "calibration_sha256": _sha256(calibration_path), "synthetic_plan_sha256": _sha256(plan_path),
            "effective_config_sha256": _sha256(effective_path), "source_sha256": source_hashes,
            "training_environment": environment, "evaluation_environment": current,
            "environment_changes": changes, "strict_weights_compatible": True,
            "image_threshold": threshold, "compatibility_validated": False,
            "inference_executed": False, "test_executed": False}


def validate_run(run_dir: Path, *, manifest: Path, root: Path,
                 protocol_path: Path = DEFAULT_PROTOCOL, device: torch.device = torch.device("cpu")) -> dict[str, Any]:
    """Parite sur toute la validation synthetique archivee ; seuil Kaggle conserve."""
    if device.type != "cpu":
        raise ValueError("La validation de portabilite exige le CPU.")
    protocol = load_protocol(protocol_path)
    metadata = inspect_run(run_dir, manifest)
    seed_everything(metadata["seed"], protocol["cpu_threads"])
    plan = _json(run_dir / "synthetic_plan.json")
    calibration = _json(run_dir / "calibration.json")
    dataset = synthetic.SyntheticAnomalyDataset(manifest, root, category=metadata["category"], split="val",
                                               config=plan["config"], seed=metadata["seed"], plan=plan)
    loader = DataLoader(dataset, batch_size=protocol["batch_size"], shuffle=False, num_workers=0)
    model = transfer.load_transfer_checkpoint(run_dir / "best.pt", device)
    # Reutilise exactement l'inference de validation utilisee a l'entrainement.
    predictions = train_transfer.run_epoch(model, loader, device)["predictions"]
    reference = {row["sample_id"]: row for row in calibration["validation_scores"]}
    if len(predictions) != len(reference) or {row["sample_id"] for row in predictions} != set(reference):
        raise ValueError("Couverture de parite synthetique incomplete ou dupliquee.")
    rows = []
    threshold = metadata["image_threshold"]
    for row in predictions:
        archived = reference[row["sample_id"]]
        if any(row[key] != archived[key] for key in ("split", "image_path", "label")) or row["split"] != "val":
            raise ValueError("Identite de validation synthetique divergente.")
        score, original = row["score"], archived["score"]
        error = abs(score - original)
        limit = PARITY_POLICY["atol"] + PARITY_POLICY["rtol"] * abs(original)
        changed = (score > threshold) != (original > threshold)
        boundary = max(abs(score - threshold), abs(original - threshold)) <= PARITY_POLICY["atol"]
        rows.append({**row, "archived_score": original, "absolute_error": error, "allowed_error": limit,
                     "score_within_tolerance": bool(np.isfinite(score) and 0 <= score <= 1 and error <= limit),
                     "archived_decision": int(original > threshold), "cpu_decision": int(score > threshold),
                     "decision_changed": changed, "decision_change_justified": bool(changed and boundary)})
    changed_rows = [row for row in rows if row["decision_changed"]]
    failures = sum(not row["score_within_tolerance"] for row in rows)
    unjustified = sum(not row["decision_change_justified"] for row in changed_rows)
    passed = failures == 0 and unjustified == 0
    return {**metadata, "evaluation_environment": _environment(), "compatibility_validated": passed,
            "inference_executed": True, "test_executed": False, "split": "val_synthetic",
            "status": "passed" if passed else "failed", "parity_policy": dict(PARITY_POLICY),
            "protocol_sha256": _sha256(protocol_path), "evaluation_code_sha256": _sha256(Path(__file__)),
            "validation_images": len(rows), "max_absolute_error": max(row["absolute_error"] for row in rows),
            "score_tolerance_failures": failures, "decision_changes": len(changed_rows),
            "unjustified_decision_changes": unjustified, "validation_scores": rows}


def _safe_output(output: Path, root: Path, manifest: Path, run_dir: Path) -> None:
    shared._safe_output(output, root, manifest, run_dir)
    if output.resolve().is_relative_to(PROJECT) and not output.resolve().is_relative_to(PROJECT / "reports/transfer"):
        raise ValueError("Sorties de transfert limitees a reports/transfer dans le depot ; B0/A1 proteges.")


def evaluate_run(run_dir: Path, *, protocol_path: Path, approved_sha256: str | None,
                 manifest: Path, root: Path, output: Path, device: torch.device) -> dict[str, Any]:
    shared.require_approval(protocol_path, approved_sha256)  # Avant checkpoint, manifeste et Dataset test.
    protocol = load_protocol(protocol_path)
    _safe_output(output, root, manifest, run_dir)
    metadata = validate_run(run_dir, manifest=manifest, root=root, protocol_path=protocol_path, device=device)
    if not metadata["compatibility_validated"]:
        raise ValueError("Parite numerique refusee ; aucun Dataset test construit.")
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
    parser.add_argument("--stage", choices=("inspect", "validate", "evaluate"), default="inspect")
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
            if args.stage == "validate":
                report = validate_run(args.run_dir, protocol_path=args.protocol, manifest=args.manifest,
                                      root=args.root, device=resolve_device(args.device))
                report_path = output / "compatibility.json"
                shared._write_once(report_path, shared._json_bytes(report))
                print(json.dumps({"output": str(report_path), "sha256": _sha256(report_path),
                                  "status": report["status"], "max_absolute_error": report["max_absolute_error"],
                                  "decision_changes": report["decision_changes"], "test_executed": False}))
                return 0 if report["compatibility_validated"] else 1
            report = evaluate_run(args.run_dir, protocol_path=args.protocol, approved_sha256=args.approved_protocol_sha256,
                                  manifest=args.manifest, root=args.root, output=output, device=resolve_device(args.device))
            print(json.dumps({"output": str(output), "metrics": report["metrics"]}))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError) as exc:
        print(f"Evaluation transfert impossible : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
