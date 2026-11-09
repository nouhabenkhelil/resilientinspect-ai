"""EfficientNet-B0 binaire : scratch, features gelees et fine-tuning partiel."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torchvision.models import EfficientNet_B0_Weights, efficientnet_b0

VARIANTS = ("T0", "T1", "T2")
IMAGENET_ENUM = "EfficientNet_B0_Weights.IMAGENET1K_V1"
IMAGENET_URL = "https://download.pytorch.org/models/efficientnet_b0_rwightman-7f5810bc.pth"
IMAGENET_SHA256_PREFIX = "7f5810bc"
IMAGENET_SHA256 = "7f5810bc96def8f7552d5b7e68d53c4786f81167d28291b21c0d90e1fca14934"
GRADCAM_TARGET = "features.8.0"
PROJECT = Path(__file__).resolve().parents[2]
WEIGHT_CACHE = PROJECT / "artifacts/transfer_weights"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_imagenet_state(path: Path | None, allow_download: bool) -> tuple[dict[str, torch.Tensor], dict[str, Any]]:
    """Poids officiels verifies, sans telechargement implicite ni cache global."""
    weights = EfficientNet_B0_Weights.IMAGENET1K_V1
    if weights.url != IMAGENET_URL:
        raise ValueError("URL des poids ImageNet differente du protocole fige.")
    if path is None:
        path = WEIGHT_CACHE / IMAGENET_URL.rsplit("/", 1)[-1]
        if not path.exists():
            if not allow_download:
                raise ValueError("Poids ImageNet absents : fournir --imagenet-weights ou autoriser explicitement le telechargement.")
            if WEIGHT_CACHE.resolve() != WEIGHT_CACHE.absolute():
                raise ValueError("Cache ImageNet via lien/jonction refuse.")
            WEIGHT_CACHE.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".pth.download")
            try:
                torch.hub.download_url_to_file(IMAGENET_URL, str(temporary), hash_prefix=IMAGENET_SHA256_PREFIX, progress=False)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("Fichier de poids ImageNet absent.")
    digest = _sha256(path)
    if digest != IMAGENET_SHA256:
        raise ValueError("Empreinte des poids ImageNet incompatible avec IMAGENET1K_V1.")
    state = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(state, dict) or not state:
        raise ValueError("Poids ImageNet invalides.")
    return state, {"source": "imagenet", "enum": IMAGENET_ENUM, "url": IMAGENET_URL,
                   "sha256": digest, "local_path": str(path), "checksum_prefix_verified": True}


class TransferClassifier(nn.Module):
    """Meme tete Dropout(0.2)/Linear(1280,1) pour toutes les conditions.

    Les stages geles restent en eval pendant train(), y compris BatchNorm et
    stochastic depth. T2 degele seulement features[6], [7] et [8].
    """

    def __init__(self, variant: str, *, seed: int = 42,
                 imagenet_state: dict[str, torch.Tensor] | None = None,
                 weight_provenance: dict[str, Any] | None = None) -> None:
        super().__init__()
        if variant not in VARIANTS or type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError("Variante T0/T1/T2 et seed entier valide requis.")
        self.variant, self.seed = variant, seed
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            backbone = efficientnet_b0(weights=None)
        if imagenet_state is not None:
            backbone.load_state_dict(imagenet_state, strict=True)
        self.features = backbone.features
        self.avgpool = backbone.avgpool
        with torch.random.fork_rng(devices=[]):
            # Initialisation de tete independante de la consommation RNG du backbone.
            torch.manual_seed(seed)
            self.classifier = nn.Sequential(nn.Dropout(0.2), nn.Linear(1280, 1))
        self.weight_provenance = dict(weight_provenance or {"source": "random", "seed": seed})
        self.unfrozen_feature_stages = list(range(len(self.features))) if variant == "T0" else ([6, 7, 8] if variant == "T2" else [])
        for index, stage in enumerate(self.features):
            stage.requires_grad_(index in self.unfrozen_feature_stages)
        self.train()

    def train(self, mode: bool = True) -> "TransferClassifier":
        super().train(mode)
        if mode:
            for index, stage in enumerate(self.features):
                if index not in self.unfrozen_feature_stages:
                    stage.eval()
        return self

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        if images.ndim != 4 or images.shape[1] != 3 or not images.is_floating_point():
            raise ValueError("Entree RGB BCHW flottante requise.")
        return self.classifier(torch.flatten(self.avgpool(self.features(images)), 1)).squeeze(1)


def build_transfer_model(variant: str, *, seed: int = 42, imagenet_weights: Path | None = None,
                         allow_download: bool = False) -> TransferClassifier:
    if variant not in VARIANTS:
        raise ValueError("Variante inconnue : T0, T1 ou T2 requis.")
    if variant == "T0":
        if imagenet_weights is not None or allow_download:
            raise ValueError("T0 exige une initialisation aleatoire, sans poids ImageNet.")
        return TransferClassifier(variant, seed=seed)
    state, provenance = _load_imagenet_state(imagenet_weights, allow_download)
    model = TransferClassifier(variant, seed=seed, imagenet_state=state, weight_provenance=provenance)
    if not all(torch.isfinite(value).all() for value in model.state_dict().values()):
        raise ValueError("Poids ImageNet non finis.")
    return model


def parameter_groups(model: TransferClassifier, head_lr: float = 1e-3,
                     backbone_lr: float = 1e-4) -> list[dict[str, Any]]:
    backbone = [p for p in model.features.parameters() if p.requires_grad]
    if (type(head_lr) not in (int, float) or not math.isfinite(head_lr) or head_lr <= 0
            or type(backbone_lr) not in (int, float) or not math.isfinite(backbone_lr)
            or backbone_lr < 0 or (backbone and backbone_lr == 0)):
        raise ValueError("Learning rates finis positifs requis ; zero permis pour un backbone entierement gele.")
    groups = [{"name": "head", "params": [p for p in model.classifier.parameters() if p.requires_grad], "lr": head_lr}]
    if backbone:
        groups.append({"name": "backbone", "params": backbone, "lr": backbone_lr if model.variant == "T2" else head_lr})
    return groups


def trainable_parameter_report(model: TransferClassifier) -> dict[str, Any]:
    total = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    return {"variant": model.variant, "total_parameters": total, "trainable_parameters": trainable,
            "frozen_parameters": total - trainable,
            "head_parameters": sum(p.numel() for p in model.classifier.parameters()),
            "trainable_backbone_parameters": sum(p.numel() for p in model.features.parameters() if p.requires_grad),
            "trainable_parameter_names": [name for name, p in model.named_parameters() if p.requires_grad],
            "unfrozen_feature_stages": list(model.unfrozen_feature_stages)}


def load_transfer_checkpoint(path: Path, device: str | torch.device = "cpu") -> TransferClassifier:
    """Recharge les poids du run sans recharger ou telecharger ImageNet."""
    saved = torch.load(path, map_location="cpu", weights_only=True)
    if (not isinstance(saved, dict) or saved.get("variant") not in VARIANTS
            or saved.get("category") not in ("bottle", "hazelnut", "leather")
            or saved.get("scope") not in ("full", "smoke")
            or type(saved.get("epoch")) is not int or saved["epoch"] < 1
            or type(saved.get("val_loss")) not in (int, float) or not math.isfinite(saved["val_loss"])
            or saved["val_loss"] < 0):
        raise ValueError("Metadonnees du checkpoint de transfert invalides.")
    config, provenance = saved.get("effective_config", {}), saved.get("weight_provenance", {})
    if (not isinstance(config, dict) or config.get("variant") != saved["variant"]
            or config.get("category", saved["category"]) != saved["category"]
            or config.get("seed", saved.get("seed")) != saved.get("seed")
            or not isinstance(provenance, dict)):
        raise ValueError("Configuration effective de transfert incoherente.")
    if saved["variant"] == "T0":
        if provenance.get("source") != "random" or provenance.get("seed") != saved.get("seed"):
            raise ValueError("Provenance aleatoire T0 incoherente.")
    elif (provenance.get("source") != "imagenet" or provenance.get("enum") != IMAGENET_ENUM
          or provenance.get("url") != IMAGENET_URL or not isinstance(provenance.get("sha256"), str)
          or provenance["sha256"] != IMAGENET_SHA256):
        raise ValueError("Provenance ImageNet absente ou incompatible.")
    for name in ("manifest_sha256", "synthetic_plan_sha256"):
        digest = saved.get(name)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"Empreinte {name} invalide.")
    model = TransferClassifier(saved["variant"], seed=saved["seed"], weight_provenance=provenance)
    model.load_state_dict(saved["model_state_dict"], strict=True)
    if not all(torch.isfinite(value).all() for value in model.state_dict().values()):
        raise ValueError("Poids de transfert non finis.")
    return model.to(device).eval().requires_grad_(False)
