"""Audit MVTec sur de petites images synthetiques, sans donnees externes."""

from __future__ import annotations

import csv
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image
import pytest

from resilientinspect.data.audit import audit_dataset, main, write_reports


def save_image(path: Path, size: tuple[int, int] = (12, 8), mode: str = "RGB") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Les masques sont binaires ; les images de groupes differents ont des
    # pixels distincts pour ne pas creer de doublons train/test involontaires.
    color = 255 if mode == "L" else tuple(
        hashlib.sha256("/".join(path.parts[-3:]).encode("utf-8")).digest()[:3]
    )
    Image.new(mode, size, color=color).save(path)
    return path


def category_layout(root: Path, name: str = "bottle", *, nested: bool = False) -> Path:
    category = root / name / name if nested else root / name
    for relative in ("train/good", "test/good", "ground_truth"):
        (category / relative).mkdir(parents=True, exist_ok=True)
    save_image(category / "train/good/000.png")
    save_image(category / "test/good/000.png")
    return category


def add_anomaly(category: Path, defect: str, stem: str = "000", *, mask: bool = True) -> None:
    save_image(category / "test" / defect / f"{stem}.png")
    if mask:
        save_image(category / "ground_truth" / defect / f"{stem}_mask.png", mode="L")


def issues_with_code(report: dict, code: str, category: str = "bottle") -> list[dict]:
    return [issue for issue in report["categories"][category]["issues"] if issue["code"] == code]


def content_snapshot(root: Path) -> dict[str, tuple[str, int]]:
    """Inclure les noms et mtimes pour detecter aussi un deplacement ou reecriture."""
    return {
        path.relative_to(root).as_posix(): (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_mtime_ns,
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def truncated_jpeg() -> bytes:
    """JPEG dont l'entete passe verify(), mais dont les pixels sont incomplets."""
    buffer = BytesIO()
    Image.new("RGB", (64, 64), color=(20, 70, 130)).save(buffer, format="JPEG")
    data = buffer.getvalue()[:-20]
    with Image.open(BytesIO(data)) as candidate:
        candidate.verify()
    with Image.open(BytesIO(data)) as candidate:
        with pytest.raises(OSError):
            candidate.load()
    return data


def test_counts_keep_train_test_and_defect_types_separate(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    save_image(category / "train/good/001.png", size=(16, 10))
    add_anomaly(category, "broken_large", "000")
    add_anomaly(category, "broken_large", "001")
    add_anomaly(category, "contamination", "000")

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "ok", report
    audited = report["categories"]["bottle"]
    assert audited["resolved_path"] == "bottle"
    assert audited["counts"] == {
        "train_good": 2,
        "test_good": 1,
        "test_anomalous": 3,
        "ground_truth_masks": 3,
        "matched_pairs": 3,
        "missing_masks": 0,
        "orphan_masks": 0,
        "corrupt_images": 0,
        "corrupt_masks": 0,
        "mask_size_mismatches": 0,
    }
    for defect, expected in (("broken_large", 2), ("contamination", 1)):
        observed = audited["defects"][defect]
        assert observed["test_images"] == expected
        assert observed["masks"] == expected
        assert observed["matched_pairs"] == expected
    assert audited["resolutions"] == {"images": {"12x8": 5, "16x10": 1}, "masks": {"12x8": 3}}
    assert audited["formats"] == {"images": {"PNG": 6}, "masks": {"PNG": 3}}
    assert audited["modes"] == {"images": {"RGB": 6}, "masks": {"L": 3}}


def test_reports_actual_decoded_formats_and_resolutions(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    save_image(category / "train/good/001.jpg", size=(10, 14))

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "ok", report
    audited = report["categories"]["bottle"]
    assert audited["counts"]["train_good"] == 2
    assert audited["formats"]["images"] == {"PNG": 2, "JPEG": 1}
    assert audited["resolutions"]["images"] == {"12x8": 2, "10x14": 1}


def test_clean_fixture_has_neither_errors_nor_warnings(tmp_path):
    root = tmp_path / "mvtec"
    add_anomaly(category_layout(root), "crack")

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "ok", report
    assert report["issue_counts"] == {"error": 0, "warning": 0}, report


def test_audit_accepts_all_requested_categories_without_cross_category_matching(tmp_path):
    root = tmp_path / "mvtec"
    for name in ("bottle", "hazelnut", "leather"):
        add_anomaly(category_layout(root, name), "defect")

    report = audit_dataset(root)

    assert set(report["categories"]) == {"bottle", "hazelnut", "leather"}
    assert report["status"] == "ok", report
    assert all(category["counts"]["matched_pairs"] == 1 for category in report["categories"].values())


def test_missing_and_orphan_masks_are_reported_with_paths(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    add_anomaly(category, "crack", "001", mask=False)
    save_image(category / "ground_truth/crack/999_mask.png", mode="L")

    report = audit_dataset(root, categories=["bottle"])

    counts = report["categories"]["bottle"]["counts"]
    assert report["status"] == "error"
    assert counts["missing_masks"] == 1
    assert counts["orphan_masks"] == 1
    assert counts["matched_pairs"] == 0
    assert "001.png" in issues_with_code(report, "missing_mask")[0]["path"]
    assert "999_mask.png" in issues_with_code(report, "orphan_mask")[0]["path"]
    assert all(issue["severity"] == "error" for code in ("missing_mask", "orphan_mask") for issue in issues_with_code(report, code))


def test_same_stem_in_another_defect_does_not_match(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    add_anomaly(category, "crack", "001", mask=False)
    save_image(category / "ground_truth/hole/001_mask.png", mode="L")

    report = audit_dataset(root, categories=("bottle",))

    counts = report["categories"]["bottle"]["counts"]
    assert counts["matched_pairs"] == 0
    assert counts["missing_masks"] == counts["orphan_masks"] == 1


@pytest.mark.parametrize("duplicate_kind", ["image", "mask"])
def test_same_stem_with_multiple_images_or_masks_is_ambiguous(tmp_path, duplicate_kind):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    add_anomaly(category, "crack", "001")
    if duplicate_kind == "image":
        save_image(category / "test/crack/001.jpg")
    else:
        save_image(category / "ground_truth/crack/001_mask.bmp", mode="L")

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "error"
    assert len(issues_with_code(report, "ambiguous_pair")) == 1
    counts = report["categories"]["bottle"]["counts"]
    assert counts["test_anomalous"] == (2 if duplicate_kind == "image" else 1)
    assert counts["ground_truth_masks"] == (2 if duplicate_kind == "mask" else 1)
    assert counts["matched_pairs"] == 0


def test_mask_without_required_suffix_is_orphan_and_does_not_match(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    add_anomaly(category, "crack", "001", mask=False)
    save_image(category / "ground_truth/crack/001.png", mode="L")

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "error"
    counts = report["categories"]["bottle"]["counts"]
    assert counts["ground_truth_masks"] == 1
    assert counts["orphan_masks"] == counts["missing_masks"] == 1
    assert counts["matched_pairs"] == 0
    assert "001.png" in issues_with_code(report, "orphan_mask")[0]["path"]


def test_mask_size_mismatch_is_an_error(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    add_anomaly(category, "crack")
    save_image(category / "ground_truth/crack/000_mask.png", size=(6, 4), mode="L")

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "error"
    assert report["categories"]["bottle"]["counts"]["mask_size_mismatches"] == 1
    assert len(issues_with_code(report, "mask_size_mismatch")) == 1


@pytest.mark.parametrize("kind", ["image", "mask"])
def test_corruption_requires_full_pixel_decode(tmp_path, kind):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    if kind == "image":
        destination = category / "test/crack/001.jpg"
        save_image(category / "ground_truth/crack/001_mask.png", size=(64, 64), mode="L")
    else:
        save_image(category / "test/crack/001.png", size=(64, 64))
        destination = category / "ground_truth/crack/001_mask.jpg"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(truncated_jpeg())

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "error"
    code = f"corrupt_{kind}"
    count = "corrupt_images" if kind == "image" else "corrupt_masks"
    assert report["categories"]["bottle"]["counts"][count] == 1
    assert len(issues_with_code(report, code)) == 1
    assert destination.name in issues_with_code(report, code)[0]["path"]


def test_unambiguous_nested_category_is_resolved_without_moving_files(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root, nested=True)
    add_anomaly(category, "crack")
    before = content_snapshot(root)

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "ok", report
    assert report["categories"]["bottle"]["resolved_path"] == "bottle/bottle"
    assert report["categories"]["bottle"]["counts"]["train_good"] == 1
    warning = issues_with_code(report, "nested_category")
    assert len(warning) == 1 and warning[0]["severity"] == "warning"
    assert content_snapshot(root) == before


def test_canonical_and_nested_data_are_an_ambiguous_error(tmp_path):
    root = tmp_path / "mvtec"
    category_layout(root)
    category_layout(root, nested=True)
    before = content_snapshot(root)

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "error"
    assert len(issues_with_code(report, "ambiguous_layout")) == 1
    assert content_snapshot(root) == before


@pytest.mark.parametrize("missing", ["category", "train/good", "test/good", "ground_truth"])
def test_missing_category_or_required_directory_is_explicit(tmp_path, missing):
    root = tmp_path / "mvtec"
    root.mkdir()
    if missing != "category":
        category = category_layout(root)
        target = category / missing
        for path in target.iterdir():
            path.unlink()
        target.rmdir()

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "error"
    assert issues_with_code(report, "missing_directory"), report


@pytest.mark.parametrize("relative_group,count", [("train/good", "train_good"), ("test/good", "test_good")])
def test_empty_required_normal_group_is_an_error(tmp_path, relative_group, count):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    for image in (category / relative_group).iterdir():
        image.unlink()

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "error"
    assert report["categories"]["bottle"]["counts"][count] == 0
    errors = issues_with_code(report, "empty_required_group")
    assert len(errors) == 1
    assert errors[0]["severity"] == "error"
    assert errors[0]["path"] == f"bottle/{relative_group}"


def test_empty_anomaly_directory_is_a_warning(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    (category / "test/crack").mkdir()

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "ok", report
    warnings = issues_with_code(report, "empty_defect_group")
    assert len(warnings) == 1
    assert warnings[0]["severity"] == "warning"
    assert warnings[0]["path"] == "bottle/test/crack"


@pytest.mark.parametrize("unexpected_directory", ["extra_data", "bottle"])
def test_unexpected_nonempty_category_directory_is_not_silently_ignored(tmp_path, unexpected_directory):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    save_image(category / unexpected_directory / "stray.png")
    before = content_snapshot(root)

    report = audit_dataset(root, categories=("bottle",))

    assert report["status"] == "error"
    errors = issues_with_code(report, "unexpected_category_entry")
    assert len(errors) == 1
    assert errors[0]["severity"] == "error"
    assert errors[0]["path"] == f"bottle/{unexpected_directory}"
    assert content_snapshot(root) == before


def test_audit_and_reports_preserve_every_original_byte_and_mtime(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    add_anomaly(category, "crack")
    before = content_snapshot(root)

    report = audit_dataset(root, categories=("bottle",))
    write_reports(report, tmp_path / "reports")

    assert content_snapshot(root) == before


def test_json_and_csv_reports_reproduce_audit_counts(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    add_anomaly(category, "crack", "001")
    add_anomaly(category, "crack", "002", mask=False)
    report = audit_dataset(root, categories=("bottle",))
    output = tmp_path / "reports"

    written = write_reports(report, output)

    assert isinstance(written, dict)
    expected_files = {"audit.json", "audit_summary.csv", "audit_by_defect.csv"}
    assert expected_files.issubset({path.name for path in output.iterdir()})
    assert {Path(path).name for path in written.values()} == expected_files
    assert json.loads((output / "audit.json").read_text(encoding="utf-8")) == report
    with (output / "audit_summary.csv").open(encoding="utf-8-sig", newline="") as stream:
        summary = list(csv.DictReader(stream))
    assert len(summary) == 1 and summary[0]["category"] == "bottle"
    for count, expected in report["categories"]["bottle"]["counts"].items():
        assert int(summary[0][count]) == expected
    with (output / "audit_by_defect.csv").open(encoding="utf-8-sig", newline="") as stream:
        defects = list(csv.DictReader(stream))
    assert len(defects) == 1
    assert defects[0]["category"] == "bottle"
    assert defects[0]["defect"] == "crack"
    for count in ("test_images", "masks", "matched_pairs"):
        assert int(defects[0][count]) == report["categories"]["bottle"]["defects"]["crack"][count]


@pytest.mark.parametrize("relative_output", [".", "reports/eda"])
def test_reports_cannot_be_written_inside_the_dataset(tmp_path, relative_output):
    root = tmp_path / "mvtec"
    category_layout(root)
    before = content_snapshot(root)
    report = audit_dataset(root, categories=("bottle",))

    with pytest.raises(ValueError):
        write_reports(report, root / relative_output)

    assert content_snapshot(root) == before
    assert not (root / "audit.json").exists()
    assert not (root / "reports").exists()


@pytest.mark.parametrize("nested", [False, True])
def test_cli_succeeds_for_clean_or_nested_layout(tmp_path, nested):
    root = tmp_path / "mvtec"
    category_layout(root, nested=nested)
    output = tmp_path / "reports"

    result = main(["--root", str(root), "--categories", "bottle", "--output-dir", str(output)])

    assert result == 0
    assert (output / "audit.json").is_file()


def test_cli_audit_errors_still_produce_reports(tmp_path):
    root = tmp_path / "mvtec"
    category = category_layout(root)
    add_anomaly(category, "crack", mask=False)
    output = tmp_path / "reports"

    result = main(["--root", str(root), "--categories", "bottle", "--output-dir", str(output)])

    assert result == 1
    assert json.loads((output / "audit.json").read_text(encoding="utf-8"))["status"] == "error"


def test_cli_returns_operational_error_for_unsafe_report_location(tmp_path):
    root = tmp_path / "mvtec"
    category_layout(root)

    result = main(["--root", str(root), "--categories", "bottle", "--output-dir", str(root / "reports")])

    assert result == 2
    assert not (root / "reports").exists()
