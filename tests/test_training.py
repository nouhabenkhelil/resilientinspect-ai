"""Pipeline B0 : donnees temporaires, suivi MLflow reel et selection val uniquement."""

import json
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
from resilientinspect.models.autoencoder import ConvAutoencoder
from resilientinspect.training import train_ae
from test_prepare import make_dataset, prepared, snapshot


PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def restore_process_state():
    threads = torch.get_num_threads()
    deterministic = torch.are_deterministic_algorithms_enabled()
    benchmark, cudnn_deterministic = torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic
    precision = torch.get_float32_matmul_precision()
    python_state, numpy_state = random.getstate(), np.random.get_state()
    with torch.random.fork_rng(devices=[]):
        yield
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(deterministic)
    torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic = benchmark, cudnn_deterministic
    torch.set_float32_matmul_precision(precision)
    random.setstate(python_state)
    np.random.set_state(numpy_state)


def write_config(path, **updates):
    config = train_ae.load_config(PROJECT / "configs/train_ae_b0.yaml")
    config["model_config"] = str(PROJECT / "configs/ae_baseline.yaml")
    config["dataset_config"] = str(PROJECT / "configs/dataset.yaml")
    config.update(updates)
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("training_integration")
    root = make_dataset(tmp / "raw")
    rows, report = prepare_dataset(root)
    manifests = tmp / "manifests"
    write_manifests(rows, report, manifests)
    config = write_config(tmp / "train.yaml")
    before = snapshot(root), snapshot(manifests)
    opened = []
    original_open = Image.open
    def guarded_open(path, *args, **kwargs):
        relative = Path(path).relative_to(root).as_posix()
        assert relative.startswith("bottle/train/good/")
        assert "/test/" not in relative and "/ground_truth/" not in relative
        opened.append(relative)
        return original_open(path, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Image, "open", guarded_open)
        first = train_ae.run_training(config, root=root, manifest=manifests / "manifest.csv",
                                      output_dir=tmp / "output", category="bottle", device="cpu", smoke=True)
        second = train_ae.run_training(config, root=root, manifest=manifests / "manifest.csv",
                                       output_dir=tmp / "output", category="bottle", device="cpu", smoke=True)
    assert before == (snapshot(root), snapshot(manifests))
    return tmp, root, manifests, config, first, second, opened


def test_real_smoke_updates_weights_but_never_reads_test_masks_or_other_categories(runs):
    _, root, manifests, _, first, _, opened = runs
    assert first["scope"] == "smoke" and first["epochs_completed"] == 1
    assert first["test_used"] is False and first["selection_split"] == "val"
    row = first["history"][0]
    assert row["train_batches"] == 2 and row["train_images"] == 4
    assert row["val_batches"] == 1 and row["val_images"] == 2
    assert len(opened) == 12  # Deux runs, 4 train + 2 val dans chacun.
    usage = json.loads((Path(first["run_dir"]) / "data_usage.json").read_text())
    assert not set(usage["train"]) & set(usage["val"])
    checkpoint = torch.load(Path(first["run_dir"]) / "best.pt", map_location="cpu", weights_only=True)
    assert checkpoint["epoch"] == first["best_epoch"] == 1
    assert checkpoint["val_loss"] == row["val_loss"]
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(42)
        initial = ConvAutoencoder().state_dict()
    assert not torch.equal(initial["encoder.0.0.weight"], checkpoint["model_state_dict"]["encoder.0.0.weight"])
    restored = ConvAutoencoder()
    restored.load_state_dict(checkpoint["model_state_dict"])
    restored.eval()
    with torch.inference_mode():
        assert torch.isfinite(restored(torch.zeros(1, 3, 256, 256))).all()


def test_same_environment_seed_and_manifests_reproduce_history_and_checkpoint_tensors(runs):
    *_, first, second, opened = runs
    assert first["run_id"] != second["run_id"] and first["run_dir"] != second["run_dir"]
    assert first["history"] == second["history"]
    one = torch.load(Path(first["run_dir"]) / "best.pt", weights_only=True, map_location="cpu")
    two = torch.load(Path(second["run_dir"]) / "best.pt", weights_only=True, map_location="cpu")
    assert all(torch.equal(value, two["model_state_dict"][key]) for key, value in one["model_state_dict"].items())


def test_mlflow_records_real_metrics_parameters_tags_and_artifacts(runs):
    first = runs[4]
    client = MlflowClient(tracking_uri=first["tracking_uri"])
    run = client.get_run(first["run_id"])
    assert run.info.status == "FINISHED"
    assert run.data.tags["category"] == "bottle" and run.data.tags["scope"] == "smoke"
    assert run.data.tags["test_used"] == "false"
    assert run.data.params["batch_size"] == "2" and run.data.params["max_epochs"] == "1"
    assert run.data.metrics["best_val_loss"] == first["best_val_loss"]
    for split in ("train", "val"):
        history = client.get_metric_history(first["run_id"], f"{split}_loss")
        assert len(history) == 1 and history[0].step == 1
        assert history[0].value == first["history"][0][f"{split}_loss"]
    files = {artifact.path for artifact in client.list_artifacts(first["run_id"])}
    assert {"best.pt", "history.csv", "loss_curves.png", "effective_config.yaml", "environment.json",
            "provenance.json", "summary.json", "data_usage.json", "architecture.yaml", "dataset_config.yaml"} <= files


def test_validation_does_not_update_weights_bn_buffers_or_create_gradients(prepared):
    root, _, _, output = prepared
    settings = train_ae.load_config(PROJECT / "configs/train_ae_b0.yaml")["training"]
    loaders = train_ae.build_loaders(output / "manifest.csv", root, "bottle", settings, 42, torch.device("cpu"))
    model = ConvAutoencoder()
    before = {key: value.clone() for key, value in model.state_dict().items()}
    result = train_ae.run_epoch(model, loaders["val"], torch.device("cpu"))
    assert result["images"] == 2 and not model.training
    assert all(torch.equal(value, model.state_dict()[key]) for key, value in before.items())
    assert all(p.grad is None for p in model.parameters())


class ZeroReconstruction(nn.Module):
    def forward(self, images):
        return torch.zeros_like(images)


def test_epoch_mean_weights_the_short_last_batch_by_sample_count():
    samples = [{"image": torch.full((3, 256, 256), value), "split": "val", "image_path": str(i)}
               for i, value in enumerate((0.0, 1.0, 1.0))]
    result = train_ae.run_epoch(ZeroReconstruction(), DataLoader(samples, batch_size=2), torch.device("cpu"))
    assert result["loss"] == pytest.approx(2 / 3)
    assert result["images"] == 3 and result["batches"] == 2


def test_epoch_rejects_a_test_split_before_any_model_forward():
    loader = DataLoader([{"image": torch.zeros(3, 256, 256), "split": "test", "image_path": "forbidden"}])
    with pytest.raises(ValueError, match="Split interdit"):
        train_ae.run_epoch(ZeroReconstruction(), loader, torch.device("cpu"))


def test_early_stopping_counts_ties_and_resets_only_on_significant_improvement():
    stopper = train_ae.EarlyStopping(patience=2, min_delta=0.01)
    assert not stopper.update(0.5)
    assert not stopper.update(0.495)
    assert not stopper.update(0.48) and stopper.bad_epochs == 0
    assert not stopper.update(0.48)
    assert stopper.update(0.48)
    with pytest.raises(ValueError, match="non finie"):
        stopper.update(float("nan"))


def test_checkpoint_selection_follows_val_minimum_and_early_stops_with_mocked_epochs(runs, monkeypatch):
    # Pertes de controle simulees, uniquement dans le repertoire temporaire du test.
    tmp, root, manifests, config_path, *_ = runs
    config = train_ae.load_config(config_path)
    config["training"]["max_epochs"] = 5
    config["training"]["early_stopping"]["patience"] = 1
    config_path = tmp / "selection.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    epoch = 0
    def fake_epoch(model, loader, device, optimizer=None, max_batches=None):
        nonlocal epoch
        if optimizer is not None:
            epoch += 1
            with torch.no_grad():
                next(model.parameters()).fill_(epoch * 0.001)
            loss = [0.3, 0.2, 0.1][epoch - 1]
        else:
            loss = [0.4, 0.3, 0.35][epoch - 1]
        return {"loss": loss, "images": 1, "batches": 1, "image_paths": [loader.dataset.rows[0]["image_path"]]}
    monkeypatch.setattr(train_ae, "run_epoch", fake_epoch)
    result = train_ae.run_training(config_path, root=root, manifest=manifests / "manifest.csv",
                                   output_dir=tmp / "output", device="cpu")
    assert result["epochs_completed"] == 3 and result["stopped_early"]
    assert result["best_epoch"] == 2 and result["best_val_loss"] == 0.3
    checkpoint = torch.load(Path(result["run_dir"]) / "best.pt", map_location="cpu", weights_only=True)
    assert checkpoint["epoch"] == 2
    assert torch.all(checkpoint["model_state_dict"]["encoder.0.0.weight"] == 0.002)


def test_failed_epoch_marks_mlflow_run_failed_without_best_checkpoint(runs, monkeypatch):
    tmp, root, manifests, config, *_ = runs
    def fail(*args, **kwargs):
        raise ValueError("synthetic failure")
    monkeypatch.setattr(train_ae, "run_epoch", fail)
    with pytest.raises(ValueError, match="synthetic failure"):
        train_ae.run_training(config, root=root, manifest=manifests / "manifest.csv",
                              output_dir=tmp / "output", device="cpu", smoke=True)
    failures = list((tmp / "output/bottle").glob("*/failure.json"))
    assert len(failures) == 1 and not failures[0].with_name("best.pt").exists()
    failure = json.loads(failures[0].read_text())
    client = MlflowClient(tracking_uri=runs[4]["tracking_uri"])
    assert client.get_run(failure["run_id"]).info.status == "FAILED"


@pytest.mark.parametrize("destination", ["raw", "manifest"])
def test_output_cannot_overwrite_protected_inputs(prepared, tmp_path, destination):
    root, _, _, manifests = prepared
    output = root if destination == "raw" else manifests
    before = snapshot(output)
    with pytest.raises(ValueError, match="hors des donnees"):
        train_ae.run_training(PROJECT / "configs/train_ae_b0.yaml", root=root,
                              manifest=manifests / "manifest.csv", output_dir=output, device="cpu", smoke=True)
    assert snapshot(output) == before


def test_modified_manifest_is_refused_before_reading_any_image(prepared):
    root, _, _, output = prepared
    path = output / "manifest.csv"
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], *reversed(lines[1:])]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empreinte figee"):
        train_ae.build_loaders(path, root, "bottle", {}, 42, torch.device("cpu"))


@pytest.mark.parametrize("field,value", [("learning_rate", float("nan")), ("batch_size", 0),
                                         ("max_epochs", True), ("mixed_precision", True)])
def test_invalid_training_settings_are_not_silently_accepted(tmp_path, field, value):
    config = train_ae.load_config(PROJECT / "configs/train_ae_b0.yaml")
    config["training"][field] = value
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError):
        train_ae.load_config(path)


def test_smoke_budget_cannot_be_expanded_by_configuration(tmp_path):
    config = train_ae.load_config(PROJECT / "configs/train_ae_b0.yaml")
    config["smoke"]["max_epochs"] = 20
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="Smoke limite"):
        train_ae.load_config(path)


def test_unknown_optimizer_setting_fails_instead_of_being_ignored(tmp_path):
    config = train_ae.load_config(PROJECT / "configs/train_ae_b0.yaml")
    config["training"]["momentum"] = 0.9
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError, match="inconnus"):
        train_ae.load_config(path)


def test_explicit_cuda_request_never_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert train_ae.resolve_device("auto").type == "cpu"
    with pytest.raises(ValueError, match="CUDA demande mais indisponible"):
        train_ae.resolve_device("cuda")


def test_cli_missing_data_returns_failure_without_creating_outputs(tmp_path):
    output = tmp_path / "output"
    assert train_ae.main(["--root", str(tmp_path / "absent"), "--output-dir", str(output), "--smoke"]) == 1
    assert not output.exists()
