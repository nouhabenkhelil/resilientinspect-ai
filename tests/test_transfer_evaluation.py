"""Evaluation externe uniquement sur faux dataset/checkpoints temporaires, sans apprentissage."""

from copy import deepcopy
from importlib.metadata import version
import json
import os
from pathlib import Path
import random
import shutil
import sys

import numpy as np
from PIL import Image
import pytest
import torch
import yaml

from resilientinspect.data.prepare import prepare_dataset, write_manifests
from resilientinspect.data import synthetic
from resilientinspect.evaluation import evaluate_transfer as ev
from resilientinspect.models import transfer
from resilientinspect.training import train_transfer
from test_prepare import make_dataset, snapshot

PROJECT = Path(__file__).resolve().parents[1]
PROTOCOL = PROJECT / "configs/evaluate_transfer.yaml"
CPU = torch.device("cpu")


@pytest.fixture(scope="module", autouse=True)
def process_state():
    threads = torch.get_num_threads()
    deterministic = torch.are_deterministic_algorithms_enabled()
    benchmark, cudnn = torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic
    precision = torch.get_float32_matmul_precision()
    python_state, numpy_state = random.getstate(), np.random.get_state()
    environment = {name: os.environ.get(name) for name in ("MPLCONFIGDIR", "CUBLAS_WORKSPACE_CONFIG")}
    with torch.random.fork_rng(devices=[]):
        torch.set_num_threads(2)
        yield
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(deterministic)
    torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic = benchmark, cudnn
    torch.set_float32_matmul_precision(precision)
    random.setstate(python_state)
    np.random.set_state(numpy_state)
    for name, value in environment.items():
        if value is None: os.environ.pop(name, None)
        else: os.environ[name] = value


def write_json(path, data):
    path.write_bytes(ev.shared._json_bytes(data))


@pytest.fixture(scope="module")
def synthetic_run(tmp_path_factory):
    """Metadata full fabriquee pour l'API, poids T0 aleatoires sans entrainement."""
    temporary = tmp_path_factory.mktemp("transfer_evaluation_synthetic")
    root = make_dataset(temporary / "raw")
    rows, preparation = prepare_dataset(root)
    write_manifests(rows, preparation, temporary / "manifests")
    manifest = temporary / "manifests/manifest.csv"
    digest = ev.shared.manifest_digest(manifest)
    run = temporary / "full_synthetic_fixture"
    run.mkdir()
    config = synthetic.load_synthetic_config(PROJECT / "configs/synthetic_transfer.yaml")
    plan = synthetic.prepare_synthetic_plan(manifest, config, 42)
    synthetic.write_synthetic_plan(plan, run / "synthetic_plan.json")
    plan_digest = ev._sha256(run / "synthetic_plan.json")
    effective = train_transfer.load_config(PROJECT / "configs/train_t0.yaml")
    effective.update(category="bottle", seed=42, scope="full", device="cpu", max_batches_per_split=None,
                     normalization=config["normalization"], image_size=[256, 256])
    effective_path = run / "effective_config.yaml"
    effective_path.write_text(yaml.safe_dump(effective), encoding="utf-8")
    model = transfer.build_transfer_model("T0", seed=42)
    torch.save({"variant": "T0", "category": "bottle", "seed": 42, "scope": "full", "epoch": 1,
                "val_loss": 0.7, "model_state_dict": model.state_dict(), "effective_config": effective,
                "weight_provenance": model.weight_provenance, "manifest_sha256": digest,
                "synthetic_plan_sha256": plan_digest}, run / "best.pt")
    environment = {"python": sys.version.split()[0], "torch": str(torch.__version__), "numpy": np.__version__,
                   "torchvision": version("torchvision"), "scikit_learn": version("scikit-learn"), "device": "cpu"}
    write_json(run / "environment.json", environment)
    dataset = synthetic.SyntheticAnomalyDataset(manifest, root, category="bottle", split="val",
                                               config=config, seed=42, plan=plan)
    loader = ev.DataLoader(dataset, batch_size=4, shuffle=False, num_workers=0)
    scores = train_transfer.run_epoch(model, loader, CPU)["predictions"]
    threshold = float(np.quantile([row["score"] for row in scores if row["label"] == 0], 0.95, method="higher"))
    source_paths = [PROJECT / "configs/train_t0.yaml", PROJECT / "configs/synthetic_transfer.yaml",
                    Path(train_transfer.__file__), Path(transfer.__file__), Path(synthetic.__file__),
                    PROJECT / "src/data/dataset.py", PROJECT / "src/data/prepare.py", PROJECT / "src/data/audit.py",
                    PROJECT / "src/training/train_ae.py", Path(ev.shared.__file__), PROJECT / "pyproject.toml"]
    (run / "source").mkdir()
    source_hashes = {}
    for path in source_paths:
        (run / "source" / path.name).write_bytes(path.read_bytes())
        source_hashes["/kaggle/working/project/" + path.name] = ev._sha256(path)
    write_json(run / "provenance.json", {"source_sha256": source_hashes, "manifest_sha256": digest,
                                         "synthetic_plan_sha256": plan_digest,
                                         "weight_provenance": model.weight_provenance})
    calibration = {"variant": "T0", "category": "bottle", "seed": 42, "scope": "full",
                   "calibration_split": "val_synthetic", "normal_only": True, "method": "normal_quantile",
                   "quantile": 0.95, "quantile_method": "higher", "decision": "strictly_greater",
                   "checkpoint_sha256": ev._sha256(run / "best.pt"), "manifest_sha256": digest,
                   "synthetic_plan_sha256": plan_digest, "effective_config_sha256": ev._sha256(effective_path),
                   "train_code_sha256": ev._sha256(Path(train_transfer.__file__)),
                   "model_code_sha256": ev._sha256(Path(transfer.__file__)),
                   "synthetic_code_sha256": ev._sha256(Path(synthetic.__file__)),
                   "shared_evaluation_code_sha256": ev._sha256(Path(ev.shared.__file__)),
                   "dataset_code_sha256": ev._sha256(PROJECT / "src/data/dataset.py"),
                   "normalization": config["normalization"], "image_size": [256, 256], "environment": environment,
                   "validation_scores": scores, "image_threshold": threshold,
                   "validation_normal_images": len(scores) // 2, "validation_images": len(scores)}
    write_json(run / "calibration.json", calibration)
    calibration_digest = ev._sha256(run / "calibration.json")
    (run / "calibration.sha256").write_text(calibration_digest + "\n", encoding="ascii")
    write_json(run / "summary.json", {"status": "completed", "variant": "T0", "category": "bottle", "seed": 42,
                                     "scope": "full", "best_epoch": 1, "best_val_loss": 0.7,
                                     "test_used": False, "selection_split": "val_synthetic",
                                     "checkpoint_sha256": ev._sha256(run / "best.pt"),
                                     "manifest_sha256": digest, "synthetic_plan_sha256": plan_digest,
                                     "calibration_sha256": calibration_digest, "source_sha256": source_hashes})
    return temporary, root, manifest, run


@pytest.fixture
def copied_run(synthetic_run, tmp_path):
    run = tmp_path / "run"
    shutil.copytree(synthetic_run[3], run)
    return run


def rewrite_calibration(run, calibration):
    """Maintient l'enveloppe SHA afin de tester le contenu, pas juste le checksum."""
    write_json(run / "calibration.json", calibration)
    digest = ev._sha256(run / "calibration.json")
    (run / "calibration.sha256").write_text(digest + "\n", encoding="ascii")
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    summary["calibration_sha256"] = digest
    write_json(run / "summary.json", summary)


def test_protocol_is_strict_and_image_only():
    protocol = ev.load_protocol(PROTOCOL)
    assert protocol["image_size"] == [256, 256]
    assert protocol["pixel_metrics"] is False
    assert protocol["score"] == "sigmoid_anomaly_logit"
    assert protocol["calibration_split"] == "val_synthetic_normal"
    assert protocol["threshold_quantile"] == 0.95 and protocol["decision"] == "strictly_greater"


@pytest.mark.parametrize("key,value", [
    ("image_size", [224, 224]), ("pixel_metrics", True), ("threshold_quantile", 0.9),
    ("calibration_split", "test"), ("decision", "greater_equal"), ("batch_size", 8),
])
def test_protocol_changes_are_rejected(tmp_path, key, value):
    protocol = ev.load_protocol(PROTOCOL)
    protocol[key] = value
    path = tmp_path / "changed.yaml"
    path.write_text(yaml.safe_dump(protocol), encoding="utf-8")
    with pytest.raises(ValueError): ev.load_protocol(path)


@pytest.mark.parametrize("approval", [None, "wrong-sha"])
def test_unapproved_test_refused_before_any_run_manifest_or_dataset_access(tmp_path, monkeypatch, capsys, approval):
    def forbidden(*args, **kwargs): raise AssertionError("Acces avant validation explicite")
    monkeypatch.setattr(ev, "inspect_run", forbidden)
    monkeypatch.setattr(ev, "MVTecDataset", forbidden)
    monkeypatch.setattr(Image, "open", forbidden)
    with pytest.raises(ValueError, match="validation du protocole"):
        ev.evaluate_run(tmp_path / "missing", protocol_path=PROTOCOL, approved_sha256=approval,
                        manifest=tmp_path / "missing.csv", root=tmp_path / "missing_root",
                        output=tmp_path / "out", device=CPU)
    args = ["--stage", "evaluate", "--run-dir", str(tmp_path / "missing")]
    if approval: args.extend(["--approved-protocol-sha256", approval])
    assert ev.main(args) == 1
    capsys.readouterr()


def test_inspection_only_loads_metadata_and_weights(synthetic_run, monkeypatch, capsys):
    def forbidden(*args, **kwargs): raise AssertionError("Inspect ne doit construire Dataset ou faire inference")
    monkeypatch.setattr(ev, "MVTecDataset", forbidden)
    monkeypatch.setattr(synthetic, "SyntheticAnomalyDataset", forbidden)
    monkeypatch.setattr(Image, "open", forbidden)
    monkeypatch.setattr(transfer.TransferClassifier, "forward", forbidden)
    metadata = ev.inspect_run(synthetic_run[3], synthetic_run[2])
    assert metadata["inference_executed"] is metadata["test_executed"] is False
    assert metadata["image_threshold"] == ev._json(synthetic_run[3] / "calibration.json")["image_threshold"]
    assert ev.main(["--stage", "inspect", "--run-dir", str(synthetic_run[3]),
                    "--manifest", str(synthetic_run[2])]) == 0
    capsys.readouterr()


def test_smoke_cannot_be_evaluated_as_full(synthetic_run, copied_run, monkeypatch):
    summary = json.loads((copied_run / "summary.json").read_text(encoding="utf-8"))
    summary["scope"] = "smoke"
    write_json(copied_run / "summary.json", summary)
    def forbidden(*args, **kwargs): raise AssertionError("Dataset construit pour un smoke")
    monkeypatch.setattr(ev, "MVTecDataset", forbidden)
    with pytest.raises(ValueError, match="full"):
        ev.inspect_run(copied_run, synthetic_run[2])


@pytest.mark.parametrize("mutation", [
    "train_code_sha256", "model_code_sha256", "synthetic_code_sha256", "shared_evaluation_code_sha256",
    "dataset_code_sha256", "manifest_sha256", "normal_only", "quantile", "environment", "normalization",
    "threshold", "incomplete_scores", "source_path", "test_score", "score_nan", "label",
])
def test_stale_or_invalid_calibration_refused_before_dataset(synthetic_run, copied_run, monkeypatch, mutation):
    calibration = json.loads((copied_run / "calibration.json").read_text(encoding="utf-8"))
    if mutation == "normal_only": calibration[mutation] = False
    elif mutation == "quantile": calibration[mutation] = 0.99
    elif mutation == "environment": calibration[mutation]["torch"] = "stale"
    elif mutation == "normalization": calibration[mutation]["mean"] = [0., 0., 0.]
    elif mutation == "threshold": calibration["image_threshold"] = 0.8  # anomalous scores must not calibrate threshold.
    elif mutation == "incomplete_scores": calibration["validation_scores"].pop()
    elif mutation == "source_path": calibration["validation_scores"][0]["image_path"] = "bottle/test/good/000.png"
    elif mutation == "test_score": calibration["validation_scores"][0]["split"] = "test"
    elif mutation == "score_nan": calibration["validation_scores"][0]["score"] = -1.0
    elif mutation == "label": calibration["validation_scores"][0]["label"] ^= 1
    else: calibration[mutation] = "stale"
    rewrite_calibration(copied_run, calibration)
    def forbidden(*args, **kwargs): raise AssertionError("Dataset ouvert avec calibration perimee")
    monkeypatch.setattr(ev, "MVTecDataset", forbidden)
    with pytest.raises(ValueError):
        ev.evaluate_run(copied_run, protocol_path=PROTOCOL, approved_sha256=ev._sha256(PROTOCOL),
                        manifest=synthetic_run[2], root=synthetic_run[1], output=copied_run.parent / "out", device=CPU)


def test_modified_calibration_hash_is_rejected(synthetic_run, copied_run):
    path = copied_run / "calibration.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Calibration modifiee"):
        ev.inspect_run(copied_run, synthetic_run[2])


def test_pretrained_provenance_cannot_replace_t0_random_origin(synthetic_run, copied_run):
    payload = torch.load(copied_run / "best.pt", map_location="cpu", weights_only=True)
    payload["weight_provenance"]["source"] = "imagenet"
    torch.save(payload, copied_run / "best.pt")
    digest = ev._sha256(copied_run / "best.pt")
    summary = json.loads((copied_run / "summary.json").read_text(encoding="utf-8"))
    summary["checkpoint_sha256"] = digest
    write_json(copied_run / "summary.json", summary)
    calibration = json.loads((copied_run / "calibration.json").read_text(encoding="utf-8"))
    calibration["checkpoint_sha256"] = digest
    rewrite_calibration(copied_run, calibration)
    with pytest.raises(ValueError, match="Provenance"):
        ev.inspect_run(copied_run, synthetic_run[2])


def test_inconsistent_effective_normalization_refused_even_with_consistent_hashes(synthetic_run, copied_run):
    payload = torch.load(copied_run / "best.pt", map_location="cpu", weights_only=True)
    effective = deepcopy(payload["effective_config"])
    effective["normalization"]["mean"] = [0., 0., 0.]
    payload["effective_config"] = effective
    torch.save(payload, copied_run / "best.pt")
    (copied_run / "effective_config.yaml").write_text(yaml.safe_dump(effective), encoding="utf-8")
    checkpoint_digest = ev._sha256(copied_run / "best.pt")
    summary = json.loads((copied_run / "summary.json").read_text(encoding="utf-8"))
    summary["checkpoint_sha256"] = checkpoint_digest
    write_json(copied_run / "summary.json", summary)
    calibration = json.loads((copied_run / "calibration.json").read_text(encoding="utf-8"))
    calibration.update(checkpoint_sha256=checkpoint_digest, effective_config_sha256=ev._sha256(copied_run / "effective_config.yaml"),
                       normalization=effective["normalization"])
    rewrite_calibration(copied_run, calibration)
    with pytest.raises(ValueError): ev.inspect_run(copied_run, synthetic_run[2])


def test_approved_evaluation_on_fake_dataset_never_opens_masks_and_is_reproducible(synthetic_run, tmp_path, monkeypatch):
    _, root, manifest, run = synthetic_run
    before = snapshot(root), snapshot(manifest.parent), snapshot(run)
    opened = []
    original_open = Image.open
    def guarded_open(path, *args, **kwargs):
        relative = Path(path).relative_to(root).as_posix()
        assert relative.startswith(("bottle/train/good/", "bottle/test/")) and "/ground_truth/" not in relative
        opened.append(relative)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Image, "open", guarded_open)
    reports = []
    for suffix in ("first", "second"):
        reports.append(ev.evaluate_run(run, protocol_path=PROTOCOL, approved_sha256=ev._sha256(PROTOCOL),
                                       manifest=manifest, root=root, output=tmp_path / suffix, device=CPU))
    assert reports[0] == reports[1]
    assert len(opened) == 12 and len(set(opened)) == 4
    assert reports[0]["images"] == 2 and reports[0]["split"] == "test_real_mvtec"
    assert reports[0]["pixel_metrics_computed"] is False and reports[0]["gradcam_is_segmentation"] is False
    assert not {"dice", "iou", "pixel_auroc", "pixel_ap"} & set(reports[0]["metrics"])
    for name in ("predictions.csv", "metrics.json"):
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()
    assert before == (snapshot(root), snapshot(manifest.parent), snapshot(run))


def set_training_environment(run, **changes):
    environment = ev._json(run / "environment.json")
    environment.update(changes)
    write_json(run / "environment.json", environment)
    calibration = ev._json(run / "calibration.json")
    calibration["environment"] = environment
    rewrite_calibration(run, calibration)
    return environment


def test_portable_environment_preserves_kaggle_metadata_and_requires_parity(synthetic_run, copied_run, monkeypatch):
    training = set_training_environment(copied_run, python="3.13.16", torch="2.11.0+cu130", numpy="2.1.3",
                                        torchvision="0.26.0+cu130", device="cuda", gpu_name="Tesla T4")
    before = snapshot(copied_run)
    metadata = ev.inspect_run(copied_run, synthetic_run[2])
    assert metadata["training_environment"] == training
    assert metadata["evaluation_environment"]["device"] == "cpu"
    assert metadata["environment_changes"]["torch"]["training"] == "2.11.0+cu130"
    assert metadata["strict_weights_compatible"] and not metadata["compatibility_validated"]
    report = ev.validate_run(copied_run, manifest=synthetic_run[2], root=synthetic_run[1])
    assert report["compatibility_validated"] and report["status"] == "passed"
    assert report["training_environment"] == training
    assert report["score_tolerance_failures"] == report["decision_changes"] == 0
    assert report["test_executed"] is False
    assert before == snapshot(copied_run)


@pytest.mark.parametrize("library,value", [("python", "4.0.0"), ("torch", "3.0.0"), ("numpy", "1.26.4"),
                                           ("torchvision", "1.0.0"), ("scikit_learn", "2.0.0"), ("torch", "unknown")])
def test_major_or_untraceable_environment_refused(synthetic_run, copied_run, monkeypatch, library, value):
    set_training_environment(copied_run, **{library: value})
    def forbidden(*args, **kwargs): raise AssertionError("Dataset ouvert avant compatibilite")
    monkeypatch.setattr(synthetic, "SyntheticAnomalyDataset", forbidden)
    with pytest.raises(ValueError, match="majeure|Version"):
        ev.validate_run(copied_run, manifest=synthetic_run[2], root=synthetic_run[1])


def test_validation_opens_only_archived_validation_sources(synthetic_run, monkeypatch):
    _, root, manifest, run = synthetic_run
    before = snapshot(root), snapshot(run), snapshot(manifest.parent)
    allowed = {row["image_path"] for row in ev._json(run / "calibration.json")["validation_scores"]}
    opened = []
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        resolved = path.resolve()
        if resolved.is_relative_to(root.resolve()):
            relative = resolved.relative_to(root.resolve()).as_posix()
            assert relative in allowed and "/train/good/" in relative
            opened.append(relative)
        return original_open(path, *args, **kwargs)
    def forbidden(*args, **kwargs): raise AssertionError("Dataset test construit pendant validate")
    with monkeypatch.context() as guarded:
        guarded.setattr(Path, "open", guarded_open)
        guarded.setattr(ev, "MVTecDataset", forbidden)
        report = ev.validate_run(run, manifest=manifest, root=root)
    assert report["compatibility_validated"] and not report["test_executed"]
    assert set(opened) == allowed
    assert len(report["validation_scores"]) == len(allowed) * 2
    assert before == (snapshot(root), snapshot(run), snapshot(manifest.parent))


def mock_validation_predictions(monkeypatch, run, mutation):
    rows = deepcopy(ev._json(run / "calibration.json")["validation_scores"])
    threshold = ev._json(run / "calibration.json")["image_threshold"]
    selected = next(row for row in rows if row["label"] == 0 and row["score"] == threshold)
    mutation(rows, selected, threshold)
    monkeypatch.setattr(train_transfer, "run_epoch", lambda *args, **kwargs: {"predictions": rows})


@pytest.mark.parametrize("delta,passed,failures,unjustified", [
    (5e-6, True, 0, 0), (2e-5, False, 0, 1), (1e-3, False, 1, 1),
])
def test_score_parity_and_decision_boundary_policy(synthetic_run, monkeypatch, delta, passed, failures, unjustified):
    run = synthetic_run[3]
    mock_validation_predictions(monkeypatch, run, lambda rows, selected, threshold: selected.update(score=threshold + delta))
    report = ev.validate_run(run, manifest=synthetic_run[2], root=synthetic_run[1])
    assert report["compatibility_validated"] is passed
    assert report["score_tolerance_failures"] == failures
    assert report["decision_changes"] == 1
    assert report["unjustified_decision_changes"] == unjustified
    changed = next(row for row in report["validation_scores"] if row["decision_changed"])
    assert changed["archived_decision"] == 0 and changed["cpu_decision"] == 1
    assert report["image_threshold"] == ev._json(run / "calibration.json")["image_threshold"]


def test_relative_tolerance_is_applied_to_archived_score(synthetic_run, monkeypatch):
    run = synthetic_run[3]
    mock_validation_predictions(monkeypatch, run, lambda rows, selected, threshold: selected.update(score=threshold - 2e-5))
    report = ev.validate_run(run, manifest=synthetic_run[2], root=synthetic_run[1])
    assert report["compatibility_validated"] and report["decision_changes"] == 0
    assert report["max_absolute_error"] > ev.PARITY_POLICY["atol"]


@pytest.mark.parametrize("mutation", [
    lambda rows, selected, threshold: rows.pop(),
    lambda rows, selected, threshold: rows.__setitem__(0, rows[-1]),
    lambda rows, selected, threshold: selected.update(split="test"),
    lambda rows, selected, threshold: selected.update(image_path="bottle/test/good/000.png"),
    lambda rows, selected, threshold: selected.update(label=1),
])
def test_parity_rejects_incomplete_or_misaligned_samples(synthetic_run, monkeypatch, mutation):
    mock_validation_predictions(monkeypatch, synthetic_run[3], mutation)
    with pytest.raises(ValueError, match="Couverture|Identite"):
        ev.validate_run(synthetic_run[3], manifest=synthetic_run[2], root=synthetic_run[1])


def test_failed_parity_blocks_approved_evaluation_before_test_dataset(synthetic_run, tmp_path, monkeypatch):
    mock_validation_predictions(monkeypatch, synthetic_run[3],
                                lambda rows, selected, threshold: selected.update(score=threshold + 0.01))
    def forbidden(*args, **kwargs): raise AssertionError("Test ouvert malgre echec de parite")
    monkeypatch.setattr(ev, "MVTecDataset", forbidden)
    with pytest.raises(ValueError, match="Parite numerique refusee"):
        ev.evaluate_run(synthetic_run[3], protocol_path=PROTOCOL, approved_sha256=ev._sha256(PROTOCOL),
                        manifest=synthetic_run[2], root=synthetic_run[1], output=tmp_path / "out", device=CPU)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("passed", [True, False])
def test_validation_cli_saves_report_and_returns_status(synthetic_run, tmp_path, monkeypatch, capsys, passed):
    if not passed:
        mock_validation_predictions(monkeypatch, synthetic_run[3],
                                    lambda rows, selected, threshold: selected.update(score=threshold + 0.01))
    result = ev.main(["--stage", "validate", "--run-dir", str(synthetic_run[3]),
                      "--manifest", str(synthetic_run[2]), "--root", str(synthetic_run[1]),
                      "--output-dir", str(tmp_path / "reports"), "--device", "cpu"])
    assert result == (0 if passed else 1)
    message = json.loads(capsys.readouterr().out)
    report_path = Path(message["output"])
    assert ev._sha256(report_path) == message["sha256"]
    report = ev._json(report_path)
    assert report["compatibility_validated"] is passed
    assert report["test_executed"] is False


def test_modified_checkpoint_refused_before_deserialization(synthetic_run, copied_run, monkeypatch):
    path = copied_run / "best.pt"
    path.write_bytes(path.read_bytes() + b"tampered")
    def forbidden(*args, **kwargs): raise AssertionError("Deserialisation avant SHA256")
    monkeypatch.setattr(torch, "load", forbidden)
    with pytest.raises(ValueError, match="Checkpoint modifie"):
        ev.inspect_run(copied_run, synthetic_run[2])


@pytest.mark.parametrize("mutation", ["dtype", "shape", "missing_key", "extra_key", "nan"])
def test_incompatible_weights_rejected_even_with_consistent_hashes(synthetic_run, copied_run, mutation):
    payload = torch.load(copied_run / "best.pt", map_location="cpu", weights_only=True)
    state = payload["model_state_dict"]
    name = "classifier.1.weight"
    if mutation == "dtype": state[name] = state[name].double()
    elif mutation == "shape": state[name] = state[name][:, :1]
    elif mutation == "missing_key": del state[name]
    elif mutation == "extra_key": state["unknown"] = torch.zeros(1)
    else: state[name][0, 0] = float("nan")
    torch.save(payload, copied_run / "best.pt")
    digest = ev._sha256(copied_run / "best.pt")
    summary = ev._json(copied_run / "summary.json")
    summary["checkpoint_sha256"] = digest
    write_json(copied_run / "summary.json", summary)
    calibration = ev._json(copied_run / "calibration.json")
    calibration["checkpoint_sha256"] = digest
    rewrite_calibration(copied_run, calibration)
    with pytest.raises((ValueError, RuntimeError)):
        ev.inspect_run(copied_run, synthetic_run[2])


@pytest.mark.parametrize("name", ["train_t0.yaml", "synthetic_transfer.yaml", "train_transfer.py", "transfer.py",
                                 "synthetic.py", "dataset.py", "prepare.py", "audit.py", "train_ae.py",
                                 "evaluate_ae.py", "pyproject.toml"])
def test_every_archived_training_source_hash_remains_strict(synthetic_run, copied_run, name):
    path = copied_run / "source" / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Source ou configuration"):
        ev.inspect_run(copied_run, synthetic_run[2])


def test_archived_source_inventory_cannot_be_omitted(synthetic_run, copied_run):
    provenance = ev._json(copied_run / "provenance.json")
    provenance["source_sha256"].pop(next(iter(provenance["source_sha256"])))
    write_json(copied_run / "provenance.json", provenance)
    with pytest.raises(ValueError, match="Inventaire"):
        ev.inspect_run(copied_run, synthetic_run[2])


@pytest.mark.parametrize("relative", ["configs/train_t0.yaml", "configs/synthetic_transfer.yaml", "src/data/prepare.py",
                                     "src/data/audit.py", "src/training/train_ae.py", "pyproject.toml"])
def test_local_source_and_config_hashes_remain_strict(synthetic_run, monkeypatch, relative):
    original_hash = ev._sha256
    changed_path = PROJECT / relative
    def changed_hash(path):
        return "0" * 64 if Path(path) == changed_path else original_hash(path)
    monkeypatch.setattr(ev, "_sha256", changed_hash)
    with pytest.raises(ValueError, match="Source ou configuration"):
        ev.inspect_run(synthetic_run[3], synthetic_run[2])


@pytest.mark.parametrize("name", ["effective_config.yaml", "synthetic_plan.json"])
def test_modified_plan_or_effective_config_is_refused(synthetic_run, copied_run, name):
    path = copied_run / name
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Calibration|Plan synthetique"):
        ev.inspect_run(copied_run, synthetic_run[2])


def test_non_cpu_validation_refused_before_any_artifact_access(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs): raise AssertionError("Acces au run malgre device incompatible")
    monkeypatch.setattr(ev, "inspect_run", forbidden)
    with pytest.raises(ValueError, match="CPU"):
        ev.validate_run(tmp_path / "missing", manifest=tmp_path / "missing.csv", root=tmp_path,
                        device=torch.device("cuda"))
