"""Evaluation A1 : uniquement donnees/checkpoints synthetiques, sans entrainement."""

from copy import deepcopy
import json
import os
from pathlib import Path
import random
import subprocess

import numpy as np
from PIL import Image
import pytest
import torch
import yaml

from resilientinspect.data.prepare import prepare_dataset, write_manifests
from resilientinspect.evaluation import evaluate_a1 as ev
from resilientinspect.evaluation import evaluate_ae as shared
from test_a1_checkpoints import write_run
from test_prepare import make_dataset, snapshot

PROJECT = Path(__file__).resolve().parents[1]
PROTOCOL = PROJECT / "configs/evaluate_ae_b0.yaml"
CPU = torch.device("cpu")


def directory_link(link, target):
    """Lien temporaire, avec jonction Windows si les symlinks sont interdits."""
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        if os.name != "nt" or not (isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in (5, 1314)):
            pytest.skip(f"Creation de liens symboliques indisponible : {exc}")
        try:
            subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=True)
        except subprocess.CalledProcessError as junction_exc:
            pytest.skip(f"Creation de jonctions Windows indisponible : {junction_exc.stderr!r}")


@pytest.fixture(scope="module", autouse=True)
def restore_process_state():
    threads = torch.get_num_threads()
    deterministic = torch.are_deterministic_algorithms_enabled()
    benchmark, cudnn = torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic
    precision = torch.get_float32_matmul_precision()
    python_state, numpy_state = random.getstate(), np.random.get_state()
    environment = {key: os.environ.get(key) for key in ("MPLCONFIGDIR", "CUBLAS_WORKSPACE_CONFIG")}
    with torch.random.fork_rng(devices=[]):
        torch.set_num_threads(2)
        yield
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(deterministic)
    torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic = benchmark, cudnn
    torch.set_float32_matmul_precision(precision)
    random.setstate(python_state)
    np.random.set_state(numpy_state)
    for key, value in environment.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    temporary = tmp_path_factory.mktemp("a1_evaluation")
    root = make_dataset(temporary / "raw")
    rows, report = prepare_dataset(root)
    write_manifests(rows, report, temporary / "manifests")
    manifest = temporary / "manifests/manifest.csv"
    runs = temporary / "runs"
    for category in shared.CATEGORIES:
        write_run(runs, category, shared.manifest_digest(manifest))
    selected, _ = ev.discover_checkpoints(runs)
    return temporary, root, manifest, runs, selected


def test_a1_uses_b0_scientific_module_and_exact_frozen_protocol():
    assert ev.shared is shared
    protocol = ev.load_protocol(PROTOCOL)
    assert protocol == shared.load_protocol(PROTOCOL)
    assert protocol["anomaly_map"] == "rgb_mean_absolute_error"
    assert protocol["smoothing"] == "none" and protocol["resolution"] == [256, 256]
    assert protocol["image_top_fraction"] == 0.01
    assert protocol["image_threshold_quantile"] == 0.95
    assert protocol["pixel_threshold_quantile"] == 0.995
    assert protocol["quantile_method"] == "higher"
    assert protocol["decision"] == "strictly_greater"


@pytest.mark.parametrize("key,value", [
    ("image_top_fraction", 0.02), ("image_threshold_quantile", 0.9),
    ("pixel_threshold_quantile", 0.99), ("smoothing", "gaussian"),
    ("resolution", [128, 128]), ("padding", "include"),
    ("decision", "greater_equal"), ("quantile_method", "linear"),
    ("seed", 7), ("batch_size", 2), ("cpu_threads", 1), ("figures_per_defect", 2),
])
def test_a1_refuses_changes_to_frozen_b0_protocol(tmp_path, key, value):
    protocol = shared.load_protocol(PROTOCOL)
    protocol[key] = value
    path = tmp_path / "protocol.yaml"
    path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    with pytest.raises(ValueError):
        ev.load_protocol(path)


def test_inspect_never_constructs_dataset_or_runs_inference(synthetic, monkeypatch, capsys):
    temporary, root, manifest, runs, _ = synthetic

    def forbidden(*args, **kwargs):
        raise AssertionError("Inspect ne doit ouvrir aucun Dataset ou image")

    monkeypatch.setattr(shared, "MVTecDataset", forbidden)
    monkeypatch.setattr(shared, "infer_records", forbidden)
    monkeypatch.setattr(Image, "open", forbidden)
    output = temporary / "inspection"
    assert ev.main(["--stage", "inspect", "--protocol", str(PROTOCOL), "--runs-root", str(runs),
                    "--root", str(root), "--manifest", str(manifest), "--output-dir", str(output)]) == 0
    inventory = json.loads((output / shared._sha256(PROTOCOL)[:12] / "checkpoint_inventory.json").read_text(encoding="utf-8"))
    assert inventory["inference_executed"] is False and inventory["test_executed"] is False
    assert set(inventory["selected"]) == set(shared.CATEGORIES)
    capsys.readouterr()


def test_unapproved_test_is_blocked_before_manifest_checkpoint_or_dataset_access(synthetic, tmp_path, monkeypatch, capsys):
    checkpoint = synthetic[4]["bottle"]

    def forbidden(*args, **kwargs):
        raise AssertionError("Acces avant validation du protocole")

    monkeypatch.setattr(shared, "MVTecDataset", forbidden)
    monkeypatch.setattr(shared, "infer_records", forbidden)
    monkeypatch.setattr(ev, "discover_checkpoints", forbidden)
    for approval in (None, "wrong-sha"):
        with pytest.raises(ValueError, match="validation du protocole"):
            ev.evaluate_category(checkpoint, protocol_path=PROTOCOL, approved_sha256=approval,
                                 root=tmp_path / "absent", manifest=tmp_path / "absent.csv",
                                 output=tmp_path / "output", device=CPU)
        args = ["--stage", "evaluate", "--manifest", str(tmp_path / "absent.csv")]
        if approval is not None:
            args.extend(["--approved-protocol-sha256", approval])
        assert ev.main(args) == 1
    capsys.readouterr()


@pytest.fixture(scope="module")
def evaluated(synthetic):
    temporary, root, manifest, runs, selected = synthetic
    checkpoint = selected["bottle"]
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
        output = temporary / name
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Image, "open", guarded_open)
            calibrations.append(ev.calibrate_category(checkpoint, protocol_path=PROTOCOL, root=root,
                                                     manifest=manifest, output=output, device=CPU))
        reports.append(ev.evaluate_category(checkpoint, protocol_path=PROTOCOL,
                                           approved_sha256=shared._sha256(PROTOCOL), root=root,
                                           manifest=manifest, output=output, device=CPU))
        outputs.append(output)
    assert before == (snapshot(root), snapshot(manifest.parent), snapshot(runs))
    assert len(opened) == 4 and len(set(opened)) == 2
    return outputs, reports, calibrations


def test_cpu_reproduces_calibration_predictions_metrics_and_figures(evaluated):
    outputs, reports, calibrations = evaluated
    assert reports[0] == reports[1] and calibrations[0] == calibrations[1]
    assert calibrations[0]["variant"] == reports[0]["variant"] == "A1"
    assert calibrations[0]["validation_images"] == 2
    assert reports[0]["metrics"]["images"] == 2
    for name in ("calibration.json", "calibration.sha256", "calibration_scores.csv", "predictions.csv", "predictions.json", "metrics.json"):
        assert (outputs[0] / name).read_bytes() == (outputs[1] / name).read_bytes()
    assert len(reports[0]["figures"]) == 2
    for name in reports[0]["figures"]:
        assert (outputs[0] / "figures" / name).read_bytes() == (outputs[1] / "figures" / name).read_bytes()
        with Image.open(outputs[0] / "figures" / name) as figure:
            assert figure.width > figure.height


def test_calibration_recalculates_quantiles_from_a1_validation_scores(synthetic, evaluated):
    checkpoint = synthetic[4]["bottle"]
    model = ev.load_model(checkpoint, CPU, checkpoint.manifest_sha256)
    records = shared.infer_records(model, synthetic[2], synthetic[1], "bottle", "val", ev.load_protocol(PROTOCOL), CPU)
    calibration = evaluated[2][0]
    expected = shared.calibrate_records(records, ev.load_protocol(PROTOCOL))
    for key, value in expected.items():
        assert calibration[key] == value
    assert calibration["calibration_split"] == "val" and calibration["normal_only"] is True
    assert calibration["checkpoint_sha256"] == checkpoint.sha256


@pytest.mark.parametrize("mutation", [
    "protocol_sha256", "manifest_sha256", "checkpoint_sha256", "dataset_code_sha256",
    "evaluation_code_sha256", "shared_evaluation_code_sha256", "loader_code_sha256",
    "checkpoint_validation_code_sha256", "preparation_code_sha256", "model_code_sha256",
    "category", "normal_only", "variant", "threshold", "environment", "checkpoint", "protocol",
])
def test_incompatible_calibration_fails_before_any_test_inference(synthetic, evaluated, tmp_path, monkeypatch, mutation):
    calibration = deepcopy(evaluated[2][0])
    if mutation == "threshold":
        calibration["pixel_threshold"] = 2.0
    elif mutation == "normal_only":
        calibration[mutation] = False
    elif mutation == "variant":
        calibration[mutation] = "B0"
    elif mutation == "environment":
        calibration[mutation]["torch"] = "changed-version"
    elif mutation == "checkpoint":
        calibration[mutation]["sha256"] = "changed-checkpoint"
    else:
        calibration[mutation] = "modified"
    (tmp_path / "calibration.json").write_text(json.dumps(calibration), encoding="utf-8")
    (tmp_path / "calibration.sha256").write_text(shared._sha256(tmp_path / "calibration.json"), encoding="ascii")

    def forbidden(*args, **kwargs):
        raise AssertionError("Test ouvert avec une calibration incompatible")

    monkeypatch.setattr(shared, "infer_records", forbidden)
    monkeypatch.setattr(shared, "MVTecDataset", forbidden)
    with pytest.raises(ValueError):
        ev.evaluate_category(synthetic[4]["bottle"], protocol_path=PROTOCOL,
                             approved_sha256=shared._sha256(PROTOCOL), root=synthetic[1],
                             manifest=synthetic[2], output=tmp_path, device=CPU)


def test_changed_calibration_digest_fails_before_inference(synthetic, evaluated, tmp_path, monkeypatch):
    source = evaluated[0][0]
    (tmp_path / "calibration.json").write_bytes((source / "calibration.json").read_bytes() + b" ")
    (tmp_path / "calibration.sha256").write_bytes((source / "calibration.sha256").read_bytes())

    def forbidden(*args, **kwargs):
        raise AssertionError("Inference apres modification calibration")

    monkeypatch.setattr(shared, "infer_records", forbidden)
    with pytest.raises(ValueError):
        ev.evaluate_category(synthetic[4]["bottle"], protocol_path=PROTOCOL,
                             approved_sha256=shared._sha256(PROTOCOL), root=synthetic[1],
                             manifest=synthetic[2], output=tmp_path, device=CPU)


def test_a1_inference_preserves_weights_buffers_and_gradients(synthetic):
    checkpoint = synthetic[4]["bottle"]
    model = ev.load_model(checkpoint, CPU, checkpoint.manifest_sha256)
    before = {key: value.clone() for key, value in model.state_dict().items()}
    records = shared.infer_records(model, synthetic[2], synthetic[1], "bottle", "val", ev.load_protocol(PROTOCOL), CPU)
    assert len(records) == 2 and not model.training
    assert all(not parameter.requires_grad and parameter.grad is None for parameter in model.parameters())
    assert all(torch.equal(value, model.state_dict()[key]) for key, value in before.items())


def test_output_cannot_target_b0_or_overwrite_existing_result(synthetic, evaluated):
    checkpoint = synthetic[4]["bottle"]

    def forbidden(*args, **kwargs):
        raise AssertionError("Inference avant validation du repertoire de sortie")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(shared, "infer_records", forbidden)
        for output in (PROJECT / "reports/evaluation/b0/forbidden", PROJECT / "artifacts/b0_runs/forbidden",
                       synthetic[1] / "out", synthetic[2].parent / "out", synthetic[3] / "out"):
            with pytest.raises(ValueError):
                ev.calibrate_category(checkpoint, protocol_path=PROTOCOL, root=synthetic[1],
                                      manifest=synthetic[2], output=output, device=CPU)
    result = evaluated[0][0] / "metrics.json"
    original = result.read_bytes()
    mtime = result.stat().st_mtime_ns
    shared._write_once(result, original)
    assert result.stat().st_mtime_ns == mtime
    with pytest.raises(ValueError):
        shared._write_once(result, b"changed")
    assert result.read_bytes() == original


@pytest.mark.parametrize("target_index", [1, 3])
def test_inspect_refuses_symlink_destination_into_data_or_checkpoints(synthetic, tmp_path, capsys, target_index):
    _, root, manifest, runs, _ = synthetic
    target = synthetic[target_index]
    before = snapshot(target)
    output = tmp_path / "output"
    output.mkdir()
    destination = output / shared._sha256(PROTOCOL)[:12]
    directory_link(destination, target)
    assert ev.main(["--stage", "inspect", "--protocol", str(PROTOCOL), "--runs-root", str(runs),
                    "--root", str(root), "--manifest", str(manifest), "--output-dir", str(output)]) == 1
    assert snapshot(target) == before
    assert not (target / "checkpoint_inventory.json").exists()
    capsys.readouterr()


def test_evaluate_refuses_figures_link_into_data_before_inference(synthetic, tmp_path, monkeypatch):
    _, root, manifest, _, selected = synthetic
    checkpoint = selected["bottle"]
    output = tmp_path / "output"
    ev.calibrate_category(checkpoint, protocol_path=PROTOCOL, root=root, manifest=manifest, output=output, device=CPU)
    before = snapshot(root)
    directory_link(output / "figures", root)

    def forbidden(*args, **kwargs):
        raise AssertionError("Inference avant validation du repertoire des figures")

    monkeypatch.setattr(shared, "infer_records", forbidden)
    with pytest.raises(ValueError):
        ev.evaluate_category(checkpoint, protocol_path=PROTOCOL, approved_sha256=shared._sha256(PROTOCOL),
                             root=root, manifest=manifest, output=output, device=CPU)
    assert snapshot(root) == before


def test_three_category_cli_produces_derived_reports(synthetic, capsys):
    temporary, root, manifest, runs, _ = synthetic
    output = temporary / "all_categories"
    args = ["--protocol", str(PROTOCOL), "--runs-root", str(runs), "--root", str(root),
            "--manifest", str(manifest), "--output-dir", str(output), "--device", "cpu"]
    assert ev.main([*args, "--stage", "calibrate"]) == 0
    assert ev.main([*args, "--stage", "evaluate", "--approved-protocol-sha256", shared._sha256(PROTOCOL)]) == 0
    destination = output / shared._sha256(PROTOCOL)[:12]
    for category in shared.CATEGORIES:
        report = json.loads((destination / category / "metrics.json").read_text(encoding="utf-8"))
        assert report["variant"] == "A1" and report["category"] == category
        assert report["metrics"]["images"] == 2 and len(report["figures"]) == 2
    macro = json.loads((destination / "macro_metrics.json").read_text(encoding="utf-8"))
    assert all(value["categories"] == 3 for value in macro.values())
    assert (destination / "category_metrics.csv").read_text(encoding="utf-8").count("\n") == 4
    capsys.readouterr()
