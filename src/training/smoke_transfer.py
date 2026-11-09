"""Trois smoke CPU sur images fabriquees en temporaire ; aucun dataset officiel."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import tempfile
import time
from typing import Any

import numpy as np
from PIL import Image
import torch

from resilientinspect.data.audit import _sha256
from resilientinspect.data.prepare import write_manifests
from resilientinspect.data import synthetic
from resilientinspect.evaluation.evaluate_ae import _json_bytes, _write_once
from resilientinspect.evaluation.gradcam import gradcam
from resilientinspect.models.transfer import GRADCAM_TARGET, load_transfer_checkpoint
from .train_transfer import run_training

PROJECT = Path(__file__).resolve().parents[2]


def _make_fixture(directory: Path) -> tuple[Path, Path]:
    """Dix sources artificielles uniques par categorie, huit train et deux val."""
    root = directory / "raw"
    rows = []
    yy, xx = np.indices((32, 64))
    for category_index, category in enumerate(("bottle", "hazelnut", "leather")):
        for index in range(10):
            rgb = np.stack(((xx * 3 + index * 13 + category_index * 17) % 256,
                            (yy * 5 + index * 7 + category_index * 43) % 256,
                            ((xx + yy) * 2 + index * 11 + category_index * 29) % 256), axis=-1).astype(np.uint8)
            relative = f"{category}/train/good/{index:03d}.png"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgb).save(path)
            rows.append({"image_path": relative, "category": category, "split": "train" if index < 8 else "val",
                         "label": "0", "defect_type": "good", "mask_path": "", "source_split": "train",
                         "sha256": _sha256(path), "mask_sha256": ""})
    manifests = directory / "manifests"
    write_manifests(rows, {"dataset_root": str(root)}, manifests)
    return root, manifests / "manifest.csv"


def _cam_figure(model: torch.nn.Module, dataset: synthetic.SyntheticAnomalyDataset, path: Path, title: str) -> dict[str, Any]:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    samples = [dataset[0], dataset[1]]  # Meme source, normale puis anomalie synthetique.
    images = torch.stack([sample["image"] for sample in samples])
    before = {name: value.clone() for name, value in model.state_dict().items()}
    cams = gradcam(model, images)
    assert all(torch.equal(value, model.state_dict()[name]) for name, value in before.items())
    assert all(parameter.grad is None for parameter in model.parameters())
    figure = Figure(figsize=(12, 6.8), layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots(2, 4)
    for row, sample in enumerate(samples):
        raw = sample["raw_image"].permute(1, 2, 0).numpy()
        valid = sample["valid_mask"][0].numpy().astype(bool)
        cam = np.ma.array(cams[row, 0].numpy(), mask=~valid)
        axes[row, 0].imshow(raw)
        axes[row, 1].imshow(np.ma.array(sample["synthetic_mask"][0].numpy(), mask=~valid), vmin=0, vmax=1, cmap="gray", interpolation="nearest")
        axes[row, 2].imshow(cam, vmin=0, vmax=1, cmap="magma", interpolation="nearest")
        axes[row, 3].imshow(raw)
        axes[row, 3].imshow(cam, vmin=0, vmax=1, cmap="magma", alpha=0.45, interpolation="nearest")
        for axis, label in zip(axes[row], (f"RGB | label={sample['label']}", "Support corruption synthetique", "Grad-CAM classe anomalie", "Attribution sur RGB")):
            axis.set_title(label, fontsize=9)
            axis.axis("off")
    figure.suptitle(title + "\nGrad-CAM : attribution, aucune segmentation")
    stream = io.BytesIO()
    figure.savefig(stream, format="png", dpi=120)
    _write_once(path, stream.getvalue())
    figure.clear()
    return {"target_layer": GRADCAM_TARGET, "shape": list(cams.shape), "finite": bool(torch.isfinite(cams).all()),
            "weights_and_buffers_preserved": True, "path": str(path), "sample_ids": [sample["sample_id"] for sample in samples]}


def run_smokes(*, output_dir: Path, imagenet_weights: Path, report_path: Path) -> dict[str, Any]:
    if report_path.resolve().is_relative_to(PROJECT) and not report_path.resolve().is_relative_to(PROJECT / "reports/transfer"):
        raise ValueError("Rapport smoke limite a reports/transfer dans le depot.")
    if report_path.exists():
        raise FileExistsError("Rapport smoke existant ; choisir un nouveau chemin.")
    results = []
    with tempfile.TemporaryDirectory(prefix="resilientinspect_transfer_smoke_") as temporary:
        directory = Path(temporary)
        root, manifest = _make_fixture(directory)
        config = synthetic.load_synthetic_config(PROJECT / "configs/synthetic_transfer.yaml")
        plan = synthetic.prepare_synthetic_plan(manifest, config, 42)
        plan_path = directory / "plan.json"
        synthetic.write_synthetic_plan(plan, plan_path)
        original_open = Image.open
        opened: list[str] = []

        def guarded_open(path: Any, *args: Any, **kwargs: Any) -> Any:
            relative = Path(path).resolve().relative_to(root.resolve()).as_posix()
            if "/train/good/" not in relative or "/test/" in relative or "/ground_truth/" in relative:
                raise AssertionError("Smoke limite aux images artificielles train/good temporaires.")
            opened.append(relative)
            return original_open(path, *args, **kwargs)

        Image.open = guarded_open
        try:
            for variant in ("T0", "T1", "T2"):
                started = time.perf_counter()
                summary = run_training(PROJECT / f"configs/train_{variant.lower()}.yaml", root=root, manifest=manifest,
                                       output_dir=output_dir, category="bottle", seed=42, device="cpu", smoke=True,
                                       synthetic_plan=plan_path, imagenet_weights=imagenet_weights if variant != "T0" else None)
                run_dir = Path(summary["run_dir"])
                model = load_transfer_checkpoint(run_dir / "best.pt")
                dataset = synthetic.SyntheticAnomalyDataset(manifest, root, category="bottle", split="val", config=config, seed=42, plan=plan)
                cam = _cam_figure(model, dataset, run_dir / "gradcam_synthetic.png",
                                  f"{variant} | bottle | val_synthetic | smoke | seed42 | {summary['run_id'][:8]}")
                results.append({"variant": variant, "run_id": summary["run_id"], "run_dir": str(run_dir),
                                "scope": summary["scope"], "epochs_completed": summary["epochs_completed"],
                                "history": summary["history"], "validation_metrics": summary["validation_metrics"],
                                "trainable_parameters": summary["trainable_parameters"]["trainable_parameters"],
                                "checkpoint_sha256": summary["checkpoint_sha256"],
                                "synthetic_plan_sha256": summary["synthetic_plan_sha256"],
                                "weight_provenance": summary["weight_provenance"], "gradcam": cam,
                                "local_smoke_seconds": time.perf_counter() - started})
        finally:
            Image.open = original_open
    assert len({row["synthetic_plan_sha256"] for row in results}) == 1
    assert all(row["scope"] == "smoke" and row["epochs_completed"] == 1 for row in results)
    report = {"scope": "synthetic_cpu_smoke_only", "official_training_executed": False, "official_test_executed": False,
              "official_images_opened": False, "seed": 42, "batch_size": 2, "max_batches_per_split": 2,
              "temporary_sources_only": True, "opened_source_paths": sorted(set(opened)), "results": results,
              "note": "Les metriques sont des controles sur images artificielles, aucune performance industrielle mesuree."}
    _write_once(report_path, _json_bytes(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--imagenet-weights", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/transfer_runs"))
    parser.add_argument("--report", type=Path, default=Path("reports/transfer/smoke_verification.json"))
    args = parser.parse_args(argv)
    result = run_smokes(output_dir=args.output_dir, imagenet_weights=args.imagenet_weights, report_path=args.report)
    print(json.dumps({"report": str(args.report), "variants": [row["variant"] for row in result["results"]], "scope": result["scope"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
