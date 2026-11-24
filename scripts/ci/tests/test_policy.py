"""Negative controls for CI gates; synthetic bytes and configuration only."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

DIRECTORY = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, DIRECTORY / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


guard = module("repository_guard")
docker = module("docker_build")


@pytest.mark.parametrize("name", ["weights/a.pt", "model.onnx", "tracking.sqlite", ".env.local", ".dvc/cache/a", ".mlflow-ui/lib/a.py", "mlops/local/db.txt", "frontend/reports/screenshots/inspection.png"])
def test_private_paths_are_blocked(name):
    assert guard.path_problem(name)


@pytest.mark.parametrize("name", [".env.example", "mlops/dataset.dvc", "mlops/release-manifest.json", "reports/experiments/mlops_registry.json", "frontend/public/logo.svg", "data/raw/.gitkeep"])
def test_legitimate_metadata_and_placeholders_remain_allowed(name):
    assert guard.path_problem(name) is None


def test_sqlite_and_dataset_bytes_cannot_be_hidden_by_renaming():
    data = b"synthetic test image bytes"
    assert guard.inspect_bytes("diagram.txt", data, {hashlib.sha256(data).hexdigest()})
    assert guard.inspect_bytes("report.txt", b"SQLite format 3\x00" + b"test", set())


def test_secret_and_size_checks_do_not_need_real_credentials():
    assert guard.inspect_bytes("example.txt", b"ghp_" + b"A" * 36, set())
    assert guard.inspect_bytes("oversize.txt", b"x" * (guard.MAX_BYTES + 1), set())


def test_ci_compose_has_no_production_mounts_ports_or_runtime_dependencies():
    config = docker.configuration()
    for service in config["services"].values():
        assert set(service) == {"build", "image", "platform"}
        assert all("@sha256:" in image for image in service["build"]["args"].values())
    assert config["name"] != "resilientinspect"
