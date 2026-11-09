"""Paires normales/synthetiques figees par source, sans aucun acces au test reel."""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
import sys
from typing import Any

import torch
from torch.utils.data import Dataset
import yaml

from .audit import _linked, _sha256
from .dataset import MVTecDataset
from .prepare import read_manifest

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
GENERATOR = "localized_self_cutpaste_v1"
PROJECT = Path(__file__).resolve().parents[2]


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def validate_synthetic_config(config: dict[str, Any]) -> None:
    expected = {"schema_version", "image_size", "copies_per_source", "patch_fraction", "min_effect", "normalization"}
    if (not isinstance(config, dict) or set(config) != expected or type(config["schema_version"]) is not int
            or config["schema_version"] != 1 or config["image_size"] != [256, 256]
            or type(config["copies_per_source"]) is not int or config["copies_per_source"] != 1):
        raise ValueError("Configuration synthetique attendue : schema 1, 256x256, une copie par source.")
    fraction = config["patch_fraction"]
    if (not isinstance(fraction, list) or len(fraction) != 2
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in fraction)
            or not 0 < fraction[0] <= fraction[1] <= 0.5):
        raise ValueError("Fractions de dimensions du patch attendues dans ]0,0.5].")
    effect = config["min_effect"]
    if type(effect) not in (int, float) or not math.isfinite(effect) or not 0 < effect <= 0.5:
        raise ValueError("Effet photometrique strictement positif, au plus 0.5, requis.")
    if config["normalization"] != {"mean": list(IMAGENET_MEAN), "std": list(IMAGENET_STD)}:
        raise ValueError("Normalisation ImageNet fixe commune a T0/T1/T2 requise.")


def load_synthetic_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    validate_synthetic_config(config)
    return config


def _manifest_sha256(manifest: Path) -> str:
    digest = _sha256(manifest)
    preparation = manifest.with_name("preparation.json")
    if preparation.exists():
        frozen = json.loads(preparation.read_text(encoding="utf-8"))
        if frozen.get("manifest_sha256", {}).get(manifest.name) != digest:
            raise ValueError("Manifeste different de son empreinte figee.")
    return digest


def prepare_synthetic_plan(manifest: Path, config: dict[str, Any], seed: int = 42) -> dict[str, Any]:
    """Lit seulement les metadonnees ; les sources val et train sont disjointes.

    Chaque source donne une paire label=0/1. Son tirage est une fonction de la
    seed, du split, du chemin et du SHA source, sans dependance au modele/epoque.
    """
    validate_synthetic_config(config)
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Seed synthetique entiere dans [0,2**32[ requise.")
    manifest = Path(manifest)
    digest = _manifest_sha256(manifest)
    sources = [row for row in read_manifest(manifest) if row["split"] in ("train", "val")]
    if not sources or any(row["source_split"] != "train" or row["label"] != "0"
                          or row["defect_type"] != "good" or row["mask_path"] for row in sources):
        raise ValueError("Sources synthetiques reservees a train/good et val/good sans masque.")
    categories = sorted({row["category"] for row in sources})
    if any(not any(row["category"] == category and row["split"] == split for row in sources)
           for category in categories for split in ("train", "val")):
        raise ValueError("Chaque categorie exige des sources train et val distinctes.")
    recipes = []
    for source in sorted(sources, key=lambda row: (row["category"], row["split"], row["image_path"])):
        identity = {key: source[key] for key in ("category", "split", "image_path", "sha256")}
        source_id = hashlib.sha256(_json_bytes(identity)).hexdigest()
        random_digest = hashlib.sha256(_json_bytes({"seed": seed, **identity})).digest()
        corruption_seed = int.from_bytes(random_digest[:8], "big")
        for label in (0, 1):
            recipes.append({"sample_id": f"{source_id}:{'synthetic' if label else 'normal'}", "source_id": source_id,
                            "image_path": source["image_path"], "source_sha256": source["sha256"],
                            "category": source["category"], "split": source["split"], "source_split": "train",
                            "label": label, "corruption_seed": corruption_seed})
    return {"schema_version": 1, "generator": GENERATOR, "manifest_sha256": digest,
            "generator_code_sha256": _sha256(Path(__file__)), "config": deepcopy(config),
            "config_sha256": hashlib.sha256(_json_bytes(config)).hexdigest(), "seed": seed,
            "categories": categories, "recipes": recipes}


def write_synthetic_plan(plan: dict[str, Any], path: Path) -> None:
    """Ecrit un plan reproductible une seule fois, sans ecrasement ni liens."""
    path = Path(path).absolute()
    resolved = path.resolve()
    if (resolved.is_relative_to(PROJECT)
            and not any(resolved.is_relative_to(PROJECT / name)
                        for name in ("artifacts/transfer_data", "artifacts/transfer_runs"))):
        raise ValueError("Sorties du plan limitees aux repertoires transfer_data/transfer_runs dans le depot.")
    if any(ancestor.exists() and _linked(ancestor) for ancestor in (path, *path.parents)):
        raise ValueError("Plan synthetique via lien ou jonction refuse.")
    data = _json_bytes(plan)
    if path.exists() and path.read_bytes() != data:
        raise FileExistsError("Plan synthetique fige different ; utiliser un nouveau chemin.")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)


def _normalization_vectors(image: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    if (not isinstance(image, torch.Tensor) or image.ndim not in (3, 4)
            or image.shape[-3] != 3 or not image.is_floating_point() or not torch.isfinite(image).all()):
        raise ValueError("Tenseur RGB CHW ou BCHW flottant fini requis.")
    shape = (3, 1, 1) if image.ndim == 3 else (1, 3, 1, 1)
    mean = image.new_tensor(IMAGENET_MEAN).reshape(shape)
    std = image.new_tensor(IMAGENET_STD).reshape(shape)
    return mean, std


def normalize_image(image: torch.Tensor) -> torch.Tensor:
    mean, std = _normalization_vectors(image)
    if image.min() < 0 or image.max() > 1:
        raise ValueError("Pixels RGB [0,1] requis avant normalisation.")
    return (image - mean) / std


def denormalize_image(image: torch.Tensor) -> torch.Tensor:
    mean, std = _normalization_vectors(image)
    return image * std + mean


def _local_corruption(image: torch.Tensor, valid: torch.Tensor, seed: int,
                      config: dict[str, Any]) -> tuple[torch.Tensor, torch.Tensor]:
    """Cut-paste dans la meme image, avec contraste/luminosite locale fixes."""
    ys, xs = torch.where(valid[0].bool())
    if not ys.numel():
        raise ValueError("Zone valide vide pour la corruption synthetique.")
    top, left = int(ys.min()), int(xs.min())
    height, width = int(ys.max()) - top + 1, int(xs.max()) - left + 1
    rng = random.Random(seed)
    low, high = config["patch_fraction"]
    patch_h = max(1, min(height, math.ceil(rng.uniform(low, high) * height)))
    patch_w = max(1, min(width, math.ceil(rng.uniform(low, high) * width)))
    target_y, target_x = rng.randint(top, top + height - patch_h), rng.randint(left, left + width - patch_w)
    source_y, source_x = rng.randint(top, top + height - patch_h), rng.randint(left, left + width - patch_w)
    donor = image[:, source_y:source_y + patch_h, source_x:source_x + patch_w].clone()
    target = image[:, target_y:target_y + patch_h, target_x:target_x + patch_w]
    contrast = rng.choice((0.8, 1.2))
    mean = donor.mean(dim=(-2, -1), keepdim=True)
    effect = config["min_effect"]
    direction = 1 if float(target.mean()) < 0.5 else -1
    patch = ((donor - mean) * contrast + mean + direction * effect).clamp(0, 1)
    if torch.equal(patch, target):
        patch = torch.where(target < 0.5, target + effect, target - effect)
    result = image.clone()
    result[:, target_y:target_y + patch_h, target_x:target_x + patch_w] = patch
    changed = (result != image).any(dim=0, keepdim=True)
    if not changed.any() or torch.any(changed & ~valid.bool()):
        raise ValueError("Corruption synthétique vide ou debordant sur le padding.")
    return result, changed.to(torch.float32)


class SyntheticAnomalyDataset(Dataset):
    """Deux exemples fixes par source normale ; aucun mode test disponible."""

    def __init__(self, manifest: Path, root: Path, *, category: str, split: str,
                 config: dict[str, Any], seed: int = 42, plan: dict[str, Any] | None = None) -> None:
        if split not in ("train", "val"):
            raise ValueError("Synthese limitee aux splits explicites train et val, jamais test.")
        expected = prepare_synthetic_plan(manifest, config, seed)
        if plan is not None and _json_bytes(plan) != _json_bytes(expected):
            raise ValueError("Plan synthetique perime, modifie ou incompatible avec les sources.")
        self.plan = expected
        self.config = deepcopy(config)
        self.rows = [row for row in expected["recipes"] if row["category"] == category and row["split"] == split]
        if not self.rows:
            raise ValueError("Aucune source synthetique pour la categorie/split demandes.")
        self.dataset = MVTecDataset(manifest, root, split=split, categories=[category],
                                    image_size=tuple(config["image_size"]), verify_hashes=True)
        self._indices = {row["image_path"]: index for index, row in enumerate(self.dataset.rows)}

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, Any]:
        row = self.rows[index]
        sample = self.dataset[self._indices[row["image_path"]]]
        raw = sample["image"]
        mask = torch.zeros_like(sample["valid_mask"])
        if row["label"]:
            raw, mask = _local_corruption(raw, sample["valid_mask"], row["corruption_seed"], self.config)
        return {"image": normalize_image(raw), "raw_image": raw, "label": row["label"],
                "synthetic_mask": mask, "valid_mask": sample["valid_mask"],
                "image_path": row["image_path"], "sample_id": row["sample_id"], "source_id": row["source_id"],
                "category": row["category"], "split": row["split"], "source_split": "train", "mask_path": "",
                "defect_type": "synthetic_cutpaste" if row["label"] else "good"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Figer les recettes synthetiques sans ouvrir d'image.")
    parser.add_argument("--manifest", type=Path, default=Path("data/manifests/manifest.csv"))
    parser.add_argument("--config", type=Path, default=Path("configs/synthetic_transfer.yaml"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--root", type=Path, default=Path("data/raw/mvtec_ad"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        output = args.output or Path("artifacts/transfer_data") / f"seed_{args.seed}" / "plan.json"
        if any(output.resolve().is_relative_to(protected.resolve()) for protected in (args.root, args.manifest.parent)):
            raise ValueError("Plan interdit dans les donnees et les manifestes sources.")
        plan = prepare_synthetic_plan(args.manifest, load_synthetic_config(args.config), args.seed)
        write_synthetic_plan(plan, output)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"Preparation synthetique impossible : {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(output), "sha256": _sha256(output), "recipes": len(plan["recipes"]),
                      "categories": plan["categories"], "inference_executed": False, "images_opened": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
