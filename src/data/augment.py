"""Photometrie train/good seulement ; geometrie et originaux preserves."""

from __future__ import annotations

import math
from typing import Any

import torch
from torch.utils.data import Dataset

from .dataset import MVTecDataset


def validate_augmentation(config: dict[str, Any]) -> None:
    if not isinstance(config, dict) or set(config) != {"enabled", "probability", "brightness", "contrast"}:
        raise ValueError("Schema d'augmentation incomplet ou inconnu.")
    if type(config["enabled"]) is not bool:
        raise ValueError("enabled doit etre booleen.")
    for key in ("probability", "brightness", "contrast"):
        value = config[key]
        bound = 1 if key == "probability" else 0.2
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= bound:
            raise ValueError(f"Augmentation {key} hors des bornes prudentes [0,{bound}].")


class TrainAugmentedDataset(Dataset):
    """Tirage stateless(seed,epoch,index), sans influence de l'initialisation CNN.

    L'image augmentee sert aussi de cible de reconstruction ; pas de denoising.
    Aucun flip, rotation, crop, defaut synthetique ou changement de masque.
    """

    def __init__(self, dataset: MVTecDataset, config: dict[str, Any], seed: int) -> None:
        validate_augmentation(config)
        if any(row["split"] != "train" or row["source_split"] != "train" or row["label"] != "0" or row["mask_path"]
               for row in dataset.rows):
            raise ValueError("Augmentation reservee exclusivement a train/good.")
        self.dataset, self.config, self.seed, self.epoch = dataset, dict(config), seed, 0
        self.rows = dataset.rows

    def __len__(self) -> int:
        return len(self.dataset)

    def set_epoch(self, epoch: int) -> None:
        if type(epoch) is not int or epoch < 0:
            raise ValueError("Epoque d'augmentation invalide.")
        self.epoch = epoch

    def __getitem__(self, index: int) -> dict[str, Any]:
        sample = self.dataset[index]
        generator = torch.Generator().manual_seed(self.seed + self.epoch * len(self) + index)
        if not self.config["enabled"] or torch.rand((), generator=generator).item() >= self.config["probability"]:
            return sample
        brightness = 1 + (2 * torch.rand((), generator=generator).item() - 1) * self.config["brightness"]
        contrast = 1 + (2 * torch.rand((), generator=generator).item() - 1) * self.config["contrast"]
        valid = sample["valid_mask"]
        image = sample["image"] * brightness
        mean = (image * valid).sum() / (3 * valid.sum())
        sample = dict(sample)
        sample["image"] = ((image - mean) * contrast + mean).clamp(0, 1) * valid
        return sample
