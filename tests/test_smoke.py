"""Verifications du socle sans donnees, reseau ni entrainement."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = PROJECT_ROOT / "scripts" / "smoke_test.py"


@pytest.fixture(scope="module")
def smoke_module():
    """Charger le script sans modifier le chemin d'import du projet."""
    spec = importlib.util.spec_from_file_location("project_smoke", SMOKE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def synthetic_config():
    return {
        "schema_version": 1,
        "phase": 0,
        "dataset": {
            "name": "mvtec_ad",
            "root_env": "MVTEC_AD_ROOT",
            "default_root": "nonexistent_dataset_do_not_create",
            "download": False,
            "categories": {
                "status": "provisional",
                "candidates": ["hazelnut", "bottle", "leather"],
                "confirmed": [],
            },
        },
    }


def write_config(tmp_path, config):
    path = tmp_path / "dataset.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def test_dataset_declaration_confirms_user_categories_for_audit(smoke_module):
    config = smoke_module.validate_dataset_config(PROJECT_ROOT / "configs" / "dataset.yaml")
    assert config["phase"] == 1
    assert config["dataset"]["download"] is False
    categories = config["dataset"]["categories"]
    assert categories["status"] == "confirmed"
    assert categories["confirmed"] == ["bottle", "hazelnut", "leather"]
    assert set(categories["candidates"]) == {"hazelnut", "bottle", "leather"}


def test_config_validation_does_not_require_dataset(smoke_module, tmp_path, synthetic_config):
    path = write_config(tmp_path, synthetic_config)
    missing_dataset = tmp_path / synthetic_config["dataset"]["default_root"]
    assert not missing_dataset.exists()
    assert smoke_module.validate_dataset_config(path) == synthetic_config
    assert not missing_dataset.exists()


@pytest.mark.parametrize(
    ("field_path", "invalid_value"),
    [
        (("phase",), 2),
        (("dataset", "download"), True),
        (("dataset", "categories", "status"), "confirmed"),
        (("dataset", "categories", "confirmed"), ["hazelnut"]),
        (("dataset", "categories", "candidates"), ["hazelnut", "hazelnut"]),
        (("dataset", "categories", "candidates"), []),
        (("dataset", "categories", "candidates"), [""]),
    ],
    ids=["later-phase", "download", "confirmed-status", "confirmed-category", "duplicates", "empty-list", "empty-name"],
)
def test_reject_unsafe_or_ambiguous_config(
    smoke_module, tmp_path, synthetic_config, field_path, invalid_value
):
    config = deepcopy(synthetic_config)
    target = config
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = invalid_value
    with pytest.raises(ValueError):
        smoke_module.validate_dataset_config(write_config(tmp_path, config))


@pytest.fixture
def synthetic_phase_one_config(synthetic_config):
    config = deepcopy(synthetic_config)
    config["phase"] = 1
    config["dataset"]["categories"].update(
        status="confirmed", confirmed=["bottle", "hazelnut", "leather"]
    )
    return config


@pytest.mark.parametrize("confirmed", [["bottle"], ["bottle", "hazelnut", "leather"]])
def test_phase_one_accepts_confirmed_candidates_without_reading_data(
    smoke_module, tmp_path, synthetic_phase_one_config, confirmed
):
    config = deepcopy(synthetic_phase_one_config)
    config["dataset"]["categories"]["confirmed"] = confirmed
    missing_dataset = tmp_path / config["dataset"]["default_root"]
    assert not missing_dataset.exists()
    assert smoke_module.validate_dataset_config(write_config(tmp_path, config)) == config
    assert not missing_dataset.exists()


@pytest.mark.parametrize(
    ("field_path", "invalid_value"),
    [
        (("phase",), True),
        (("dataset", "download"), True),
        (("dataset", "categories", "status"), "provisional"),
        (("dataset", "categories", "confirmed"), []),
        (("dataset", "categories", "confirmed"), ["bottle", "bottle"]),
        (("dataset", "categories", "confirmed"), ["unknown_category"]),
        (("dataset", "categories", "confirmed"), [""]),
        (("dataset", "categories", "confirmed"), [None]),
        (("dataset", "categories", "confirmed"), "bottle"),
    ],
    ids=["boolean-phase", "download", "provisional", "empty", "duplicates", "unknown", "empty-name", "null-name", "scalar"],
)
def test_phase_one_rejects_unsafe_or_ambiguous_config(
    smoke_module, tmp_path, synthetic_phase_one_config, field_path, invalid_value
):
    config = deepcopy(synthetic_phase_one_config)
    target = config
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = invalid_value
    with pytest.raises(ValueError):
        smoke_module.validate_dataset_config(write_config(tmp_path, config))


@pytest.mark.parametrize("content", ["dataset: [unterminated", "scalar", "- item"], ids=["syntax", "scalar", "list"])
def test_reject_invalid_yaml_document(smoke_module, tmp_path, content):
    path = tmp_path / "invalid.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        smoke_module.validate_dataset_config(path)


def test_missing_config_is_an_explicit_error(smoke_module, tmp_path):
    with pytest.raises(ValueError):
        smoke_module.validate_dataset_config(tmp_path / "missing.yaml")


def test_collect_report_accepts_optional_dependencies(smoke_module):
    report = smoke_module.collect_report(PROJECT_ROOT)
    assert report["phase"] == 1
    assert report["status"] == "ok", report
    assert isinstance(report["checks"], dict) and report["checks"]
    assert all(check["status"] in {"ok", "not_installed"} for check in report["checks"].values()), report


def test_smoke_cli_works_outside_repository(tmp_path):
    result = subprocess.run(
        [sys.executable, "-I", str(SMOKE_SCRIPT)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["phase"] == 1
    assert report["status"] == "ok", report
    assert isinstance(report["checks"], dict) and report["checks"]
    assert all(check["status"] in {"ok", "not_installed"} for check in report["checks"].values()), report


def test_installed_package_imports_outside_repository(tmp_path):
    probe = (
        "import importlib, json; "
        "names = ['resilientinspect', 'resilientinspect.data', 'resilientinspect.models', "
        "'resilientinspect.training', 'resilientinspect.evaluation', "
        "'resilientinspect.export', 'resilientinspect.mlops']; "
        "print(json.dumps({name: importlib.import_module(name).__file__ for name in names}))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    imported = json.loads(result.stdout)
    assert len(imported) == 7
    for source in imported.values():
        assert Path(source).resolve().is_relative_to(PROJECT_ROOT / "src")


def test_git_ignores_datasets_checkpoints_and_secrets():
    ignored_paths = {
        "data/raw/mvtec_ad/hazelnut/train/good/sample.png",
        "data/processed/cache.bin",
        "datasets/mvtec_ad/sample.png",
        "outputs/checkpoints/b0.pt",
        "artifacts/checkpoints/a1.pth",
        "local/model.ckpt",
        ".env",
        ".env.local",
        "secrets/api_token.txt",
        ".aws/credentials",
    }
    allowed_paths = {".env.example", "data/raw/.gitkeep", "artifacts/checkpoints/.gitkeep"}
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        # Le mode binaire NUL evite la conversion LF -> CRLF sous Windows.
        input=("\0".join(sorted(ignored_paths | allowed_paths)) + "\0").encode("utf-8"),
        cwd=PROJECT_ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.decode("utf-8").split("\0")) - {""} == ignored_paths
