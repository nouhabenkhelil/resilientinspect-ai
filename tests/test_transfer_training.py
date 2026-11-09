"""Pipeline transfert sur images temporaires ; aucun poids ImageNet ni reseau requis."""

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import random

from mlflow import MlflowClient
import numpy as np
from PIL import Image
import pytest
import torch
from torch import nn
from torch.utils.data import DataLoader
import yaml

from resilientinspect.data.prepare import prepare_dataset, write_manifests
from resilientinspect.training import train_transfer as tr
from test_prepare import make_dataset, snapshot

PROJECT = Path(__file__).resolve().parents[1]
CPU = torch.device("cpu")


@pytest.fixture(scope="module", autouse=True)
def restore_process_state():
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
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def temporary_config(path, variant="t0"):
    config = tr.load_config(PROJECT / f"configs/train_{variant}.yaml")
    config["synthetic_config"] = str(PROJECT / "configs/synthetic_transfer.yaml")
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    temporary = tmp_path_factory.mktemp("transfer_training")
    root = make_dataset(temporary / "raw")
    rows, report = prepare_dataset(root)
    write_manifests(rows, report, temporary / "manifests")
    manifest = temporary / "manifests/manifest.csv"
    config = temporary_config(temporary / "train.yaml")
    return temporary, root, manifest, config


@pytest.fixture(scope="module")
def runs(synthetic):
    temporary, root, manifest, config = synthetic
    before = snapshot(root), snapshot(manifest.parent)
    opened = []
    original_open = Image.open

    def guarded_open(path, *args, **kwargs):
        relative = Path(path).relative_to(root).as_posix()
        assert relative.startswith("bottle/train/good/")
        assert "/test/" not in relative and "/ground_truth/" not in relative
        opened.append(relative)
        return original_open(path, *args, **kwargs)

    results = []
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Image, "open", guarded_open)
        for _ in range(2):
            results.append(tr.run_training(config, root=root, manifest=manifest, output_dir=temporary / "runs",
                                           category="bottle", seed=42, device="cpu", smoke=True))
    assert before == (snapshot(root), snapshot(manifest.parent))
    return *synthetic, results, opened


def test_configurations_share_architecture_examples_seed_and_budget():
    configs = [tr.load_config(PROJECT / f"configs/train_t{i}.yaml") for i in range(3)]
    for key in ("categories", "seed", "synthetic_config", "calibration", "smoke", "tracking"):
        assert configs[0][key] == configs[1][key] == configs[2][key]
    for key in ("batch_size", "max_epochs", "head_lr", "weight_decay", "loss", "mixed_precision", "num_workers", "cpu_threads", "early_stopping"):
        assert configs[0]["training"][key] == configs[1]["training"][key] == configs[2]["training"][key]
    assert [config["training"]["backbone_lr"] for config in configs] == [0.001, 0, 0.0001]
    assert all(config["model"]["head_dropout"] == 0.2 for config in configs)


@pytest.mark.parametrize("section,key,value", [
    (None, "variant", "B0"), (None, "seed", True),
    ("training", "loss", "mse"), ("training", "mixed_precision", True),
    ("training", "backbone_lr", 0), ("training", "head_lr", float("nan")),
    ("model", "head_dropout", 0.3), ("model", "unfreeze_stages", []),
    ("calibration", "quantile", 0.9), ("smoke", "max_epochs", 2),
    ("tracking", "experiment_name", "resilientinspect-ae"),
])
def test_invalid_or_incompatible_configuration_is_rejected(tmp_path, section, key, value):
    config = tr.load_config(PROJECT / "configs/train_t0.yaml")
    target = config if section is None else config[section]
    target[key] = value
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError):
        tr.load_config(path)


def test_classification_metrics_exact_ties_and_no_pixel_claim():
    actual = tr.classification_metrics(np.array([0, 0, 1, 1]), np.array([0.2, 0.6, 0.6, 0.9]), 0.6)
    assert actual["accuracy"] == 0.75 and actual["f1"] == pytest.approx(2 / 3)
    assert actual["auroc"] == 0.875 and actual["ap"] == pytest.approx(5 / 6)
    assert {key: actual[key] for key in ("tn", "tp", "fp", "fn")} == {"tn": 2, "tp": 1, "fp": 0, "fn": 1}
    assert actual["anomaly_fraction"] == 0.5 and actual["positive_class"] == 1
    assert not {"dice", "iou", "pixel_auroc"} & set(actual)
    degenerate = tr.classification_metrics(np.array([0, 0]), np.array([0., 0.]))
    assert degenerate["auroc"] is degenerate["ap"] is degenerate["f1"] is None
    with pytest.raises(ValueError):
        tr.classification_metrics(np.array([0, 1]), np.array([0., 1.]), float("nan"))


class FirstPixelLogit(nn.Module):
    def forward(self, images):
        return images[:, 0, 0, 0]


def sample(value, label, split="val", index=0):
    return {"image": torch.full((3, 256, 256), value), "label": label, "split": split,
            "image_path": f"bottle/train/good/{index}.png", "sample_id": str(index)}


def test_epoch_weights_short_last_batch_by_sample_count():
    examples = [sample(value, label, index=i) for i, (value, label) in enumerate(((0., 0), (1., 1), (1., 0)))]
    result = tr.run_epoch(FirstPixelLogit(), DataLoader(examples, batch_size=2), CPU)
    expected = nn.functional.binary_cross_entropy_with_logits(torch.tensor([0., 1., 1.]), torch.tensor([0., 1., 0.])).item()
    assert result["loss"] == pytest.approx(expected)
    assert result["images"] == 3 and result["batches"] == 2
    assert all(row["split"] == "val" for row in result["predictions"])


def test_epoch_rejects_test_before_model_forward():
    class Forbidden(nn.Module):
        def forward(self, images):
            raise AssertionError("Le modele ne doit pas voir test")
    with pytest.raises(ValueError, match="Split interdit"):
        tr.run_epoch(Forbidden(), DataLoader([sample(0., 0, "test")]), CPU)


def test_full_cpu_training_is_blocked_before_dataset_access(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pas de Dataset avant garde CPU")
    monkeypatch.setattr(tr.synthetic, "prepare_synthetic_plan", forbidden)
    with pytest.raises(ValueError, match="reserve a CUDA"):
        tr.run_training(PROJECT / "configs/train_t0.yaml", root=tmp_path / "absent", manifest=tmp_path / "absent.csv",
                        output_dir=tmp_path / "out", category="bottle", device="cpu")


def test_b0_a1_sources_data_and_manifests_are_protected(synthetic):
    _, root, manifest, _ = synthetic
    for path in (root / "output", manifest.parent / "output", PROJECT / "artifacts/b0_runs/output",
                 PROJECT / "artifacts/a1_runs/output", PROJECT / "reports/evaluation/b0/output",
                 PROJECT / "reports/evaluation/a1/output", PROJECT / "configs/output", PROJECT / "src/output"):
        with pytest.raises(ValueError):
            tr._safe_output(path, root, manifest)


def test_synthetic_smoke_uses_no_test_and_saves_real_updates(runs):
    _, _, _, _, results, opened = runs
    first = results[0]
    assert opened and all("/train/good/" in path for path in opened)
    assert first["scope"] == "smoke" and first["epochs_completed"] == first["best_epoch"] == 1
    assert first["selection_split"] == "val_synthetic" and first["test_used"] is False
    assert first["history"][0]["train_batches"] == first["history"][0]["val_batches"] == 2
    path = Path(first["run_dir"])
    saved = torch.load(path / "best.pt", weights_only=True, map_location="cpu")
    initial = tr.transfer.build_transfer_model("T0", seed=42)
    assert any(not torch.equal(value, saved["model_state_dict"][name]) for name, value in initial.state_dict().items())
    assert saved["scope"] == "smoke" and saved["synthetic_plan_sha256"] == first["synthetic_plan_sha256"]
    usage = json.loads((path / "data_usage.json").read_text(encoding="utf-8"))
    assert not set(usage["train"]) & set(usage["val"])


def test_same_plan_seed_environment_reproduce_histories_and_tensors(runs):
    first, second = runs[4]
    assert first["run_id"] != second["run_id"]
    assert first["history"] == second["history"]
    assert first["synthetic_plan_sha256"] == second["synthetic_plan_sha256"]
    assert first["validation_metrics"] == second["validation_metrics"]
    saved = [torch.load(Path(result["run_dir"]) / "best.pt", weights_only=True, map_location="cpu") for result in (first, second)]
    assert all(torch.equal(value, saved[1]["model_state_dict"][name]) for name, value in saved[0]["model_state_dict"].items())


def test_calibration_recomputes_val_normal_quantile_and_binds_artifacts(runs):
    first = runs[4][0]
    path = Path(first["run_dir"])
    calibration = json.loads((path / "calibration.json").read_text(encoding="utf-8"))
    normal = np.array([row["score"] for row in calibration["validation_scores"] if row["label"] == 0])
    assert calibration["image_threshold"] == float(np.quantile(normal, 0.95, method="higher"))
    assert calibration["normal_only"] and calibration["calibration_split"] == "val_synthetic"
    assert calibration["checkpoint_sha256"] == tr._sha256(path / "best.pt")
    assert calibration["effective_config_sha256"] == tr._sha256(path / "effective_config.yaml")
    assert (path / "calibration.sha256").read_text(encoding="ascii").strip() == tr._sha256(path / "calibration.json")
    assert calibration["synthetic_plan_sha256"] == tr._sha256(path / "synthetic_plan.json")
    assert calibration["validation_images"] == first["validation_metrics"]["images"] == 4
    assert not any("/test/" in row["image_path"] for row in calibration["validation_scores"])


def test_mlflow_logs_measured_curves_parameters_and_provenance(runs):
    first = runs[4][0]
    client = MlflowClient(tracking_uri=first["tracking_uri"])
    run = client.get_run(first["run_id"])
    assert run.info.status == "FINISHED"
    assert run.data.tags["test_used"] == "false" and run.data.tags["variant"] == "T0"
    assert run.data.tags["selection_split"] == "val_synthetic"
    assert run.data.params["batch_size"] == "2" and run.data.params["max_epochs"] == "1"
    assert run.data.metrics["best_val_loss"] == first["best_val_loss"]
    for key in ("loss", "accuracy", "auroc", "ap", "f1"):
        for split in ("train", "val"):
            observed = first["history"][0][f"{split}_{key}"]
            if observed is not None:
                assert client.get_metric_history(first["run_id"], f"{split}_{key}")[0].value == observed
    artifacts = {item.path for item in client.list_artifacts(first["run_id"])}
    assert {"best.pt", "history.csv", "learning_curves.png", "validation_diagnostics.png", "calibration.json",
            "calibration.sha256", "validation_predictions.csv", "validation_metrics.json", "effective_config.yaml",
            "environment.json", "provenance.json", "summary.json", "data_usage.json", "trainable_parameters.json",
            "weight_provenance.json", "synthetic_plan.json"} <= artifacts
    with Image.open(Path(first["run_dir"]) / "learning_curves.png") as figure:
        assert figure.size == (1440, 840)


def test_stale_plan_is_rejected_before_model_or_images(synthetic, tmp_path, monkeypatch):
    _, root, manifest, config = synthetic
    plan = tr.synthetic.prepare_synthetic_plan(manifest, tr.synthetic.load_synthetic_config(PROJECT / "configs/synthetic_transfer.yaml"), 42)
    plan["seed"] = 43
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    def forbidden(*args, **kwargs):
        raise AssertionError("Acces modele/image apres plan perime")
    monkeypatch.setattr(tr.transfer, "build_transfer_model", forbidden)
    monkeypatch.setattr(Image, "open", forbidden)
    with pytest.raises(ValueError, match="Plan synthetique"):
        tr.run_training(config, root=root, manifest=manifest, output_dir=tmp_path / "out", category="bottle",
                        device="cpu", smoke=True, synthetic_plan=path)
