"""Diagnostic de phase 0, sans donnees, reseau ni entrainement.

Une installation PyTorch existante est sondee avec de petits tenseurs ; son
absence est informative et ne bloque pas le socle Python de la phase 0.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import struct
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRECTORIES = (
    ".github/workflows", "configs", "data/raw", "data/processed",
    "data/manifests", "src/data", "src/models", "src/training",
    "src/evaluation", "src/export", "src/mlops", "backend/app/routes",
    "backend/tests", "frontend/src/components", "frontend/src/pages",
    "frontend/src/services", "frontend/src/styles", "tests", "scripts",
    "reports/eda", "reports/figures", "reports/tables", "reports/experiments",
    "reports/latex", "artifacts",
)


def validate_dataset_config(path: Path) -> dict[str, Any]:
    """Valide la declaration provisoire, sans acceder au dataset."""
    import yaml

    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"Configuration YAML illisible : {exc}") from exc

    if not isinstance(config, dict):
        raise ValueError("La configuration doit etre un mapping YAML.")
    if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        raise ValueError("schema_version doit valoir 1.")
    if type(config.get("phase")) is not int or config["phase"] != 0:
        raise ValueError("Seule la phase 0 est autorisee.")
    dataset = config.get("dataset")
    if not isinstance(dataset, dict) or dataset.get("name") != "mvtec_ad":
        raise ValueError("Le dataset declare doit etre mvtec_ad.")
    if dataset.get("download") is not False:
        raise ValueError("download doit rester false en phase 0.")
    categories = dataset.get("categories")
    if not isinstance(categories, dict):
        raise ValueError("La declaration des categories est absente.")
    if categories.get("status") != "provisional" or categories.get("confirmed") != []:
        raise ValueError("Les categories doivent rester provisoires et non confirmees.")
    candidates = categories.get("candidates")
    if (
        not isinstance(candidates, list)
        or not candidates
        or any(not isinstance(name, str) or not name.strip() for name in candidates)
        or len(set(candidates)) != len(candidates)
    ):
        raise ValueError("Les categories candidates doivent etre des noms uniques non vides.")
    return config


def probe_torch() -> dict[str, Any]:
    """Sonde facultative ; ne telecharge aucun poids et ne construit aucun modele."""
    try:
        if importlib.util.find_spec("torch") is None:
            return {
                "status": "not_installed",
                "cuda_available": None,
                "detail": "PyTorch absent ; CUDA non teste. Installation differee.",
            }
        torch = importlib.import_module("torch")
        cpu_result = torch.ones((2, 2), device="cpu").sum().item()
        if cpu_result != 4.0:
            raise RuntimeError("Echec du calcul tensoriel CPU elementaire.")
        cuda_available = bool(torch.cuda.is_available())
        result = {
            "status": "ok",
            "version": str(torch.__version__),
            "cpu_tensor_check": True,
            "cuda_build": torch.version.cuda,
            "cuda_available": cuda_available,
            "cuda_devices": [],
        }
        if cuda_available:
            for index in range(torch.cuda.device_count()):
                torch.ones(1, device=f"cuda:{index}").sum().item()
                result["cuda_devices"].append(torch.cuda.get_device_name(index))
        return result
    except Exception as exc:
        return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}


def _git(*arguments: str, root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=10, check=True,
    )
    return completed.stdout.strip()


def collect_report(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Collecte uniquement les preuves verifiables du socle local."""
    checks: dict[str, dict[str, Any]] = {}
    checks["python"] = {
        "status": "ok" if sys.version_info[:2] == (3, 11) and struct.calcsize("P") == 8 else "error",
        "version": platform.python_version(),
        "executable": sys.executable,
        "bits": struct.calcsize("P") * 8,
    }
    try:
        package = importlib.import_module("resilientinspect")
        installed_version = importlib.metadata.version("resilientinspect-ai")
        if package.__version__ != installed_version:
            raise RuntimeError("Versions du paquet et des metadonnees incoherentes.")
        for module in ("data", "models", "training", "evaluation", "export", "mlops"):
            importlib.import_module(f"resilientinspect.{module}")
        checks["package"] = {"status": "ok", "version": installed_version}
    except Exception as exc:
        checks["package"] = {"status": "error", "detail": str(exc)}
    try:
        config = validate_dataset_config(project_root / "configs" / "dataset.yaml")
        checks["dataset_config"] = {
            "status": "ok",
            "categories_status": config["dataset"]["categories"]["status"],
            "candidates": config["dataset"]["categories"]["candidates"],
            "confirmed": config["dataset"]["categories"]["confirmed"],
            "data_accessed": False,
        }
    except Exception as exc:
        checks["dataset_config"] = {"status": "error", "detail": str(exc)}
    missing = [name for name in REQUIRED_DIRECTORIES if not (project_root / name).is_dir()]
    checks["structure"] = {"status": "error" if missing else "ok", "missing": missing}
    try:
        version = _git("--version", root=project_root)
        if _git("rev-parse", "--is-inside-work-tree", root=project_root) != "true":
            raise RuntimeError("Le projet doit etre dans un depot Git.")
        try:
            head = _git("rev-parse", "--verify", "HEAD", root=project_root)
        except subprocess.CalledProcessError:
            head = None  # Un depot nouvellement initialise peut ne contenir aucun commit.
        checks["git"] = {
            "status": "ok", "version": version, "head": head,
            "branch": _git("branch", "--show-current", root=project_root),
        }
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        checks["git"] = {"status": "error", "detail": str(exc)}
    checks["pytorch"] = probe_torch()
    return {
        "phase": 0,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "error" if any(check["status"] == "error" for check in checks.values()) else "ok",
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpu_count": os.cpu_count(),
        },
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    report = collect_report()
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
