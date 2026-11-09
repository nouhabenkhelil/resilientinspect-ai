"""Artefacts A1 synthetiques crees sans apprentissage ni donnees officielles."""

import json
from pathlib import Path

import pytest
import torch
import yaml

from resilientinspect.evaluation import a1_checkpoints as cp
from resilientinspect.models.autoencoder_improved import ImprovedAutoencoder

PROJECT = Path(__file__).resolve().parents[1]


def write_run(root, category, manifest_sha, *, name="full_synthetic", scope="full", seed=42):
    path = root / category / name
    path.mkdir(parents=True)
    architecture = yaml.safe_load((PROJECT / "configs/ae_improved.yaml").read_text(encoding="utf-8"))
    architecture["model"]["kwargs"]["channels"] = [4, 8, 16, 32]
    effective = {"variant": "A1", "category": category, "scope": scope, "seed": seed,
                 "training": {"loss": "l1_ssim"}, "max_batches_per_split": None if scope == "full" else 2,
                 "architecture": architecture}
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = ImprovedAutoencoder(**architecture["model"]["kwargs"])
    torch.save({"variant": "A1", "category": category, "scope": scope, "seed": seed, "epoch": 1,
                "val_loss": 0.1, "manifest_sha256": manifest_sha, "effective_config": effective,
                "architecture": architecture, "model_state_dict": model.state_dict()}, path / "best.pt")
    summary = {"status": "completed", "variant": "A1", "scope": scope, "category": category,
               "selection_split": "val", "test_used": False, "best_epoch": 1, "epochs_completed": 1,
               "best_val_loss": 0.1, "run_id": name.split("_", 1)[1], "manifest_sha256": manifest_sha,
               "checkpoint_sha256": cp._sha256(path / "best.pt"),
               "history": [{"epoch": 1, "val_loss": 0.1, "train_images": 2, "val_images": 2}]}
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (path / "effective_config.yaml").write_text(yaml.safe_dump(effective), encoding="utf-8")
    (path / "architecture.yaml").write_text(yaml.safe_dump(architecture), encoding="utf-8")
    return path


@pytest.fixture
def runs(tmp_path):
    root = tmp_path / "runs"
    for category in cp.CATEGORIES:
        write_run(root, category, "a" * 64)
    return root


def test_discovery_excludes_unreadable_smoke_and_mlflow_before_loading(runs):
    for relative in ("bottle/smoke_bad", "mlartifacts/full_bad/artifacts"):
        path = runs / relative
        path.mkdir(parents=True)
        (path / "best.pt").write_bytes(b"invalid and never loaded")
    selected, excluded = cp.discover_checkpoints(runs)
    assert list(selected) == list(cp.CATEGORIES)
    assert {row["reason"] for row in excluded} == {"smoke", "mlflow_copy"}
    metadata = cp.inspection_metadata(selected["bottle"])
    assert metadata["seed"] == 42 and metadata["epochs_completed"] == 1
    assert "architecture.yaml" in metadata["verified_artifact_sha256"]


def test_strict_a1_loader_is_used_and_frozen(runs, monkeypatch):
    checkpoint = cp.discover_checkpoints(runs)[0]["bottle"]
    original = cp.a1_config.load_a1_checkpoint
    calls = []
    def loader(path, device):
        calls.append((path, device))
        return original(path, device)
    monkeypatch.setattr(cp.a1_config, "load_a1_checkpoint", loader)
    model = cp.load_model(checkpoint, torch.device("cpu"), "a" * 64)
    assert calls == [(Path(checkpoint.path), torch.device("cpu"))]
    assert not model.training and all(not value.requires_grad for value in model.parameters())
    with pytest.raises(ValueError, match="manifeste"):
        cp.load_model(checkpoint, torch.device("cpu"), "b" * 64)


@pytest.mark.parametrize("mutation", ["variant", "test_used", "loss", "run_id", "architecture", "checksum", "payload", "provenance", "usage", "source"])
def test_inconsistent_metadata_fail_closed(runs, mutation):
    path = runs / "bottle/full_synthetic"
    summary = json.loads((path / "summary.json").read_text())
    if mutation == "variant": summary["variant"] = "B0"
    elif mutation == "test_used": summary["test_used"] = True
    elif mutation == "loss": summary["best_val_loss"] = float("nan")
    elif mutation == "run_id": summary["run_id"] = "wrong"
    elif mutation == "architecture": (path / "architecture.yaml").write_text("{}")
    elif mutation == "checksum": (path / "best.pt").write_bytes(b"modified")
    elif mutation == "payload":
        payload = torch.load(path / "best.pt", weights_only=True)
        payload["seed"] = 999
        torch.save(payload, path / "best.pt")
        summary["checkpoint_sha256"] = cp._sha256(path / "best.pt")
    elif mutation == "provenance": (path / "provenance.json").write_text('{"manifest_sha256": "wrong"}')
    elif mutation == "usage": (path / "data_usage.json").write_text('{"train": ["bottle/test/good/0.png"], "val": []}')
    elif mutation == "source": summary["source_sha256"] = {"/kaggle/source.py": "a" * 64}
    (path / "summary.json").write_text(json.dumps(summary))
    with pytest.raises(ValueError): cp.discover_checkpoints(runs)


def test_distinct_complete_runs_are_ambiguous(runs):
    write_run(runs, "bottle", "a" * 64, name="full_other", seed=7)
    with pytest.raises(ValueError, match="Plusieurs runs complets"):
        cp.discover_checkpoints(runs)


@pytest.mark.parametrize("mutation", ["missing_weight", "nan", "skip_scale"])
def test_load_rejects_bad_weights_via_existing_a1_contract(runs, mutation):
    path = runs / "bottle/full_synthetic"
    payload = torch.load(path / "best.pt", weights_only=True)
    key = next(key for key in payload["model_state_dict"] if key.endswith("weight"))
    if mutation == "missing_weight": payload["model_state_dict"].pop(key)
    elif mutation == "nan": payload["model_state_dict"][key].fill_(float("nan"))
    else:
        key = next(key for key in payload["model_state_dict"] if key.endswith("scale"))
        payload["model_state_dict"][key].fill_(0.9)
    torch.save(payload, path / "best.pt")
    summary = json.loads((path / "summary.json").read_text())
    summary["checkpoint_sha256"] = cp._sha256(path / "best.pt")
    (path / "summary.json").write_text(json.dumps(summary))
    checkpoint = cp.discover_checkpoints(runs)[0]["bottle"]
    with pytest.raises((ValueError, RuntimeError)):
        cp.load_model(checkpoint, torch.device("cpu"), "a" * 64)
