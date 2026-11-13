"""Diagnostics scientifiques sur comptages synthétiques, sans données MVTec."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "diagnostic", Path(__file__).resolve().parents[1] / "scripts/diagnose_b0_a1.py"
)
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def rows():
    return [
        dict(label=0, score=.1, predicted_label=0, tp=0, fp=100, fn=0, defect_type="good", empty_anomalous_mask=False),
        dict(label=0, score=.2, predicted_label=0, tp=0, fp=0, fn=0, defect_type="good", empty_anomalous_mask=False),
        dict(label=1, score=.8, predicted_label=1, tp=9, fp=0, fn=1, defect_type="crack", empty_anomalous_mask=False),
        dict(label=1, score=.9, predicted_label=1, tp=1, fp=0, fn=9, defect_type="hole", empty_anomalous_mask=False),
    ]


def test_micro_overlap_includes_normal_false_positive_pixels():
    values = diagnostic.measurements(diagnostic.arrays(rows()))
    # Image classement/décisions parfaits, mais 100 FP pixel sur une normale.
    assert values[:3] == pytest.approx([1, 1, 1])
    assert values[3] == pytest.approx(20 / 130)
    assert values[4] == pytest.approx(10 / 120)
    assert values[3] != pytest.approx((.9 + .1) / 2)


def test_bootstrap_pairs_whole_images_and_is_reproducible(monkeypatch):
    monkeypatch.setattr(diagnostic, "REPLICATES", 40)
    original = diagnostic.measurements
    observed = []

    def inspect(sample):
        # Deux images par classe, TP/FP/FN toujours ceux d'une image entière.
        assert sorted(sample[:, 0]) == [0, 0, 1, 1]
        assert all(tuple(r) in {tuple(s) for s in diagnostic.arrays(rows())} for r in sample)
        observed.append(sample.copy())
        return original(sample)

    monkeypatch.setattr(diagnostic, "measurements", inspect)
    predictions = {(m, c): rows() for m in diagnostic.MODELS for c in diagnostic.CATEGORIES}
    result = diagnostic.paired_bootstrap(predictions)
    first_samples = observed[:240]
    for i in range(0, len(first_samples), 2):
        np.testing.assert_array_equal(first_samples[i], first_samples[i + 1])
    assert all(r["delta_low"] == r["delta_high"] == r["delta"] == 0 for r in result)
    assert diagnostic.paired_bootstrap(predictions) == result


def test_defect_segmentation_excludes_normals_but_image_ranking_uses_them():
    predictions = {(m, c): rows() for m in diagnostic.MODELS for c in diagnostic.CATEGORIES}
    result = diagnostic.defect_metrics(predictions)
    crack = next(r for r in result if r["defect"] == "crack")
    assert crack["normal_n"] == 2 and crack["anomalous_n"] == 1
    assert crack["image_auroc_vs_good"] == 1
    assert crack["dice_defect_only"] == pytest.approx(18 / 19)
    assert crack["iou_defect_only"] == pytest.approx(9 / 10)
