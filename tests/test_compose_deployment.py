"""Deployment contracts, using temporary files; no datasets or real inference."""

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from deployment.healthcheck import ready


PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_compose", PROJECT / "scripts/prepare_compose.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def put(path, value="test"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value, encoding="utf-8")


@pytest.fixture
def inputs(tmp_path):
    for name in ("manifest.csv", "preparation.json"):
        put(tmp_path / "data/manifests" / name)
    for name in ("evaluate_ae_b0.yaml", "evaluate_transfer.yaml", "train_t0.yaml", "train_t1.yaml",
                 "train_t2.yaml", "synthetic_transfer.yaml"):
        put(tmp_path / "configs" / name)
    protocol_sha = prepare.sha256(tmp_path / "configs/evaluate_ae_b0.yaml")[:12]
    for variant in ("B0", "A1", "T0", "T1", "T2"):
        for category in prepare.CATEGORIES:
            transfer = variant.startswith("T")
            relative = (f"transfer_runs/{variant}/{category}/seed42/full_fixture" if transfer
                        else f"{variant.lower()}_runs/{category}/full_fixture")
            run = tmp_path / "artifacts" / relative
            summary = {"checkpoint_sha256": "a" * 64, "source_sha256": {"/archive/train.py": "b" * 64}}
            put(run / "summary.json", summary)
            for name in ("best.pt", "effective_config.yaml", "environment.json"):
                put(run / name)
            put(run / "history.csv")
            put(run / "loss_curves.png")
            if variant == "A1" or transfer:
                put(run / "source/train.py")
            if transfer:
                for name in ("synthetic_plan.json", "calibration.json", "calibration.sha256", "provenance.json"):
                    put(run / name)
                put(tmp_path / f"reports/transfer/portability/{variant}/{category}/seed42/{'a'*12}/{protocol_sha}/compatibility.json",
                    {"evaluation_environment": {"platform": "Windows-10"}})
            else:
                base = tmp_path / f"reports/evaluation/{variant.lower()}/{protocol_sha}/{category}"
                put(base / "calibration.json", {"checkpoint": {"path": "C:\\archive\\best.pt"}})
                put(base / "calibration.sha256")
    put(tmp_path / "reports/transfer/portability/validation_summary.json", {})
    put(tmp_path / "data/raw/forbidden.png")
    put(tmp_path / "artifacts/b0_runs/bottle/smoke_fixture/best.pt")
    put(tmp_path / "artifacts/b0_runs/mlartifacts/copy/best.pt")
    return tmp_path


def test_minimal_mounts_are_read_only_and_do_not_create_host_files(inputs):
    before = {str(path): path.read_bytes() for path in inputs.rglob("*") if path.is_file()}
    document, report = prepare.generate(inputs)
    mounts = document["services"]["scientific_files"]["volumes"]
    assert mounts
    assert all(item["type"] == "bind" and item["read_only"] is True
               and item["bind"]["create_host_path"] is False for item in mounts)
    assert len({item["target"] for item in mounts}) == len(mounts)
    assert sum(item["target"].endswith("/best.pt") for item in mounts) == 15
    assert not any(word in item["target"] for item in mounts
                   for word in ("/raw/", ".png", "history.csv", "smoke_", "mlartifacts", "test.csv", "val.csv"))
    assert len(report["linux_admission_blockers"]) == 15
    assert {str(path): path.read_bytes() for path in inputs.rglob("*") if path.is_file()} == before


def test_all_full_runs_remain_visible_for_backend_ambiguity_checks(inputs):
    base = inputs / "artifacts/b0_runs/bottle/full_other"
    for name in ("best.pt", "effective_config.yaml", "summary.json"):
        put(base / name, {} if name == "summary.json" else "other")
    document, _ = prepare.generate(inputs)
    mounts = document["services"]["scientific_files"]["volumes"]
    assert sum(item["target"].endswith("/best.pt") for item in mounts) == 16


def test_missing_checkpoint_fails_without_creating_a_directory(inputs):
    missing = inputs / "artifacts/b0_runs/bottle/full_fixture/best.pt"
    missing.unlink()
    with pytest.raises(ValueError, match="Required regular file missing"):
        prepare.generate(inputs)
    assert not missing.exists()


def test_archive_cannot_add_images_to_mounts(inputs):
    summary = inputs / "artifacts/a1_runs/bottle/full_fixture/summary.json"
    put(summary, {"source_sha256": {"/archive/sample.png": "a" * 64}})
    with pytest.raises(ValueError, match="Unsafe or duplicate"):
        prepare.generate(inputs)


def test_changed_artifact_roots_are_configurable(inputs):
    alternative = inputs / "custom"
    (inputs / "artifacts").rename(alternative)
    document, _ = prepare.generate(inputs, {"RI_ARTIFACTS_DIR": str(alternative)})
    checkpoint = next(item for item in document["services"]["scientific_files"]["volumes"]
                      if item["target"].endswith("/best.pt"))
    assert checkpoint["source"].startswith("${RI_ARTIFACTS_DIR:-./artifacts}/")


@pytest.mark.parametrize("body,expected", [
    ({"status": "ok", "device": "cpu", "ready_models": 15, "expected_models": 15}, True),
    ({"status": "degraded", "device": "cpu", "ready_models": 14, "expected_models": 15}, False),
    ({"status": "ok", "device": "cpu", "ready_models": 1, "expected_models": 1}, False),
    ({"status": "ok", "device": "cuda", "ready_models": 15, "expected_models": 15}, False),
    ({}, False),
])
def test_readiness_requires_fifteen_validated_cpu_models(body, expected):
    assert ready(body) is expected


def test_compose_keeps_local_ports_free_and_gates_frontend():
    document = yaml.safe_load((PROJECT / "docker-compose.yml").read_text(encoding="utf-8"))
    backend, frontend = (document["services"][name] for name in ("backend", "frontend"))
    assert backend["ports"] == ["127.0.0.1:${RI_BACKEND_PORT:-8001}:8000"]
    assert frontend["ports"] == ["127.0.0.1:${RI_FRONTEND_PORT:-18080}:8080"]
    assert frontend["depends_on"]["backend"]["condition"] == "service_healthy"
    assert set(document["services"]) == {"backend", "frontend"}
    assert backend["extends"]["file"] == "./docker-compose.mounts.yml"
