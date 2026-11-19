from dataclasses import asdict
from pathlib import Path

import pytest

from backend.app.portability import checkpoint_matches, compatible_environment, require_evidence
from resilientinspect.evaluation.evaluate_ae import Checkpoint
from resilientinspect.data.audit import _sha256


def test_relocation_requires_canonical_identity_and_unchanged_bytes(tmp_path):
    path = tmp_path / "artifacts/b0_runs/bottle/full_abc/best.pt"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"weights")
    cp = Checkpoint("bottle", str(path), "abc", _sha256(path), "manifest", 1)
    archived = {**asdict(cp), "path": "C:/archive/artifacts/b0_runs/bottle/full_abc/best.pt"}
    assert checkpoint_matches(archived, cp, tmp_path, "B0")
    assert not checkpoint_matches({**archived, "run_id": "other"}, cp, tmp_path, "B0")
    assert not checkpoint_matches({**archived, "path": "C:/archive/../artifacts/b0_runs/bottle/full_abc/best.pt"}, cp, tmp_path, "B0")
    assert not checkpoint_matches({**archived, "path": "C:/archive/artifacts/b0_runs/leather/full_abc/best.pt"}, cp, tmp_path, "B0")
    path.write_bytes(b"tampered")
    assert not checkpoint_matches(archived, cp, tmp_path, "B0")


def test_environment_preserves_versions_and_numerical_settings():
    windows = {"platform": "Windows", "machine": "AMD64", "torch": "2.15.0+cpu", "cpu_threads": 2}
    linux = {**windows, "platform": "Linux", "machine": "x86_64"}
    assert compatible_environment(windows, linux)
    assert not compatible_environment(windows, {**linux, "torch": "2.15.1+cpu"})
    assert not compatible_environment(windows, {**linux, "cpu_threads": 4})


def test_linux_missing_evidence_fails_closed(tmp_path, monkeypatch):
    from backend.app import portability
    monkeypatch.setattr(portability.evaluate_transfer, "_environment", lambda: {"platform": "Linux"})
    with pytest.raises(OSError):
        require_evidence(tmp_path, None)
