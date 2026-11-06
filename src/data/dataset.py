"""Dataset PyTorch MVTec AD : RGB [0,1], masque binaire, letterbox en memoire."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

from PIL import Image
import torch
from torch.utils.data import Dataset

from .audit import _sha256
from .prepare import SPLITS, read_manifest, safe_data_path


def letterbox_pair(
    image: Image.Image, mask: Image.Image, size: tuple[int, int] = (256, 256),
) -> dict[str, Any]:
    """Meme geometrie pour RGB et masque ; size=(hauteur, largeur), sans crop."""
    if len(size) != 2 or any(type(value) is not int or value <= 0 for value in size):
        raise ValueError("Taille cible attendue : deux entiers strictement positifs.")
    if image.size != mask.size:
        raise ValueError("Dimensions natives image/masque differentes.")
    if mask.mode not in ("1", "L"):
        raise ValueError("Un masque doit etre mono-canal 1 ou L.")
    values = {index for index, count in enumerate(mask.histogram()) if count}
    if not values.issubset({0, 1}) and not values.issubset({0, 255}):
        raise ValueError("Masque non binaire, valeurs attendues 0/1 ou 0/255.")
    target_h, target_w = size
    original_w, original_h = image.size
    scale = min(target_h / original_h, target_w / original_w)
    new_w = max(1, min(target_w, math.floor(original_w * scale + 0.5)))
    new_h = max(1, min(target_h, math.floor(original_h * scale + 0.5)))
    left, top = (target_w - new_w) // 2, (target_h - new_h) // 2
    rgb = Image.new("RGB", (target_w, target_h), 0)
    binary = Image.new("L", (target_w, target_h), 0)
    rgb.paste(image.convert("RGB").resize((new_w, new_h), Image.Resampling.BILINEAR), (left, top))
    binary.paste(mask.convert("L").resize((new_w, new_h), Image.Resampling.NEAREST), (left, top))
    image_tensor = torch.frombuffer(bytearray(rgb.tobytes()), dtype=torch.uint8)
    image_tensor = image_tensor.reshape(target_h, target_w, 3).permute(2, 0, 1).to(torch.float32).div_(255).contiguous()
    mask_tensor = torch.frombuffer(bytearray(binary.tobytes()), dtype=torch.uint8)
    mask_tensor = mask_tensor.reshape(1, target_h, target_w).gt(0).to(torch.float32)
    valid = torch.zeros((1, target_h, target_w), dtype=torch.float32)
    valid[:, top:top + new_h, left:left + new_w] = 1
    return {
        "image": image_tensor, "mask": mask_tensor, "valid_mask": valid,
        "original_size": torch.tensor([original_h, original_w]),
        "resized_size": torch.tensor([new_h, new_w]),
        "padding": torch.tensor([top, target_h - new_h - top, left, target_w - new_w - left]),
    }


class MVTecDataset(Dataset):
    """Un split explicite obligatoire ; aucun calcul de statistiques ou augmentation.

    Utiliser de preference manifest.csv pour valider la disjonction globale.
    Les fichiers ne sont ouverts qu'a __getitem__, dans le split selectionne.
    """

    def __init__(
        self, manifest_path: Path, root: Path, *, split: str,
        categories: Sequence[str] | None = None,
        image_size: tuple[int, int] = (256, 256), verify_hashes: bool = True,
    ) -> None:
        if split not in SPLITS:
            raise ValueError("Split explicite attendu : train, val ou test.")
        if len(image_size) != 2 or any(type(value) is not int or value <= 0 for value in image_size):
            raise ValueError("Taille d'image invalide.")
        all_rows = read_manifest(manifest_path)
        available = {row["category"] for row in all_rows}
        if categories is not None and (not categories or isinstance(categories, str) or not set(categories).issubset(available)):
            raise ValueError("Selection de categories vide ou inconnue.")
        self.rows = [row for row in all_rows if row["split"] == split
                     and (categories is None or row["category"] in categories)]
        if not self.rows:
            raise ValueError("Aucune image pour le split et les categories demandes.")
        self.root = Path(root).resolve()
        self.image_size = tuple(image_size)
        self.verify_hashes = verify_hashes

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        image_path = safe_data_path(self.root, row["image_path"])
        if self.verify_hashes and _sha256(image_path) != row["sha256"]:
            raise ValueError(f"Image modifiee depuis le manifeste : {row['image_path']}")
        with Image.open(image_path) as original:
            original.load()
            image = original.convert("RGB")
        if row["mask_path"]:
            mask_path = safe_data_path(self.root, row["mask_path"])
            if self.verify_hashes and _sha256(mask_path) != row["mask_sha256"]:
                raise ValueError(f"Masque modifie depuis le manifeste : {row['mask_path']}")
            with Image.open(mask_path) as original_mask:
                original_mask.load()
                mask = original_mask.copy()
        else:
            mask = Image.new("L", image.size, 0)
        return {
            **letterbox_pair(image, mask, self.image_size),
            "label": int(row["label"]), "category": row["category"], "split": row["split"],
            "defect_type": row["defect_type"], "image_path": row["image_path"],
            "mask_path": row["mask_path"], "has_mask": bool(row["mask_path"]),
        }
