"""Selection et controle des artefacts A1 complets, sans inference ni Dataset."""

from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
import re
from typing import Any

import torch
import yaml

from resilientinspect.training import a1_config
from resilientinspect.models.autoencoder_improved import ImprovedAutoencoder
from .evaluate_ae import CATEGORIES, Checkpoint, _sha256


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _finite_loss(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _metadata(path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """Verifie les copies de configuration et la provenance sans lire de donnees."""
    summary = _json(path.with_name("summary.json"))
    effective = yaml.safe_load(path.with_name("effective_config.yaml").read_text(encoding="utf-8"))
    category = path.parent.parent.name
    run_id = path.parent.name.removeprefix("full_")
    if (summary.get("status") != "completed" or summary.get("variant") != "A1"
            or summary.get("scope") != "full" or summary.get("category") != category
            or summary.get("run_id") != run_id or summary.get("selection_split") != "val"
            or summary.get("test_used") is not False or effective.get("variant") != "A1"
            or effective.get("scope") != "full" or effective.get("category") != category
            or effective.get("max_batches_per_split", "missing") is not None):
        raise ValueError(f"Run complet A1 invalide : {path.parent}")
    epoch, completed = summary.get("best_epoch"), summary.get("epochs_completed")
    if (type(epoch) is not int or type(completed) is not int or not 1 <= epoch <= completed
            or not _finite_loss(summary.get("best_val_loss"))
            or not re.fullmatch(r"[0-9a-f]{64}", summary.get("manifest_sha256", ""))):
        raise ValueError("Epoque, perte ou manifeste A1 invalide.")
    architecture = effective["architecture"]
    a1_config.validate_a1_config(architecture, effective["training"]["loss"])
    if type(effective.get("seed")) is not int:
        raise ValueError("Seed A1 absent ou invalide.")
    history = summary.get("history")
    if history is not None:
        if (len(history) != completed or [row.get("epoch") for row in history] != list(range(1, completed + 1))
                or any(not _finite_loss(row.get("val_loss")) for row in history)
                or history[epoch - 1]["val_loss"] != summary["best_val_loss"]
                or min(row["val_loss"] for row in history) != summary["best_val_loss"]):
            raise ValueError("Historique et meilleur checkpoint A1 incoherents.")
    hashes = {"summary.json": _sha256(path.with_name("summary.json")),
              "effective_config.yaml": _sha256(path.with_name("effective_config.yaml"))}
    architecture_path = path.with_name("architecture.yaml")
    if architecture_path.exists():
        if yaml.safe_load(architecture_path.read_text(encoding="utf-8")) != architecture:
            raise ValueError("Architecture sauvegardee differente de la configuration effective.")
        hashes[architecture_path.name] = _sha256(architecture_path)
    provenance_path = path.with_name("provenance.json")
    if provenance_path.exists():
        provenance = _json(provenance_path)
        for key in ("manifest_sha256", "source_sha256", "git_sha", "git_dirty"):
            if provenance.get(key) != summary.get(key):
                raise ValueError(f"Provenance A1 incoherente : {key}.")
        hashes[provenance_path.name] = _sha256(provenance_path)
    for original, digest in summary.get("source_sha256", {}).items():
        name = original.replace("\\", "/").rsplit("/", 1)[-1]
        source = path.parent / "source" / name
        if source.is_symlink() or not source.is_file() or _sha256(source) != digest:
            raise ValueError(f"Source A1 absent ou modifie : {name}.")
        hashes[f"source/{name}"] = digest
    usage_path = path.with_name("data_usage.json")
    if usage_path.exists():
        usage = _json(usage_path)
        if (set(usage) != {"train", "val"} or any(not isinstance(usage[split], list) or not usage[split] for split in usage)
                or set(usage["train"]) & set(usage["val"])
                or any(not name.startswith(f"{category}/train/good/") or ".." in name.split("/")
                       for names in usage.values() for name in names)):
            raise ValueError("Usage A1 exige train/val normaux disjoints, sans test.")
        if history is not None and any(row.get(f"{split}_images") != len(usage[split])
                                       for row in history for split in usage):
            raise ValueError("Effectifs complets incoherents avec data_usage A1.")
        hashes[usage_path.name] = _sha256(usage_path)
    if _sha256(path) != summary.get("checkpoint_sha256"):
        raise ValueError(f"Empreinte checkpoint A1 invalide : {path}")
    return summary, effective, hashes


def _payload(checkpoint: Checkpoint, expected_manifest: str) -> dict[str, Any]:
    path = Path(checkpoint.path)
    summary, effective, _ = _metadata(path)
    if (checkpoint.category not in CATEGORIES or summary["category"] != checkpoint.category
            or summary["run_id"] != checkpoint.run_id or summary["best_epoch"] != checkpoint.best_epoch
            or summary["checkpoint_sha256"] != checkpoint.sha256
            or summary["manifest_sha256"] != checkpoint.manifest_sha256
            or checkpoint.manifest_sha256 != expected_manifest):
        raise ValueError("Checkpoint A1 ou manifeste different de la selection.")
    saved = torch.load(path, map_location="cpu", weights_only=True)
    if (saved.get("variant") != "A1" or saved.get("scope") != "full"
            or saved.get("category") != checkpoint.category or saved.get("manifest_sha256") != expected_manifest
            or type(saved.get("epoch")) is not int or saved.get("epoch") != checkpoint.best_epoch
            or not _finite_loss(saved.get("val_loss")) or saved.get("val_loss") != summary["best_val_loss"]
            or saved.get("seed") != effective["seed"] or saved.get("effective_config") != effective
            or saved.get("architecture") != effective["architecture"]):
        raise ValueError("Contenu du checkpoint A1 incoherent avec ses metadonnees.")
    return saved


def discover_checkpoints(runs_root: Path) -> tuple[dict[str, Checkpoint], list[dict[str, str]]]:
    """Trois category/full_*/best.pt ; smoke et copies MLflow exclus avant chargement."""
    root = Path(runs_root).resolve()
    candidates: dict[str, list[Checkpoint]] = {category: [] for category in CATEGORIES}
    excluded = []
    for path in sorted(root.rglob("best.pt")):
        parts = path.relative_to(root).parts
        reason = None
        if any(part.lower() in ("mlartifacts", "mlruns") for part in parts):
            reason = "mlflow_copy"
        elif any(part.startswith("smoke_") for part in parts):
            reason = "smoke"
        elif len(parts) != 3 or parts[0] not in CATEGORIES or not parts[1].startswith("full_"):
            reason = "non_canonical_layout"
        if reason:
            excluded.append({"path": str(path), "reason": reason})
            continue
        if any(item.is_symlink() for item in (path, path.parent, path.parent.parent)):
            raise ValueError("Checkpoint A1 canonique via lien symbolique refuse.")
        summary = _json(path.with_name("summary.json"))
        effective = yaml.safe_load(path.with_name("effective_config.yaml").read_text(encoding="utf-8"))
        if summary.get("scope") == "smoke" or effective.get("scope") == "smoke":
            excluded.append({"path": str(path), "reason": "smoke_metadata"})
            continue
        summary, _, _ = _metadata(path)
        checkpoint = Checkpoint(parts[0], str(path), summary["run_id"], summary["checkpoint_sha256"],
                                summary["manifest_sha256"], summary["best_epoch"])
        _payload(checkpoint, checkpoint.manifest_sha256)
        candidates[parts[0]].append(checkpoint)
    selected = {}
    for category, items in candidates.items():
        if not items:
            raise ValueError(f"Aucun checkpoint A1 complet canonique pour {category}.")
        if len({item.sha256 for item in items}) != 1:
            raise ValueError(f"Plusieurs runs complets A1 distincts pour {category} : selection explicite requise.")
        selected[category] = items[0]
        excluded.extend({"path": item.path, "reason": "identical_checkpoint_copy"} for item in items[1:])
    return selected, excluded


def load_model(checkpoint: Checkpoint, device: torch.device, expected_manifest: str) -> ImprovedAutoencoder:
    """Charge uniquement via le contrat strict A1, sans optimiseur ni apprentissage."""
    _payload(checkpoint, expected_manifest)
    return a1_config.load_a1_checkpoint(Path(checkpoint.path), device)


def inspection_metadata(checkpoint: Checkpoint) -> dict[str, Any]:
    _payload(checkpoint, checkpoint.manifest_sha256)
    summary, effective, hashes = _metadata(Path(checkpoint.path))
    environment_path = Path(checkpoint.path).with_name("environment.json")
    environment = _json(environment_path) if environment_path.exists() else None
    if environment_path.exists():
        hashes[environment_path.name] = _sha256(environment_path)
    return {**asdict(checkpoint), "variant": "A1", "scope": "full", "status": summary["status"],
            "epochs_completed": summary["epochs_completed"], "best_val_loss": summary["best_val_loss"],
            "seed": effective["seed"], "architecture": effective["architecture"], "training": effective["training"],
            "selection_split": "val", "test_used": False, "training_environment": environment,
            "verified_artifact_sha256": hashes}
