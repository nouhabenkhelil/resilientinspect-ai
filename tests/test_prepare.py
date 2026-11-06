"""Non-fuite et reproductibilite sur des donnees synthetiques temporaires."""

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import random

from PIL import Image
import pytest
import yaml

from resilientinspect.data.prepare import (
    MANIFEST_FIELDS, main, prepare_dataset, read_manifest, safe_data_path,
    validate_manifest, write_manifests,
)


def make_dataset(root: Path, categories=("bottle", "hazelnut", "leather"), n=10):
    for category_index, category in enumerate(categories):
        base = root / category
        for index in range(n):
            path = base / "train/good" / f"{index:03d}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (16, 8), (index + category_index * 40, 20, 80)).save(path)
        path = base / "test/good/000.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 8), (240, 35, 20)).save(path)
        image = Image.new("RGB", (16, 8), 0)
        mask = Image.new("L", image.size, 0)
        for x in range(4, 12):
            for y in range(2, 6):
                image.putpixel((x, y), (255, 255, 255))
                mask.putpixel((x, y), 255)
        image_path = base / "test/crack/001.png"
        mask_path = base / "ground_truth/crack/001_mask.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(image_path)
        mask.save(mask_path)
    return root


@pytest.fixture
def prepared(tmp_path):
    root = make_dataset(tmp_path / "mvtec")
    rows, report = prepare_dataset(root)
    output = tmp_path / "manifests"
    written = write_manifests(rows, report, output)
    return root, rows, written, output


def snapshot(root):
    return {path.relative_to(root).as_posix(): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


def test_partition_is_category_stratified_and_test_is_untouched(prepared):
    root, rows, report, output = prepared
    for category in ("bottle", "hazelnut", "leather"):
        groups = {split: {row["image_path"] for row in rows if row["category"] == category and row["split"] == split}
                  for split in ("train", "val", "test")}
        assert [len(groups[split]) for split in ("train", "val", "test")] == [8, 2, 2]
        assert not groups["train"] & groups["val"]
        assert not (groups["train"] | groups["val"]) & groups["test"]
        assert groups["train"] | groups["val"] == {
            path.relative_to(root).as_posix() for path in (root / category / "train/good").glob("*.png")}
        assert groups["test"] == {
            path.relative_to(root).as_posix() for path in (root / category / "test").rglob("*.png")}
    assert all(row["label"] == "0" and row["source_split"] == "train" and not row["mask_path"]
               for row in rows if row["split"] in ("train", "val"))
    assert report["totals"] == {"train": 24, "val": 6, "test": 6}
    assert len(read_manifest(output / "manifest.csv")) == 36
    assert len({row["sha256"] for row in rows if row["split"] == "train"} &
               {row["sha256"] for row in rows if row["split"] == "val"}) == 0


def test_rounding_is_explicit_ceil_not_an_exact_fraction_claim(tmp_path):
    root = make_dataset(tmp_path / "mvtec", ("bottle",), n=11)
    _, report = prepare_dataset(root, ("bottle",))
    assert report["counts"]["bottle"]["train"] == 8
    assert report["counts"]["bottle"]["val"] == 3
    assert report["validation_rounding"] == "ceil"


def test_reproducibility_rng_category_order_and_test_independence(tmp_path):
    root = make_dataset(tmp_path / "mvtec", n=15)
    random.seed(678)
    state = random.getstate()
    rows_a, report_a = prepare_dataset(root, seed=42)
    assert random.getstate() == state
    rows_b, report_b = prepare_dataset(root, ("leather", "hazelnut", "bottle"), seed=42)
    assert rows_a == rows_b and report_a == report_b
    rows_c, _ = prepare_dataset(root, seed=43)
    assert {row["image_path"] for row in rows_a if row["split"] == "val"} != {
        row["image_path"] for row in rows_c if row["split"] == "val"}
    assert [row for row in rows_a if row["split"] == "test"] == [row for row in rows_c if row["split"] == "test"]
    for rows, report, output in ((rows_a, report_a, tmp_path / "one"), (rows_b, report_b, tmp_path / "two")):
        write_manifests(rows, report, output)
    for name in ("manifest.csv", "train.csv", "val.csv", "test.csv", "preparation.json"):
        assert (tmp_path / "one" / name).read_bytes() == (tmp_path / "two" / name).read_bytes()


def test_reports_have_relative_paths_and_verified_checksums(prepared):
    root, rows, report, output = prepared
    for row in rows:
        assert not Path(row["image_path"]).is_absolute()
        assert "\\" not in row["image_path"]
        assert hashlib.sha256((root / row["image_path"]).read_bytes()).hexdigest() == row["sha256"]
        if row["label"] == "1":
            assert row["mask_path"] == row["image_path"].replace("/test/", "/ground_truth/").replace("001.png", "001_mask.png")
            assert hashlib.sha256((root / row["mask_path"]).read_bytes()).hexdigest() == row["mask_sha256"]
    for name, digest in report["manifest_sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    with (output / "manifest.csv").open(newline="", encoding="utf-8") as stream:
        assert csv.DictReader(stream).fieldnames == list(MANIFEST_FIELDS)


def test_preparation_preserves_all_original_bytes_and_mtimes(tmp_path):
    root = make_dataset(tmp_path / "mvtec")
    before = snapshot(root)
    rows, report = prepare_dataset(root)
    write_manifests(rows, report, tmp_path / "manifests")
    assert snapshot(root) == before


def test_frozen_manifests_are_idempotent_and_never_overwritten(prepared):
    root, rows, report, output = prepared
    before = snapshot(output)
    write_manifests(rows, report, output)
    assert snapshot(output) == before
    changed_rows, changed_report = prepare_dataset(root, seed=43)
    with pytest.raises(FileExistsError):
        write_manifests(changed_rows, changed_report, output)
    assert snapshot(output) == before


def test_outputs_inside_originals_are_refused(prepared):
    root, rows, report, _ = prepared
    before = snapshot(root)
    with pytest.raises(ValueError):
        write_manifests(rows, report, root / "generated")
    with pytest.raises(ValueError):
        write_manifests(rows, report, root.parent / "other", root / "report.json")
    assert not (root.parent / "other").exists()
    assert snapshot(root) == before


@pytest.mark.parametrize("mutation", ["same_path", "same_content", "test_in_val", "bad_mask", "normal_with_mask", "absolute", "traversal"])
def test_manifest_rejects_leakage_and_invalid_provenance(prepared, mutation):
    _, rows, _, _ = prepared
    bad = deepcopy(rows)
    train = next(row for row in bad if row["split"] == "train")
    val = next(row for row in bad if row["split"] == "val")
    anomaly = next(row for row in bad if row["label"] == "1")
    if mutation == "same_path": val["image_path"] = train["image_path"]
    elif mutation == "same_content": val["sha256"] = train["sha256"]
    elif mutation == "test_in_val": anomaly["split"] = "val"
    elif mutation == "bad_mask": anomaly["mask_path"] = anomaly["mask_path"].replace("crack", "hole")
    elif mutation == "normal_with_mask": train["mask_path"] = anomaly["mask_path"]
    elif mutation == "absolute": train["image_path"] = "C:/private/image.png"
    else: train["image_path"] = "../outside.png"
    with pytest.raises(ValueError): validate_manifest(bad)


def test_actual_duplicate_content_cannot_cross_train_val(prepared):
    root, rows, _, _ = prepared
    train = next(row for row in rows if row["category"] == "bottle" and row["split"] == "train")
    val = next(row for row in rows if row["category"] == "bottle" and row["split"] == "val")
    (root / val["image_path"]).write_bytes((root / train["image_path"]).read_bytes())
    with pytest.raises(ValueError, match="Fuite de contenu"):
        prepare_dataset(root)


@pytest.mark.parametrize("relative", ["../image.png", "/absolute.png", "C:/absolute.png", "bottle\\train\\good\\0.png"])
def test_unsafe_paths_are_rejected(tmp_path, relative):
    with pytest.raises(ValueError): safe_data_path(tmp_path, relative)


def test_missing_or_corrupt_mask_blocks_generation(prepared):
    root, rows, _, _ = prepared
    mask = root / next(row["mask_path"] for row in rows if row["label"] == "1")
    mask.write_bytes(b"not a PNG")
    with pytest.raises(ValueError, match="Audit incompatible"):
        prepare_dataset(root)


def test_unrecognized_split_file_is_not_silently_dropped(prepared):
    root, _, _, _ = prepared
    (root / "bottle/test/good/unknown.bin").write_bytes(b"unrecognized")
    with pytest.raises(ValueError, match="unexpected_file"):
        prepare_dataset(root)


def test_cli_generates_manifests_and_report(tmp_path):
    root = make_dataset(tmp_path / "mvtec")
    output, report = tmp_path / "manifests", tmp_path / "report.json"
    assert main(["--root", str(root), "--output-dir", str(output), "--report", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["totals"] == {"train": 24, "val": 6, "test": 6}
    assert len(read_manifest(output / "test.csv")) == 6
    config = yaml.safe_load(Path("configs/dataset.yaml").read_text(encoding="utf-8"))
    config["dataset"]["preprocessing"]["normalization"] = "test_statistics"
    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text(yaml.safe_dump(config), encoding="utf-8")
    assert main(["--config", str(bad_config), "--root", str(root), "--output-dir", str(tmp_path / "bad")]) == 1
    assert not (tmp_path / "bad").exists()
