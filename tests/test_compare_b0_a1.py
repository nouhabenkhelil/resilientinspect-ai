"""Comparaison de rapports synthetiques uniquement, aucune ouverture du dataset."""

import csv
import json
import pytest

from resilientinspect.evaluation import compare_b0_a1 as comparison
from resilientinspect.evaluation import evaluate_ae as ev


def report(category, variant="B0", value=0.5):
    return {"category": category, "variant": variant, "split": "test", "resolution": [256, 256],
            "padding_excluded": True, "protocol_sha256": "a" * 64, "manifest_sha256": "b" * 64,
            "dataset_code_sha256": "c" * 64, "checkpoint_sha256": "d" * 64,
            "calibration_sha256": "e" * 64,
            "metrics": {"image": {"auroc": value, "ap": value}, "pixel": {"auroc": value, "ap": value},
                        "image_decision": {"f1": value}, "segmentation_micro": {"dice": value, "iou": value}}}


def write_reports(root, variant="B0"):
    for category in ev.CATEGORIES:
        path = root / category / "metrics.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(report(category, variant)), encoding="utf-8")


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_pending_table_is_read_only_and_reproducible_without_inference(tmp_path, monkeypatch):
    b0, a1, output = tmp_path / "b0", tmp_path / "a1", tmp_path / "comparison"
    write_reports(b0)
    before = snapshot(b0)

    def forbidden(*args, **kwargs):
        raise AssertionError("Aucune inference ou lecture dataset autorisee pour une comparaison.")

    monkeypatch.setattr(ev, "infer_records", forbidden)
    monkeypatch.setattr(ev, "load_model", forbidden)
    monkeypatch.setattr(ev, "MVTecDataset", forbidden)
    first = comparison.build_comparison(b0, a1, output)
    saved = snapshot(output)
    assert comparison.build_comparison(b0, a1, output) == first
    assert snapshot(output) == saved
    assert snapshot(b0) == before
    assert not a1.exists()
    assert len(first["rows"]) == 6
    for row in first["rows"]:
        assert row["status"] == ("pending" if row["model"] == "A1" else "evaluated")
        if row["model"] == "A1":
            assert all(row[name] is None for name in comparison.METRICS)
        else:
            assert row["source"]["sha256"]
    with (output / "comparison.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6 and rows[1]["image_auroc"] == ""


def test_complete_comparison_preserves_both_sources(tmp_path):
    b0, a1 = tmp_path / "b0", tmp_path / "a1"
    write_reports(b0)
    write_reports(a1, "A1")
    before = snapshot(tmp_path)
    result = comparison.build_comparison(b0, a1, tmp_path / "table")
    assert all(row["status"] == "evaluated" for row in result["rows"])
    assert all(path.read_bytes() == data for name, data in before.items() for path in [tmp_path / name])


@pytest.mark.parametrize("key,value", [("protocol_sha256", "f" * 64), ("manifest_sha256", "f" * 64),
                                     ("dataset_code_sha256", "f" * 64), ("resolution", [128, 128]),
                                     ("padding_excluded", False), ("variant", "B0"), ("split", "val")])
def test_incompatible_a1_is_rejected_before_writing(tmp_path, key, value):
    b0, a1 = tmp_path / "b0", tmp_path / "a1"
    write_reports(b0)
    write_reports(a1, "A1")
    path = a1 / "bottle/metrics.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data[key] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        comparison.build_comparison(b0, a1, tmp_path / "table")
    assert not (tmp_path / "table").exists()


def test_missing_b0_and_invalid_metrics_fail(tmp_path):
    b0, a1 = tmp_path / "b0", tmp_path / "a1"
    with pytest.raises(FileNotFoundError):
        comparison.build_comparison(b0, a1, tmp_path / "table")
    write_reports(b0)
    data = report("bottle", value=float("nan"))
    (b0 / "bottle/metrics.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Metrique"):
        comparison.build_comparison(b0, a1, tmp_path / "table")


@pytest.mark.parametrize("relative", ["b0", "b0/table", "a1/table", "."])
def test_output_never_overlaps_sources(tmp_path, relative):
    b0, a1 = tmp_path / "b0", tmp_path / "a1"
    write_reports(b0)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match="Sorties"):
        comparison.build_comparison(b0, a1, tmp_path / relative)
    assert snapshot(tmp_path) == before


def test_project_output_is_limited_to_a1(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison, "PROJECT", tmp_path)
    b0, a1 = tmp_path / "reports/evaluation/b0/run", tmp_path / "reports/evaluation/a1/run"
    write_reports(b0)
    with pytest.raises(ValueError, match="limitees"):
        comparison.build_comparison(b0, a1, tmp_path / "reports/evaluation/b0/comparison")
    result = comparison.build_comparison(b0, a1, tmp_path / "reports/evaluation/a1/comparison")
    assert len(result["rows"]) == 6


def test_cli_and_no_overwrite_of_different_snapshot(tmp_path):
    b0, a1, output = tmp_path / "b0", tmp_path / "a1", tmp_path / "table"
    write_reports(b0)
    arguments = ["--b0-dir", str(b0), "--a1-dir", str(a1), "--output-dir", str(output)]
    assert comparison.main(arguments) == 0
    before = snapshot(output)
    write_reports(a1, "A1")
    assert comparison.main(arguments) == 1
    assert snapshot(output) == before
