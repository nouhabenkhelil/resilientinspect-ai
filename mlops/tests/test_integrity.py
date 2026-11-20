"""Negative tests for restoration and Registry provenance, outside scientific paths."""
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dvc_release
from common import write


def test_restoration_rejects_tampered_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(dvc_release, "ROOT", tmp_path)
    target = tmp_path / "mlops/dataset/data/manifests/manifest.csv"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"tampered")
    write(tmp_path / "mlops/release-manifest.json", {"entries": [{"group":"dataset", "path":"data/manifests/manifest.csv",
          "sha256":hashlib.sha256(b"official").hexdigest(),"bytes":8}]})
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        dvc_release.verify(tmp_path)


def test_remote_inside_git_rejected_before_dvc_call(tmp_path, monkeypatch):
    monkeypatch.setattr(dvc_release, "ROOT", tmp_path)
    monkeypatch.setattr(dvc_release, "call", lambda *a,**k: pytest.fail("DVC must not execute"))
    with pytest.raises(ValueError, match="outside"):
        dvc_release.push(tmp_path / "remote")


def test_materialize_refuses_original_repository(tmp_path, monkeypatch):
    monkeypatch.setattr(dvc_release, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="separate recovery"):
        dvc_release.materialize(tmp_path)


def test_materialize_preflight_preserves_existing_target(tmp_path, monkeypatch):
    root=tmp_path / "source"; destination=tmp_path / "recovery"
    monkeypatch.setattr(dvc_release,"ROOT",root)
    source=root / "mlops/dataset/data/manifests/manifest.csv"
    source.parent.mkdir(parents=True);source.write_bytes(b"official")
    target=destination / "data/manifests/manifest.csv"
    target.parent.mkdir(parents=True);target.write_bytes(b"keep-me")
    write(root / "mlops/release-manifest.json",{"entries":[{"group":"dataset","path":"data/manifests/manifest.csv",
          "sha256":hashlib.sha256(b"official").hexdigest(),"bytes":8}]})
    with pytest.raises(ValueError,match="Refusing to overwrite"):
        dvc_release.materialize(destination)
    assert target.read_bytes()==b"keep-me"


def test_registry_refuses_corrupt_checkpoint_before_model_loading(tmp_path):
    spec = importlib.util.spec_from_file_location("registry_model", Path(__file__).resolve().parents[1] / "registry_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checkpoint=tmp_path / "best.pt"; checkpoint.write_bytes(b"corrupt")
    binding=tmp_path / "binding.json"
    write(binding,{"sha256":{"checkpoint":hashlib.sha256(b"authentic").hexdigest()}})
    with pytest.raises(ValueError, match="SHA256 mismatch: checkpoint"):
        module.FrozenTransferModel().load_context(SimpleNamespace(artifacts={"binding":str(binding),"checkpoint":str(checkpoint)}))
