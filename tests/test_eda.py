"""Statistiques natives et figures locales, sur fixtures synthetiques uniquement."""

import csv
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image
import pytest

from resilientinspect.data.audit import _sha256
from resilientinspect.data.eda import (
    analyze_visual, annotation_overlay, crop_bounds, gallery_selection,
    main, native_metrics, write_visual_eda,
)
from resilientinspect.data.prepare import MANIFEST_FIELDS
from test_prepare import prepared, snapshot


def test_luminance_and_contrast_are_native_population_statistics():
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    rgb[:, 1] = 255
    mean, contrast, histogram = native_metrics(rgb)
    assert mean == pytest.approx(0.5)
    assert contrast == pytest.approx(0.5)
    assert histogram.sum() == 4
    assert histogram[0] == histogram[-1] == 2
    red = np.zeros((3, 4, 3), dtype=np.uint8)
    red[:, :, 0] = 255
    mean, contrast, _ = native_metrics(red)
    assert mean == pytest.approx(0.2126)
    assert contrast == pytest.approx(0)


def test_overlay_does_not_modify_original_and_matches_exact_native_mask():
    rgb = np.full((7, 7, 3), 100, dtype=np.uint8)
    mask = np.zeros((7, 7), dtype=bool)
    mask[1:6, 1:6] = True
    before = rgb.copy()
    overlay = annotation_overlay(rgb, mask)
    assert np.array_equal(rgb, before)
    assert np.array_equal(overlay[~mask], rgb[~mask])
    assert overlay[1, 1].tolist() == [255, 255, 0]
    assert overlay[3, 3].tolist() == [154, 65, 65]
    assert np.array_equal(annotation_overlay(rgb, np.zeros_like(mask)), rgb)
    with pytest.raises(ValueError):
        annotation_overlay(rgb, mask[:3])


def test_crop_keeps_every_mask_pixel_and_clips_to_native_bounds():
    mask = np.zeros((180, 200), dtype=bool)
    mask[2:4, 195:200] = True
    x0, y0, x1, y1 = crop_bounds(mask)
    assert 0 <= x0 <= 195 and 200 == x1
    assert y0 == 0 and 4 <= y1 <= 180
    assert mask[y0:y1, x0:x1].sum() == mask.sum()
    assert crop_bounds(np.zeros((10, 20), dtype=bool)) == (0, 0, 20, 10)


def test_analysis_covers_all_splits_and_uses_native_mask_surface(prepared):
    root, _, _, output = prepared
    before, manifest_before = snapshot(root), snapshot(output)
    report = analyze_visual(root, output / "manifest.csv")
    assert snapshot(root) == before and snapshot(output) == manifest_before
    for category, data in report["categories"].items():
        assert len(data["records"]) == 12
        assert data["groups"]["train/good"]["luminance_mean"]["n"] == 8
        assert data["groups"]["val/good"]["luminance_mean"]["n"] == 2
        assert data["mask_areas"]["crack"]["median"] == pytest.approx(0.25)
        assert sum(sum(bins) for bins in data["pixel_luminance_histogram"].values()) == 12 * 16 * 8
        assert all(row["mask_area_fraction"] is None for row in data["records"] if row["label"] == "0")
        selected = gallery_selection(list(reversed(data["records"])))
        assert [row["image_path"] for row in selected] == data["gallery_paths"]
        assert {row["split"] for row in selected if row["label"] == "0"} == {"train", "val", "test"}
        assert {row["defect_type"] for row in selected if row["label"] == "1"} == {"crack"}


def test_reports_and_sheets_cover_every_anomaly_and_preserve_sources(prepared, tmp_path):
    root, rows, _, output = prepared
    before, manifest_before = snapshot(root), snapshot(output)
    report = analyze_visual(root, output / "manifest.csv")
    result = write_visual_eda(report, tmp_path / "visual")
    assert len(result["figure_sha256"]) == 9
    covered = [entry["image_path"] for page in result["alignment_sheets"] for entry in page["entries"]]
    assert set(covered) == {row["image_path"] for row in rows if row["label"] == "1"}
    assert len(covered) == len(set(covered)) == 3
    for name, digest in result["figure_sha256"].items():
        path = tmp_path / "visual" / name
        assert _sha256(path) == digest
        with Image.open(path) as image:
            image.verify()
    assert snapshot(root) == before and snapshot(output) == manifest_before
    summary = json.loads((tmp_path / "visual/visual_eda_summary.json").read_text(encoding="utf-8"))
    assert summary["visual_review"]["required"] is True
    assert summary["manifest_sha256"] == _sha256(output / "manifest.csv")


@pytest.mark.parametrize("target", ["originals", "manifests"])
def test_writing_into_protected_inputs_is_refused(prepared, target):
    root, _, _, output = prepared
    before, manifest_before = snapshot(root), snapshot(output)
    report = analyze_visual(root, output / "manifest.csv")
    with pytest.raises(ValueError):
        write_visual_eda(report, (root if target == "originals" else output) / "visual")
    assert snapshot(root) == before and snapshot(output) == manifest_before


@pytest.mark.parametrize("kind", ["image", "mask", "manifest"])
def test_stale_inputs_do_not_silently_produce_new_statistics(prepared, kind):
    root, rows, _, output = prepared
    if kind == "manifest":
        # Modifier l'ordre conserve la validite structurelle mais change l'empreinte figee.
        path = output / "manifest.csv"
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join([lines[0], *reversed(lines[1:])]) + "\n", encoding="utf-8")
    else:
        row = next(row for row in rows if row["label"] == "1")
        (root / row["image_path" if kind == "image" else "mask_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="mpreinte"):
        analyze_visual(root, output / "manifest.csv")


def test_visual_figures_are_ignored_by_git():
    paths = ["reports/eda/visual/bottle_gallery.png", "reports/eda/visual/bottle_alignment_01.png",
             "reports/eda/visual/visual_eda_summary.json"]
    result = subprocess.run(["git", "check-ignore", "--no-index", "-z", "--stdin"],
                            input=("\0".join(paths) + "\0").encode(), capture_output=True, check=True)
    assert set(result.stdout.decode().split("\0")) - {""} == set(paths)


@pytest.mark.parametrize("problem", ["size", "values"])
def test_mask_alignment_and_binary_errors_are_not_repaired_silently(prepared, tmp_path, problem):
    root, rows, _, _ = prepared
    row = next(row for row in rows if row["label"] == "1")
    path = root / row["mask_path"]
    Image.new("L", (3, 3) if problem == "size" else (16, 8), 255 if problem == "size" else 127).save(path)
    row["mask_sha256"] = _sha256(path)
    manifest = tmp_path / "custom.csv"
    with manifest.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="Desalignement" if problem == "size" else "non binaire"):
        analyze_visual(root, manifest)


def test_cli_bad_source_is_an_error_and_does_not_write_figures(prepared, tmp_path):
    root, rows, _, output = prepared
    (root / rows[0]["image_path"]).write_bytes(b"changed")
    destination = tmp_path / "visual"
    assert main(["--root", str(root), "--manifest", str(output / "manifest.csv"), "--output-dir", str(destination)]) == 1
    assert not destination.exists()
