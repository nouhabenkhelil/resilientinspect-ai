"""Evaluation B0 : uniquement tenseurs, images et checkpoints synthetiques temporaires."""

from dataclasses import replace
import json
import os
from pathlib import Path
import random
import shutil

import numpy as np
from PIL import Image
import pytest
import torch
import yaml

from resilientinspect.evaluation import evaluate_ae as ev
from resilientinspect.data.prepare import prepare_dataset, write_manifests
from resilientinspect.models.autoencoder import ConvAutoencoder
from test_prepare import make_dataset, snapshot

PROJECT = Path(__file__).resolve().parents[1]
PROTOCOL = PROJECT / "configs/evaluate_ae_b0.yaml"


@pytest.fixture(scope="module", autouse=True)
def restore_process_state():
    threads = torch.get_num_threads()
    deterministic = torch.are_deterministic_algorithms_enabled()
    benchmark, cudnn = torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic
    precision = torch.get_float32_matmul_precision()
    python_state, numpy_state = random.getstate(), np.random.get_state()
    env = {key: os.environ.get(key) for key in ("MPLCONFIGDIR", "CUBLAS_WORKSPACE_CONFIG")}
    with torch.random.fork_rng(devices=[]):
        torch.set_num_threads(2)
        yield
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(deterministic)
    torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic = benchmark, cudnn
    torch.set_float32_matmul_precision(precision)
    random.setstate(python_state)
    np.random.set_state(numpy_state)
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def record(value=0.1, *, split="val", label=0, name="0.png"):
    return {"error": np.full((2, 2), value, dtype=np.float32), "valid": np.ones((2, 2), bool),
            "mask": np.zeros((2, 2), bool), "category": "bottle", "split": split,
            "source_split": "train" if split == "val" else "test", "label": label,
            "defect_type": "good" if label == 0 else "crack", "mask_path": "",
            "image_path": f"bottle/{'train' if split == 'val' else 'test'}/good/{name}"}


def write_run(root, category, manifest_sha, *, name="full_synthetic", scope="full", seed=42):
    path = root / category / name
    path.mkdir(parents=True)
    effective = {"variant": "B0", "category": category, "scope": scope,
                 "max_batches_per_split": None if scope == "full" else 2}
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = ConvAutoencoder()
    torch.save({"model_state_dict": model.state_dict(), "epoch": 1, "category": category,
                "variant": "B0", "scope": scope, "manifest_sha256": manifest_sha,
                "effective_config": effective}, path / "best.pt")
    summary = {"status": "completed", "scope": scope, "category": category, "selection_split": "val",
               "test_used": False, "best_epoch": 1, "epochs_completed": 1, "run_id": name,
               "checkpoint_sha256": ev._sha256(path / "best.pt"), "manifest_sha256": manifest_sha}
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (path / "effective_config.yaml").write_text(yaml.safe_dump(effective), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("evaluation_synthetic")
    root = make_dataset(tmp / "raw")
    rows, report = prepare_dataset(root)
    manifests = tmp / "manifests"
    write_manifests(rows, report, manifests)
    manifest = manifests / "manifest.csv"
    runs = tmp / "runs"
    for category in ev.CATEGORIES:
        write_run(runs, category, ev.manifest_digest(manifest))
    write_run(runs, "bottle", ev.manifest_digest(manifest), name="smoke_fake", scope="smoke")
    for category in ev.CATEGORIES:
        copy = runs / "mlartifacts" / category / "artifacts"
        shutil.copytree(runs / category / "full_synthetic", copy)
    selected, _ = ev.discover_checkpoints(runs)
    return tmp, root, manifest, runs, selected


def test_l1_map_is_channel_mean_without_smoothing_or_mutation():
    x = torch.zeros(1, 3, 2, 2)
    y = x.clone()
    y[0, :, 0, 0] = torch.tensor([0.3, 0.6, 0.9])
    before = y.clone()
    actual = ev.anomaly_maps(x, y)
    assert actual.shape == (1, 2, 2)
    assert actual[0, 0, 0].item() == pytest.approx(0.6)
    assert actual.count_nonzero().item() == 1
    assert torch.equal(before, y) and torch.count_nonzero(x) == 0


@pytest.mark.parametrize("case", ["shape", "channels", "nan", "inf", "range"])
def test_invalid_reconstruction_is_rejected(case):
    x = torch.zeros(1, 3, 2, 2)
    y = x.clone()
    if case == "shape": y = y[..., :1]
    elif case == "channels": x, y = x[:, :1], y[:, :1]
    else: y[0, 0, 0, 0] = {"nan": float("nan"), "inf": float("inf"), "range": 1.1}[case]
    with pytest.raises(ValueError): ev.anomaly_maps(x, y)


def test_top_fraction_uses_ceil_and_excludes_padding():
    error = np.zeros((1, 102), dtype=np.float32)
    error[0, -3:] = [0.3, 0.7, 1.0]
    valid = np.ones_like(error, dtype=bool)
    valid[0, -1] = False  # 101 valides -> ceil(1.01) = 2.
    assert ev.image_score(error, valid) == pytest.approx(0.5)
    with pytest.raises(ValueError): ev.image_score(error, np.zeros_like(valid))
    with pytest.raises(ValueError): ev.image_score(error, valid, 0)
    with pytest.raises(ValueError): ev.valid_values(error, np.full_like(error, 2))


def test_calibration_quantiles_higher_strict_ties_and_order_invariance():
    protocol = ev.load_protocol(PROTOCOL)
    rows = [record(value, name=f"{i}.png") for i, value in enumerate([0.1, 0.2, 0.3])]
    result = ev.calibrate_records(rows, protocol)
    assert result["image_threshold"] == pytest.approx(0.3)
    assert result["pixel_threshold"] == pytest.approx(0.3)
    assert result["validation_images"] == 3 and result["validation_pixels"] == 12
    assert result["empirical_image_fpr"] == result["empirical_pixel_fpr"] == 0
    reverse = ev.calibrate_records(list(reversed(rows)), protocol)
    assert reverse["image_threshold"] == result["image_threshold"]
    assert reverse["pixel_threshold"] == result["pixel_threshold"]
    zeros = ev.calibrate_records([record(0)], protocol)
    metrics, predictions = ev.summarize_records([record(0, split="test")], zeros, protocol)
    assert predictions[0]["predicted_label"] == 0
    assert metrics["segmentation_micro"]["fp"] == 0
    assert metrics["segmentation_micro"]["dice"] is None


@pytest.mark.parametrize("change", [{"split": "test"}, {"label": 1}, {"source_split": "test"}, {"mask_path": "mask.png"}])
def test_calibration_refuses_test_anomalies_and_masks(change):
    row = record()
    row.update(change)
    with pytest.raises(ValueError, match="Calibration reservee"):
        ev.calibrate_records([row], ev.load_protocol(PROTOCOL))


def test_calibration_pools_only_valid_pixels():
    protocol = ev.load_protocol(PROTOCOL)
    row = record(0.1)
    row["error"][0, 0] = 1
    row["valid"][0, 0] = False
    result = ev.calibrate_records([row], protocol)
    assert result["pixel_threshold"] == pytest.approx(0.1)
    assert result["validation_pixels"] == 3


def test_auroc_ap_known_ranking_ties_and_single_class():
    values = ev.ranking_metrics(np.array([0, 0, 1, 1]), np.array([0.1, 0.4, 0.35, 0.8]))
    assert values["auroc"] == pytest.approx(0.75)
    assert values["ap"] == pytest.approx(5 / 6)
    ties = ev.ranking_metrics(np.array([0, 1, 0]), np.ones(3))
    assert ties["auroc"] == 0.5 and ties["ap"] == pytest.approx(1 / 3)
    assert ev.ranking_metrics(np.zeros(2), np.ones(2)) == {
        "auroc": None, "ap": None, "undefined_reason": "both_classes_required"}
    with pytest.raises(ValueError): ev.ranking_metrics(np.array([0, 1]), np.array([np.nan, 0]))
    with pytest.raises(ValueError): ev.ranking_metrics(np.array([0, 2]), np.ones(2))


def test_overlap_known_counts_and_empty_policy():
    result = ev.overlap_metrics(np.array([1, 1, 0, 0]), np.array([1, 0, 1, 0]))
    assert result == {"tp": 1, "fp": 1, "fn": 1, "dice": 0.5, "iou": 1 / 3}
    assert ev.overlap_metrics(np.zeros(3), np.zeros(3))["dice"] is None
    with pytest.raises(ValueError): ev.overlap_metrics(np.array([2]), np.array([1]))


def test_test_metrics_include_normal_false_positives_exclude_padding_and_flag_empty():
    protocol = ev.load_protocol(PROTOCOL)
    normal = record(0, split="test")
    normal["error"][0, 0] = 0.9  # FP compte.
    normal["error"][1, 0] = 1  # Padding ignore.
    normal["valid"][1, 0] = False
    anomaly = record(0, split="test", label=1, name="1.png")
    anomaly["mask"][0, 0] = True
    anomaly["error"][0, 0] = 0.8  # TP.
    empty = record(0, split="test", label=1, name="2.png")
    metrics, rows = ev.summarize_records([normal, anomaly, empty], {"image_threshold": 0.5, "pixel_threshold": 0.5}, protocol)
    assert metrics["segmentation_micro"] == {"tp": 1, "fp": 1, "fn": 0, "dice": 2 / 3, "iou": 0.5}
    assert metrics["valid_pixels"] == 11 and metrics["empty_anomalous_masks"] == 1
    assert metrics["dice_macro_anomalous"] == 1 and metrics["dice_macro_anomalous_n"] == 1
    assert metrics["image_decision"] == {"tn": 0, "tp": 1, "fp": 1, "fn": 1, "f1": 0.5, "positive_class": 1}
    assert rows[-1]["empty_anomalous_mask"] is True


def test_checkpoint_discovery_excludes_smoke_and_mlflow(synthetic):
    _, _, _, runs, _ = synthetic
    selected, excluded = ev.discover_checkpoints(runs)
    assert list(selected) == list(ev.CATEGORIES)
    assert sorted(row["reason"] for row in excluded) == ["mlflow_copy"] * 3 + ["smoke"]


def test_identical_canonical_copy_is_deduplicated_but_distinct_run_is_ambiguous(synthetic, tmp_path):
    runs = tmp_path / "runs"
    shutil.copytree(synthetic[3], runs)
    shutil.copytree(runs / "bottle/full_synthetic", runs / "bottle/full_duplicate")
    selected, excluded = ev.discover_checkpoints(runs)
    assert selected["bottle"]
    assert any(row["reason"] == "identical_checkpoint_copy" for row in excluded)
    write_run(runs, "bottle", selected["bottle"].manifest_sha256, name="full_distinct", seed=7)
    with pytest.raises(ValueError, match="Plusieurs runs complets"):
        ev.discover_checkpoints(runs)


def test_smoke_metadata_cannot_be_disguised_as_full(synthetic, tmp_path):
    runs = tmp_path / "runs"
    shutil.copytree(synthetic[3], runs)
    shutil.copytree(runs / "bottle/smoke_fake", runs / "bottle/full_disguised")
    _, excluded = ev.discover_checkpoints(runs)
    assert any(row["reason"] == "smoke_metadata" for row in excluded)


@pytest.mark.parametrize("mutation", ["checksum", "missing", "test_used", "epoch"])
def test_invalid_checkpoint_inventory_fails_closed(synthetic, tmp_path, mutation):
    runs = tmp_path / "runs"
    shutil.copytree(synthetic[3], runs)
    path = runs / "bottle/full_synthetic"
    summary = json.loads((path / "summary.json").read_text())
    if mutation == "checksum": (path / "best.pt").write_bytes(b"corrupt")
    elif mutation == "missing": (path / "best.pt").unlink()
    else:
        summary["test_used" if mutation == "test_used" else "best_epoch"] = True if mutation == "test_used" else 9
        (path / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError): ev.discover_checkpoints(runs)


@pytest.mark.parametrize("mutation", ["scope", "category", "shape", "nan"])
def test_checkpoint_payload_is_loaded_safely_and_strictly(synthetic, tmp_path, mutation):
    cp = synthetic[4]["bottle"]
    saved = torch.load(cp.path, weights_only=True, map_location="cpu")
    if mutation == "scope": saved["scope"] = "smoke"
    elif mutation == "category": saved["effective_config"]["category"] = "leather"
    elif mutation == "shape": saved["model_state_dict"].pop("encoder.0.0.weight")
    else: saved["model_state_dict"]["encoder.0.0.weight"].fill_(float("nan"))
    path = tmp_path / "best.pt"
    torch.save(saved, path)
    bad = replace(cp, path=str(path), sha256=ev._sha256(path))
    with pytest.raises((ValueError, RuntimeError)): ev.load_model(bad, torch.device("cpu"), cp.manifest_sha256)
    with pytest.raises(ValueError): ev.load_model(cp, torch.device("cpu"), "wrong-manifest")


def test_inspect_never_constructs_dataset(synthetic, monkeypatch, capsys):
    tmp, root, manifest, runs, _ = synthetic
    def forbidden(*args, **kwargs): raise AssertionError("Aucun Dataset pendant inspect")
    monkeypatch.setattr(ev, "MVTecDataset", forbidden)
    assert ev.main(["--stage", "inspect", "--protocol", str(PROTOCOL), "--runs-root", str(runs),
                    "--root", str(root), "--manifest", str(manifest), "--output-dir", str(tmp / "inspection")]) == 0
    assert json.loads(capsys.readouterr().out)["inference_executed"] is False


def test_missing_or_wrong_approval_blocks_before_any_dataset_access(synthetic, monkeypatch, tmp_path):
    cp = synthetic[4]["bottle"]
    def forbidden(*args, **kwargs): raise AssertionError("Test ouvert sans validation")
    monkeypatch.setattr(ev, "MVTecDataset", forbidden)
    for approved in (None, "stale-sha"):
        with pytest.raises(ValueError, match="validation du protocole"):
            ev.evaluate_category(cp, protocol_path=PROTOCOL, approved_sha256=approved, root=tmp_path / "absent",
                                 manifest=tmp_path / "absent.csv", output=tmp_path / "out", device=torch.device("cpu"))
    assert ev.main(["--stage", "evaluate"]) == 1


@pytest.fixture(scope="module")
def evaluated(synthetic):
    tmp, root, manifest, runs, selected = synthetic
    cp = selected["bottle"]
    before = snapshot(root), snapshot(manifest.parent), snapshot(runs)
    original_open = Image.open
    opened = []
    def guarded_open(path, *args, **kwargs):
        relative = Path(path).relative_to(root).as_posix()
        assert relative.startswith("bottle/train/good/")
        assert "/test/" not in relative and "/ground_truth/" not in relative
        opened.append(relative)
        return original_open(path, *args, **kwargs)
    outputs, reports, calibrations = [], [], []
    for name in ("first", "second"):
        output = tmp / name
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Image, "open", guarded_open)
            calibrations.append(ev.calibrate_category(cp, protocol_path=PROTOCOL, root=root, manifest=manifest,
                                                     output=output, device=torch.device("cpu")))
        reports.append(ev.evaluate_category(cp, protocol_path=PROTOCOL, approved_sha256=ev._sha256(PROTOCOL),
                                           root=root, manifest=manifest, output=output, device=torch.device("cpu")))
        outputs.append(output)
    assert before == (snapshot(root), snapshot(manifest.parent), snapshot(runs))
    assert len(opened) == 4
    return outputs, reports, calibrations


def test_synthetic_e2e_reproduces_calibration_predictions_metrics_and_figures(evaluated):
    outputs, reports, calibrations = evaluated
    assert reports[0] == reports[1] and calibrations[0] == calibrations[1]
    assert calibrations[0]["validation_images"] == 2
    assert reports[0]["metrics"]["images"] == 2
    for name in ("calibration.json", "calibration.sha256", "calibration_scores.csv", "predictions.csv", "metrics.json"):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()
    assert len(reports[0]["figures"]) == 2
    for name in reports[0]["figures"]:
        assert (outputs[0] / "figures" / name).read_bytes() == (outputs[1] / "figures" / name).read_bytes()
        with Image.open(outputs[0] / "figures" / name) as figure:
            assert figure.size == (1440, 408)


@pytest.mark.parametrize("mutation", ["protocol_sha256", "manifest_sha256", "checkpoint_sha256", "dataset_code_sha256", "evaluation_code_sha256", "category", "normal_only", "threshold"])
def test_stale_or_invalid_calibration_blocks_before_inference(synthetic, evaluated, tmp_path, monkeypatch, mutation):
    calibration = dict(evaluated[2][0])
    if mutation == "threshold": calibration["pixel_threshold"] = 2.0
    elif mutation == "normal_only": calibration[mutation] = False
    else: calibration[mutation] = "modified"
    (tmp_path / "calibration.json").write_text(json.dumps(calibration))
    (tmp_path / "calibration.sha256").write_text(ev._sha256(tmp_path / "calibration.json"))
    def forbidden(*args, **kwargs): raise AssertionError("Inference avec calibration invalide")
    monkeypatch.setattr(ev, "infer_records", forbidden)
    with pytest.raises(ValueError):
        ev.evaluate_category(synthetic[4]["bottle"], protocol_path=PROTOCOL, approved_sha256=ev._sha256(PROTOCOL),
                             root=synthetic[1], manifest=synthetic[2], output=tmp_path, device=torch.device("cpu"))


def test_inference_preserves_weights_buffers_and_gradients(synthetic):
    cp = synthetic[4]["bottle"]
    model = ev.load_model(cp, torch.device("cpu"), cp.manifest_sha256)
    before = {key: value.clone() for key, value in model.state_dict().items()}
    records = ev.infer_records(model, synthetic[2], synthetic[1], "bottle", "val", ev.load_protocol(PROTOCOL), torch.device("cpu"))
    assert len(records) == 2 and not model.training
    assert all(not parameter.requires_grad and parameter.grad is None for parameter in model.parameters())
    assert all(torch.equal(value, model.state_dict()[key]) for key, value in before.items())


def test_modified_calibration_digest_blocks_before_inference(synthetic, evaluated, tmp_path, monkeypatch):
    (tmp_path / "calibration.json").write_bytes((evaluated[0][0] / "calibration.json").read_bytes() + b" ")
    (tmp_path / "calibration.sha256").write_bytes((evaluated[0][0] / "calibration.sha256").read_bytes())
    def forbidden(*args, **kwargs): raise AssertionError("Inference apres modification de calibration")
    monkeypatch.setattr(ev, "infer_records", forbidden)
    with pytest.raises(ValueError, match="empreinte invalide"):
        ev.evaluate_category(synthetic[4]["bottle"], protocol_path=PROTOCOL, approved_sha256=ev._sha256(PROTOCOL),
                             root=synthetic[1], manifest=synthetic[2], output=tmp_path, device=torch.device("cpu"))


def test_synthetic_cli_generates_reports_for_all_three_categories(synthetic, capsys):
    tmp, root, manifest, runs, _ = synthetic
    output = tmp / "all_categories"
    args = ["--protocol", str(PROTOCOL), "--runs-root", str(runs), "--root", str(root),
            "--manifest", str(manifest), "--output-dir", str(output), "--device", "cpu"]
    assert ev.main([*args, "--stage", "calibrate"]) == 0
    assert ev.main([*args, "--stage", "evaluate", "--approved-protocol-sha256", ev._sha256(PROTOCOL)]) == 0
    destination = output / ev._sha256(PROTOCOL)[:12]
    for category in ev.CATEGORIES:
        report = json.loads((destination / category / "metrics.json").read_text())
        assert report["category"] == category and report["metrics"]["images"] == 2
        assert len(report["figures"]) == 2
    macro = json.loads((destination / "macro_metrics.json").read_text())
    assert all(value["categories"] == 3 for value in macro.values())
    assert (destination / "category_metrics.csv").read_text().count("\n") == 4
    capsys.readouterr()


def test_outputs_cannot_modify_data_manifests_checkpoints_or_existing_results(synthetic, tmp_path):
    _, root, manifest, runs, _ = synthetic
    for output in (root / "out", manifest.parent / "out", runs / "out"):
        with pytest.raises(ValueError): ev._safe_output(output, root, manifest, runs)
    target = tmp_path / "result.json"
    ev._write_once(target, b"original")
    stat = target.stat().st_mtime_ns
    ev._write_once(target, b"original")
    assert target.stat().st_mtime_ns == stat
    with pytest.raises(ValueError): ev._write_once(target, b"different")
    assert target.read_bytes() == b"original"


@pytest.mark.parametrize("key,value", [("smoothing", "gaussian"), ("resolution", [128, 128]),
                                      ("image_top_fraction", float("nan")), ("batch_size", 0),
                                      ("seed", True), ("decision", "greater_equal")])
def test_protocol_validation_rejects_unsupported_or_invalid_choices(tmp_path, key, value):
    protocol = ev.load_protocol(PROTOCOL)
    protocol[key] = value
    path = tmp_path / "protocol.yaml"
    path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    with pytest.raises(ValueError): ev.load_protocol(path)


def test_evaluation_outputs_are_ignored_by_git():
    import subprocess
    result = subprocess.run(["git", "check-ignore", "--no-index", "reports/evaluation/b0/synthetic/figures/image.png",
                             "reports/evaluation/b0/synthetic/metrics.json"], cwd=PROJECT, capture_output=True, text=True, check=True)
    assert len(result.stdout.splitlines()) == 2
