"""A1 : inspection, calibration val normale, puis test apres revue explicite SHA."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import io
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import torch

from resilientinspect.data.audit import _sha256
from resilientinspect.training.train_ae import resolve_device, seed_everything
from . import evaluate_ae as shared
from .a1_checkpoints import discover_checkpoints, inspection_metadata, load_model

PROJECT = Path(__file__).resolve().parents[2]
B0_PROTOCOL = PROJECT / "configs/evaluate_ae_b0.yaml"
CATEGORIES = shared.CATEGORIES
Checkpoint = shared.Checkpoint


def load_protocol(path: Path) -> dict[str, Any]:
    """Meme YAML que B0 ; aucun reglage A1 des quantiles ou de la carte."""
    protocol = shared.load_protocol(path)
    if (protocol != shared.load_protocol(B0_PROTOCOL)
            or protocol["image_top_fraction"] != 0.01
            or protocol["image_threshold_quantile"] != 0.95
            or protocol["pixel_threshold_quantile"] != 0.995):
        raise ValueError("A1 exige strictement le protocole B0 fige, sans ajustement.")
    return protocol


def _safe_output(output: Path, root: Path, manifest: Path, runs_root: Path) -> None:
    shared._safe_output(output, root, manifest, runs_root)
    resolved = output.resolve()
    # Les repertoires temporaires hors depot permettent les tests synthetiques.
    if resolved.is_relative_to(PROJECT) and not resolved.is_relative_to(PROJECT / "reports/evaluation/a1"):
        raise ValueError("Sorties A1 autorisees uniquement sous reports/evaluation/a1 dans le depot.")
    for name in ("figures", ".matplotlib"):
        if not (output / name).resolve().is_relative_to(resolved):
            raise ValueError("Sous-dossier de sortie A1 hors du dossier autorise (lien/jonction).")


def binding(protocol_path: Path, checkpoint: Checkpoint, digest: str) -> dict[str, str]:
    source = PROJECT / "src"
    return {**shared.binding(protocol_path, checkpoint, digest), "variant": "A1",
            "evaluation_code_sha256": _sha256(Path(__file__)),
            "shared_evaluation_code_sha256": _sha256(Path(shared.__file__)),
            "checkpoint_validation_code_sha256": _sha256(Path(__file__).with_name("a1_checkpoints.py")),
            "loader_code_sha256": _sha256(source / "training/a1_config.py"),
            "model_code_sha256": _sha256(source / "models/autoencoder_improved.py"),
            "preparation_code_sha256": _sha256(source / "data/prepare.py")}


def calibrate_category(checkpoint: Checkpoint, *, protocol_path: Path, root: Path, manifest: Path,
                       output: Path, device: torch.device) -> dict[str, Any]:
    """Recalcule les deux seuils a partir de val/good pour ce checkpoint A1."""
    _safe_output(output, root, manifest, Path(checkpoint.path).parents[2])
    protocol = load_protocol(protocol_path)
    seed_everything(protocol["seed"], protocol["cpu_threads"])
    digest = shared.manifest_digest(manifest)
    model = load_model(checkpoint, device, digest)
    # infer_records verifie tous les labels/provenances val AVANT d'ouvrir une image.
    records = shared.infer_records(model, manifest, root, checkpoint.category, "val", protocol, device)
    result = {"category": checkpoint.category, "calibration_split": "val", "normal_only": True,
              "checkpoint": asdict(checkpoint), "protocol": protocol, "environment": shared._environment(device),
              **binding(protocol_path, checkpoint, digest), **shared.calibrate_records(records, protocol)}
    shared._write_once(output / "calibration.json", shared._json_bytes(result))
    shared._write_once(output / "calibration.sha256", (_sha256(output / "calibration.json") + "\n").encode("ascii"))
    shared._write_csv(output / "calibration_scores.csv", result["validation_scores"])
    return result


def _load_calibration(output: Path, checkpoint: Checkpoint, protocol: dict[str, Any],
                      expected: dict[str, str], device: torch.device) -> dict[str, Any]:
    path = output / "calibration.json"
    if path.with_suffix(".sha256").read_text(encoding="ascii").strip() != _sha256(path):
        raise ValueError("Calibration modifiee : empreinte invalide ; aucun test execute.")
    calibration = json.loads(path.read_text(encoding="utf-8"))
    if (any(calibration.get(key) != value for key, value in expected.items())
            or calibration.get("category") != checkpoint.category
            or calibration.get("checkpoint") != asdict(checkpoint)
            or calibration.get("calibration_split") != "val" or calibration.get("normal_only") is not True
            or calibration.get("protocol") != protocol
            or calibration.get("environment") != shared._environment(device)):
        raise ValueError("Calibration A1 perimee ou incompatible ; aucun test execute.")
    shared._thresholds(calibration)
    for key in ("validation_images", "validation_pixels"):
        if type(calibration.get(key)) is not int or calibration[key] < 1:
            raise ValueError("Calibration sans validation normale complete.")
    scores = calibration.get("validation_scores", [])
    if len(scores) != calibration["validation_images"]:
        raise ValueError("Scores de calibration incomplets.")
    return calibration


def _figures(records: list[dict[str, Any]], protocol: dict[str, Any], checkpoint: Checkpoint,
             calibration: dict[str, Any], output: Path) -> list[str]:
    """Selection lexicale B0 ; rendu A1 avec masque predit au seuil val fige."""
    os.environ.setdefault("MPLCONFIGDIR", str(output / ".matplotlib"))
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    _, threshold = shared._thresholds(calibration)
    counts: dict[str, int] = {}
    filenames = []
    for row in sorted(records, key=lambda row: (row["defect_type"], row["image_path"])):
        defect = row["defect_type"]
        if counts.get(defect, 0) >= protocol["figures_per_defect"]:
            continue
        counts[defect] = counts.get(defect, 0) + 1
        valid = row["valid"].astype(bool)
        predicted = (row["error"] > threshold) & valid
        arrays = (row["image"].transpose(1, 2, 0), row["reconstruction"].transpose(1, 2, 0),
                  np.ma.array(row["error"], mask=~valid), np.ma.array(row["mask"], mask=~valid),
                  np.ma.array(predicted, mask=~valid))
        titles = ("Entree RGB 256x256", "Reconstruction", "Erreur L1 RGB moyenne", "Masque GT nearest", "Prediction (seuil val)")
        figure = Figure(figsize=(15, 3.4), layout="constrained")
        FigureCanvasAgg(figure)
        for index, (axis, array, title) in enumerate(zip(figure.subplots(1, 5), arrays, titles)):
            artist = axis.imshow(array, interpolation="nearest", cmap="magma" if index == 2 else "gray", vmin=0, vmax=1)
            axis.set_title(title, fontsize=10)
            axis.axis("off")
            if index == 2:
                figure.colorbar(artist, ax=axis, fraction=0.04)
        figure.suptitle(f"{checkpoint.category} | test/{defect} | {Path(row['image_path']).name} | A1 {checkpoint.run_id[:8]}")
        filename = f"{defect}_{Path(row['image_path']).stem}.png"
        stream = io.BytesIO()
        figure.savefig(stream, format="png", dpi=120)
        shared._write_once(output / "figures" / filename, stream.getvalue())
        figure.clear()
        filenames.append(filename)
    return filenames


def evaluate_category(checkpoint: Checkpoint, *, protocol_path: Path, approved_sha256: str | None,
                      root: Path, manifest: Path, output: Path, device: torch.device) -> dict[str, Any]:
    shared.require_approval(protocol_path, approved_sha256)  # Avant manifeste, modele et Dataset test.
    _safe_output(output, root, manifest, Path(checkpoint.path).parents[2])
    protocol = load_protocol(protocol_path)
    seed_everything(protocol["seed"], protocol["cpu_threads"])
    digest = shared.manifest_digest(manifest)
    expected = binding(protocol_path, checkpoint, digest)
    calibration = _load_calibration(output, checkpoint, protocol, expected, device)
    model = load_model(checkpoint, device, digest)
    records = shared.infer_records(model, manifest, root, checkpoint.category, "test", protocol, device)
    metrics, rows = shared.summarize_records(records, calibration, protocol)
    report = {"category": checkpoint.category, "split": "test", "checkpoint": asdict(checkpoint), **expected,
              "protocol": protocol, "calibration_sha256": _sha256(output / "calibration.json"),
              "image_threshold": calibration["image_threshold"], "pixel_threshold": calibration["pixel_threshold"],
              "metrics": metrics, "resolution": [256, 256], "padding_excluded": True,
              "environment": shared._environment(device)}
    report["figures"] = _figures(records, protocol, checkpoint, calibration, output)
    shared._write_csv(output / "predictions.csv", rows)
    shared._write_once(output / "predictions.json", shared._json_bytes({"variant": "A1", "predictions": rows}))
    shared._write_once(output / "metrics.json", shared._json_bytes(report))
    return report


def _write_summary(reports: list[dict[str, Any]], destination: Path) -> None:
    rows = [{"category": report["category"], "image_auroc": report["metrics"]["image"]["auroc"],
             "image_ap": report["metrics"]["image"]["ap"], "image_f1": report["metrics"]["image_decision"]["f1"],
             "pixel_auroc": report["metrics"]["pixel"]["auroc"], "pixel_ap": report["metrics"]["pixel"]["ap"],
             "dice_micro": report["metrics"]["segmentation_micro"]["dice"],
             "iou_micro": report["metrics"]["segmentation_micro"]["iou"]} for report in reports]
    shared._write_csv(destination / "category_metrics.csv", rows)
    macro = {}
    for key in rows[0]:
        if key != "category":
            values = [row[key] for row in rows if row[key] is not None]
            macro[key] = {"mean": float(np.mean(values)) if values else None, "categories": len(values)}
    shared._write_once(destination / "macro_metrics.json", shared._json_bytes(macro))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("inspect", "calibrate", "evaluate"), default="inspect")
    parser.add_argument("--protocol", type=Path, default=Path("configs/evaluate_ae_b0.yaml"))
    parser.add_argument("--runs-root", type=Path, default=Path("artifacts/a1_runs"))
    parser.add_argument("--root", type=Path, default=Path("data/raw/mvtec_ad"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/manifest.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/evaluation/a1"))
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--approved-protocol-sha256")
    args = parser.parse_args(argv)
    try:
        if args.stage == "evaluate":
            shared.require_approval(args.protocol, args.approved_protocol_sha256)
        protocol = load_protocol(args.protocol)
        _safe_output(args.output_dir, args.root, args.manifest, args.runs_root)
        digest = shared.manifest_digest(args.manifest)
        selected, excluded = discover_checkpoints(args.runs_root)
        seed_everything(protocol["seed"], protocol["cpu_threads"])
        device = resolve_device(args.device)
        destination = args.output_dir / _sha256(args.protocol)[:12]
        _safe_output(destination, args.root, args.manifest, args.runs_root)
        if args.stage == "inspect":
            metadata = {}
            for category, checkpoint in selected.items():
                model = load_model(checkpoint, device, digest)
                metadata[category] = {**inspection_metadata(checkpoint),
                                      "parameters": sum(parameter.numel() for parameter in model.parameters())}
            inventory = {"variant": "A1", "selected": {category: asdict(cp) for category, cp in selected.items()},
                         "metadata": metadata, "excluded": excluded, "protocol": protocol,
                         "protocol_sha256": _sha256(args.protocol), "manifest_sha256": digest,
                         "environment": shared._environment(device), "inference_executed": False,
                         "calibration_executed": False, "test_executed": False}
            shared._write_once(destination / "checkpoint_inventory.json", shared._json_bytes(inventory))
            print(json.dumps(inventory, indent=2, ensure_ascii=False))
        else:
            # Tous les checkpoints sont controles avant le premier acces aux images.
            for checkpoint in selected.values():
                load_model(checkpoint, device, digest)
            if args.stage == "evaluate":
                # Refuser une calibration absente/perimee dans une categorie avant tout test.
                for category, checkpoint in selected.items():
                    _load_calibration(destination / category, checkpoint, protocol,
                                      binding(args.protocol, checkpoint, digest), device)
            reports = []
            for category, checkpoint in selected.items():
                kwargs = dict(protocol_path=args.protocol, root=args.root, manifest=args.manifest,
                              output=destination / category, device=device)
                if args.stage == "calibrate":
                    calibrate_category(checkpoint, **kwargs)
                else:
                    reports.append(evaluate_category(checkpoint, approved_sha256=args.approved_protocol_sha256, **kwargs))
            if reports:
                _write_summary(reports, destination)
            print(json.dumps({"stage": args.stage, "variant": "A1", "output": str(destination), "categories": list(selected)}))
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError) as exc:
        print(f"Evaluation A1 impossible : {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
