"""EDA visuelle descriptive a resolution native, sans modification du protocole.

Les figures incluent des images du dataset et restent locales (hors Git).
La verification semantique visuelle doit etre consignée separement apres inspection.
"""

from __future__ import annotations

from collections import defaultdict
import argparse
import csv
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .audit import _sha256
from .prepare import read_manifest, safe_data_path


GROUPS = ("train/good", "val/good", "test/good", "test/anomaly")
COLORS = ("#2463a6", "#22804b", "#666666", "#c23d38")
LUMA_BINS = np.linspace(0, 1, 65)
MEAN_BINS = np.linspace(0, 1, 33)
CONTRAST_BINS = np.linspace(0, 0.5, 33)
RUN_ID = "phase1-eda-v1"


def native_metrics(rgb: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Y' = (0.2126R + 0.7152G + 0.0722B)/255, contraste = std(Y'), ddof=0.

    Proxy de luminance sur RGB encode, sans linearisation gamma ni normalisation apprise.
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
        raise ValueError("Image RGB uint8 attendue.")
    luma = (0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]) / 255
    histogram = np.histogram(luma, bins=LUMA_BINS)[0]
    return float(luma.mean()), float(luma.std(ddof=0)), histogram


def _load_pair(root: Path, row: dict[str, str]) -> tuple[np.ndarray, np.ndarray | None]:
    image_path = safe_data_path(root, row["image_path"])
    if _sha256(image_path) != row["sha256"]:
        raise ValueError(f"Empreinte image modifiee : {row['image_path']}")
    with Image.open(image_path) as image:
        image.load()
        rgb = np.array(image.convert("RGB"))
    mask = None
    if row["mask_path"]:
        mask_path = safe_data_path(root, row["mask_path"])
        if _sha256(mask_path) != row["mask_sha256"]:
            raise ValueError(f"Empreinte masque modifiee : {row['mask_path']}")
        with Image.open(mask_path) as source:
            source.load()
            if source.mode not in ("1", "L"):
                raise ValueError(f"Masque non mono-canal : {row['mask_path']}")
            raw = np.array(source.convert("L"))
        values = set(np.unique(raw).tolist())
        if not values.issubset({0, 1}) and not values.issubset({0, 255}):
            raise ValueError(f"Masque non binaire : {row['mask_path']}")
        if raw.shape != rgb.shape[:2]:
            raise ValueError(f"Desalignement de dimensions : {row['image_path']} / {row['mask_path']}")
        mask = raw > 0
    return rgb, mask


def annotation_overlay(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Rouge translucide dans le masque, contour jaune ; contexte intact."""
    if rgb.shape[:2] != mask.shape or mask.dtype != bool:
        raise ValueError("Masque booleen de meme geometrie attendu.")
    padded = np.pad(mask, 1, constant_values=False)
    interior = mask & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    outline = mask & ~interior
    result = rgb.astype(np.float64)
    result[mask] = 0.65 * result[mask] + 0.35 * np.array([255, 0, 0])
    result[outline] = [255, 255, 0]
    return np.rint(result).astype(np.uint8)


def crop_bounds(mask: np.ndarray) -> tuple[int, int, int, int]:
    """Contexte autour du masque, en coordonnees natives ; affichage seulement."""
    height, width = mask.shape
    yy, xx = np.nonzero(mask)
    if not len(xx):
        return 0, 0, width, height
    margin = max(16, math.ceil(0.25 * max(int(xx.max() - xx.min() + 1), int(yy.max() - yy.min() + 1))))
    cx, cy = (int(xx.min()) + int(xx.max()) + 1) / 2, (int(yy.min()) + int(yy.max()) + 1) / 2
    half_w = max(64, (int(xx.max() - xx.min() + 1) + 2 * margin) / 2)
    half_h = max(64, (int(yy.max() - yy.min() + 1) + 2 * margin) / 2)
    return max(0, math.floor(cx - half_w)), max(0, math.floor(cy - half_h)), min(width, math.ceil(cx + half_w)), min(height, math.ceil(cy + half_h))


def gallery_selection(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trois normaux (train/val/test), puis tous les types de defauts, maximum 12."""
    selected = []
    for split in ("train", "val", "test"):
        candidates = sorted((row for row in records if row["split"] == split and row["label"] == "0"), key=lambda row: row["image_path"])
        if candidates:
            selected.append(candidates[0])
    by_defect: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(records, key=lambda row: row["image_path"]):
        if row["label"] == "1":
            by_defect[row["defect_type"]].append(row)
    selected.extend(group[0] for _, group in sorted(by_defect.items()))
    for _, group in sorted(by_defect.items()):
        if len(selected) < 12 and len(group) > 1:
            selected.append(group[-1])
    return selected


def _describe(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    array = np.asarray(values)
    return {"n": len(values), "min": float(array.min()), "median": float(np.median(array)),
            "mean": float(array.mean()), "max": float(array.max()), "std": float(array.std(ddof=0))}


def analyze_visual(root: Path, manifest_path: Path) -> dict[str, Any]:
    root, manifest_path = Path(root).resolve(), Path(manifest_path).resolve()
    rows = read_manifest(manifest_path)
    frozen = manifest_path.with_name("preparation.json")
    if frozen.exists():
        hashes = json.loads(frozen.read_text(encoding="utf-8"))["manifest_sha256"]
        if hashes.get(manifest_path.name) != _sha256(manifest_path):
            raise ValueError("Le manifeste ne correspond plus a son empreinte figee.")
    categories = {}
    for name in sorted({row["category"] for row in rows}):
        records, issues = [], []
        histograms = {group: np.zeros(64, dtype=np.int64) for group in GROUPS}
        for row in (row for row in rows if row["category"] == name):
            rgb, mask = _load_pair(root, row)
            mean, contrast, histogram = native_metrics(rgb)
            group = f"{row['split']}/good" if row["label"] == "0" else "test/anomaly"
            histograms[group] += histogram
            area = float(mask.mean()) if mask is not None else None
            touches_border = bool(mask is not None and (mask[0].any() or mask[-1].any() or mask[:, 0].any() or mask[:, -1].any()))
            if area == 0:
                issues.append({"code": "empty_native_mask", "path": row["mask_path"], "severity": "warning"})
            records.append({**row, "group": group, "width": rgb.shape[1], "height": rgb.shape[0],
                            "luminance_mean": mean, "contrast_rms": contrast,
                            "mask_area_fraction": area, "mask_touches_border": touches_border})
        groups = {group: {
            "luminance_mean": _describe([row["luminance_mean"] for row in records if row["group"] == group]),
            "contrast_rms": _describe([row["contrast_rms"] for row in records if row["group"] == group]),
        } for group in GROUPS}
        mask_areas = {defect: _describe([row["mask_area_fraction"] for row in records if row["label"] == "1" and row["defect_type"] == defect])
                      for defect in sorted({row["defect_type"] for row in records if row["label"] == "1"})}
        categories[name] = {"records": records, "groups": groups, "mask_areas": mask_areas,
                            "pixel_luminance_histogram": {group: hist.tolist() for group, hist in histograms.items()},
                            "gallery_paths": [row["image_path"] for row in gallery_selection(records)], "issues": issues}
    return {
        "schema_version": 1, "run_id": RUN_ID, "dataset_root": str(root),
        "manifest_path": str(manifest_path), "manifest_sha256": _sha256(manifest_path),
        "eda_code_sha256": _sha256(Path(__file__)), "categories": categories,
        "definitions": {
            "luminance": "Y'=(0.2126R+0.7152G+0.0722B)/255 on encoded RGB, no gamma linearization",
            "contrast": "population std(Y'), ddof=0, per image",
            "mask_area": "nonzero native mask pixels / native image pixels; anomalous test only",
            "pixel_histogram_bins": LUMA_BINS.tolist(), "mean_histogram_bins": MEAN_BINS.tolist(),
            "contrast_histogram_bins": CONTRAST_BINS.tolist(),
            "statistics_resolution": "native, no resize, no normalization fitted",
        },
        "protocol": {"split_changes": False, "scientific_parameter_changes": False,
                     "original_modifications": False, "training": False, "threshold_tuning": False},
        "visual_review": {"required": True, "record": "visual_review.json",
                          "note": "Dimension equality is not a semantic alignment certification; inspect generated sheets."},
    }


def _new_figure(rows: int, columns: int, size: tuple[float, float]):
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "resilientinspect-matplotlib"))
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    figure = Figure(figsize=size, layout="constrained")
    FigureCanvasAgg(figure)
    return figure, figure.subplots(rows, columns, squeeze=False)


def _gallery(root: Path, name: str, data: dict[str, Any], destination: Path) -> None:
    selected = gallery_selection(data["records"])
    figure, axes = _new_figure(len(selected), 3, (10, 2.45 * len(selected)))
    figure.suptitle(f"{name} | {RUN_ID} | originaux, masques et annotations", fontsize=13)
    for index, row in enumerate(selected):
        rgb, mask = _load_pair(root, row)
        mask = np.zeros(rgb.shape[:2], dtype=bool) if mask is None else mask
        for column, array in enumerate((rgb, mask, annotation_overlay(rgb, mask))):
            axes[index, column].imshow(array, cmap="gray" if column == 1 else None, vmin=0 if column == 1 else None,
                                      vmax=1 if column == 1 else None, interpolation="nearest")
            axes[index, column].axis("off")
        axes[index, 0].set_title(f"{row['split']} / {row['defect_type']} / {Path(row['image_path']).name}", fontsize=9)
        axes[index, 1].set_title("ground_truth" if row["mask_path"] else "normal : aucun masque", fontsize=9)
        axes[index, 2].set_title("rouge : annotation | jaune : contour", fontsize=9)
    figure.savefig(destination, dpi=120)
    figure.clear()


def _distributions(name: str, data: dict[str, Any], destination: Path) -> None:
    figure, axes = _new_figure(2, 2, (12, 8.8))
    figure.suptitle(f"{name} | {RUN_ID} | statistiques natives descriptives", fontsize=13)
    for group, color in zip(GROUPS, COLORS):
        records = [row for row in data["records"] if row["group"] == group]
        if not records:
            continue
        label = f"{group} (n={len(records)})"
        for field, bins, axis in (("luminance_mean", MEAN_BINS, axes[0, 0]), ("contrast_rms", CONTRAST_BINS, axes[0, 1])):
            counts = np.histogram([row[field] for row in records], bins=bins)[0]
            axis.stairs(counts / len(records), bins, label=label, color=color)
        counts = np.array(data["pixel_luminance_histogram"][group])
        axes[1, 0].stairs(counts / counts.sum(), LUMA_BINS, label=label, color=color)
    for axis, title, xlabel in (
        (axes[0, 0], "Luminance moyenne par image", "Moyenne Y' [0,1]"),
        (axes[0, 1], "Contraste RMS par image", "Ecart-type Y' [0,0.5]"),
        (axes[1, 0], "Histogramme des pixels de luminance", "Y' [0,1]"),
    ):
        axis.set(title=title, xlabel=xlabel, ylabel="Fraction par intervalle")
        axis.legend(fontsize=7)
        axis.grid(alpha=0.2)
    areas = {defect: [100 * row["mask_area_fraction"] for row in data["records"] if row["label"] == "1" and row["defect_type"] == defect]
             for defect in data["mask_areas"]}
    axis = axes[1, 1]
    if areas:
        axis.boxplot(list(areas.values()), tick_labels=[f"{defect}\nn={len(values)}" for defect, values in areas.items()], showfliers=True)
        if all(value > 0 for values in areas.values() for value in values):
            axis.set_yscale("log")
        axis.tick_params(axis="x", labelrotation=25, labelsize=8)
    axis.set(title="Surface des masques test par defaut", xlabel="Type de defaut", ylabel="% de l'image (axe log si toutes >0)")
    axis.grid(axis="y", alpha=0.2)
    figure.savefig(destination, dpi=150)
    figure.clear()


def _alignment_sheets(root: Path, name: str, data: dict[str, Any], output: Path) -> list[dict[str, Any]]:
    from matplotlib.font_manager import findfont

    font = ImageFont.truetype(findfont("DejaVu Sans"), 19)
    heading = ImageFont.truetype(findfont("DejaVu Sans"), 22)
    abnormal = sorted((row for row in data["records"] if row["label"] == "1"), key=lambda row: row["image_path"])
    pages = []
    for start in range(0, len(abnormal), 12):
        selected = abnormal[start:start + 12]
        page_number = start // 12 + 1
        # Grille fixe : les images a ratio variable ne peuvent pas recouvrir les legendes.
        cell_w, row_h, header_h = 310, 335, 55
        canvas = Image.new("RGB", (1944, 1430), "white")
        draw = ImageDraw.Draw(canvas)
        draw.text((972, 24), f"{name} | {RUN_ID} | alignement {page_number} | original / annotation",
                  fill="black", font=heading, anchor="mm")
        entries = []
        for index, row in enumerate(selected):
            rgb, mask = _load_pair(root, row)
            box = crop_bounds(mask)
            x0, y0, x1, y1 = box
            original, binary = rgb[y0:y1, x0:x1], mask[y0:y1, x0:x1]
            pair_x, row_y = 20 + (index % 3) * 642, 65 + (index // 3) * row_h
            labels = [f"{row['defect_type']}\n{Path(row['image_path']).name}",
                      f"surface={100 * row['mask_area_fraction']:.3g}%\ncrop xy={x0},{y0}"]
            for column, array in enumerate((original, annotation_overlay(original, binary))):
                x = pair_x + column * cell_w
                draw.multiline_text((x + cell_w / 2, row_y + 25), labels[column], fill="black", font=font,
                                    anchor="mm", align="center", spacing=2)
                thumbnail = Image.fromarray(array)
                scale = min((cell_w - 10) / thumbnail.width, (row_h - header_h - 10) / thumbnail.height)
                thumbnail = thumbnail.resize((max(1, round(thumbnail.width * scale)), max(1, round(thumbnail.height * scale))),
                                             Image.Resampling.NEAREST)
                canvas.paste(thumbnail, (x + (cell_w - thumbnail.width) // 2,
                                        row_y + header_h + (row_h - header_h - thumbnail.height) // 2))
            entries.append({"image_path": row["image_path"], "mask_path": row["mask_path"], "crop_box_native": list(box)})
        filename = f"{name}_alignment_{page_number:02d}.png"
        canvas.save(output / filename)
        pages.append({"figure": filename, "entries": entries})
    return pages


def write_visual_eda(report: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    output = Path(output_dir).resolve()
    root = Path(report["dataset_root"]).resolve()
    manifest_dir = Path(report["manifest_path"]).resolve().parent
    if output.is_relative_to(root) or output.is_relative_to(manifest_dir):
        raise ValueError("Les figures doivent rester hors des originaux et des manifestes figes.")
    filenames = ["image_statistics.csv", "visual_eda_summary.json"]
    for name, data in report["categories"].items():
        n_masks = sum(row["label"] == "1" for row in data["records"])
        filenames += [f"{name}_gallery.png", f"{name}_distributions.png"]
        filenames += [f"{name}_alignment_{index + 1:02d}.png" for index in range(math.ceil(n_masks / 12))]
    for name in filenames:
        target = output / name
        if target.is_symlink() or target.resolve().is_relative_to(root) or target.resolve().is_relative_to(manifest_dir):
            raise ValueError("Destination de figure non sure.")
    output.mkdir(parents=True, exist_ok=True)
    sheets = []
    for name, data in report["categories"].items():
        _gallery(root, name, data, output / f"{name}_gallery.png")
        _distributions(name, data, output / f"{name}_distributions.png")
        sheets.extend(_alignment_sheets(root, name, data, output))
    fields = ["image_path", "category", "split", "label", "defect_type", "mask_path", "width", "height",
              "luminance_mean", "contrast_rms", "mask_area_fraction", "mask_touches_border"]
    with (output / "image_statistics.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for data in report["categories"].values():
            writer.writerows(data["records"])
    summary = {**report, "alignment_sheets": sheets,
               "figure_sha256": {name: _sha256(output / name) for name in filenames if name.endswith(".png")}}
    (output / "visual_eda_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/raw/mvtec_ad"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/manifest.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/eda/visual"))
    arguments = parser.parse_args(argv)
    try:
        report = analyze_visual(arguments.root, arguments.manifest)
        result = write_visual_eda(report, arguments.output_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(f"EDA impossible : {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"figures": len(result["figure_sha256"]), "alignment_pairs": sum(len(page["entries"]) for page in result["alignment_sheets"]),
                      "image_count": sum(len(data["records"]) for data in result["categories"].values()),
                      "output_dir": str(arguments.output_dir), "visual_review_required": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
