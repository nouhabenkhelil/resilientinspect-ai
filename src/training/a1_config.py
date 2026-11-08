"""Contrat A1 et rechargement strict ; boucle d'apprentissage partagee dans train_ae."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import torch

from resilientinspect.data.augment import validate_augmentation
from resilientinspect.models.autoencoder_improved import ImprovedAutoencoder
from .losses import ReconstructionLoss


def validate_a1_config(config: dict[str, Any], training_loss: str) -> None:
    if not isinstance(config, dict) or set(config) != {"schema_version", "model", "loss", "augmentation"} or config["schema_version"] != 1:
        raise ValueError("Schema architecture A1 invalide.")
    model = config["model"]
    if (set(model) != {"name", "class", "kwargs", "input_shape", "output_activation", "skip_resolutions"}
            or model["name"] != "A1" or model["class"] != "resilientinspect.models.autoencoder_improved.ImprovedAutoencoder"
            or model["input_shape"] != [3, 256, 256] or model["output_activation"] != "sigmoid"
            or model["skip_resolutions"] != [32, 64]
            or set(model["kwargs"]) != {"channels", "residual_blocks", "skip_connections", "skip_scale"}):
        raise ValueError("Architecture A1 inconnue ou metadonnees incoherentes.")
    loss = config["loss"]
    if not isinstance(loss, dict) or set(loss) != {"name", "l1_weight", "ssim_weight", "window_size", "sigma"} or loss["name"] != training_loss:
        raise ValueError("Perte A1 incoherente entre configurations.")
    ReconstructionLoss(**loss)
    validate_augmentation(config["augmentation"])


def load_a1_checkpoint(path: Path, device: str | torch.device = "cpu") -> ImprovedAutoencoder:
    """Poids et architecture sauvegardee, sans optimiseur ni reprise implicite."""
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if checkpoint.get("variant") != "A1" or checkpoint.get("scope") not in ("full", "smoke"):
        raise ValueError("Checkpoint A1 complet ou smoke requis.")
    architecture = checkpoint["architecture"]
    effective = checkpoint["effective_config"]
    if (effective.get("variant") != "A1" or effective.get("category") != checkpoint.get("category")
            or effective.get("scope") != checkpoint["scope"] or effective.get("architecture") != architecture):
        raise ValueError("Metadonnees A1 incoherentes.")
    validate_a1_config(architecture, effective["training"]["loss"])
    model = ImprovedAutoencoder(**architecture["model"]["kwargs"])
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    if not all(torch.isfinite(value).all() for value in model.state_dict().values()):
        raise ValueError("Poids A1 non finis.")
    for skip in model.skips.values():
        if not torch.isclose(skip.scale, torch.tensor(architecture["model"]["kwargs"]["skip_scale"], dtype=skip.scale.dtype)):
            raise ValueError("Echelle du skip differente de l'architecture sauvegardee.")
    return model.to(device).eval().requires_grad_(False)
