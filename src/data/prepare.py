"""Manifestes MVTec AD reproductibles, sans copie ni modification d'images."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import random
import re
import sys
from typing import Any, Sequence

import yaml

from .audit import DEFAULT_CATEGORIES, _linked, _sha256, audit_dataset


MANIFEST_FIELDS = (
    "image_path", "category", "split", "label", "defect_type", "mask_path",
    "source_split", "sha256", "mask_sha256",
)
SPLITS = ("train", "val", "test")
DEFAULT_PREPROCESSING = {
    "image_size": [256, 256], "aspect_ratio": "letterbox",
    "image_interpolation": "bilinear", "mask_interpolation": "nearest",
    "padding_value": 0, "pixel_scaling": "divide_by_255", "normalization": "none",
}
SPLIT_METHOD = "sorted_then_python_random_shuffle_per_category_v1"


def validate_preparation_settings(config: dict[str, Any]) -> None:
    """Verifier le protocole annonce, sans acceder au dataset ni importer torch."""
    dataset = config.get("dataset", {})
    if config.get("phase") != 1 or dataset.get("stage") != "preparation":
        raise ValueError("La preparation exige phase 1 et stage preparation.")
    settings = dataset.get("preparation")
    if not isinstance(settings, dict):
        raise ValueError("Parametres de preparation absents.")
    if type(settings.get("seed")) is not int:
        raise ValueError("La seed doit etre un entier.")
    fraction = settings.get("validation_fraction")
    if type(fraction) not in (int, float) or not 0 < fraction < 1:
        raise ValueError("validation_fraction doit etre comprise strictement entre 0 et 1.")
    if settings.get("split_method") != SPLIT_METHOD or settings.get("validation_rounding") != "ceil":
        raise ValueError("Methode de separation ou arrondi non supporte.")
    if dataset.get("preprocessing") != DEFAULT_PREPROCESSING:
        raise ValueError("Preprocessing attendu : letterbox 256x256, bilinear/nearest, pixels /255, sans normalisation.")


def safe_data_path(root: Path, relative: str) -> Path:
    """Resoudre un chemin POSIX relatif sans traversee, lien ni jonction."""
    path = PurePosixPath(relative)
    if (not path.parts or not relative or path.is_absolute() or "\\" in relative or ":" in relative
            or ".." in path.parts or path.as_posix() != relative):
        raise ValueError(f"Chemin relatif invalide : {relative!r}")
    root = Path(root).resolve()
    current = root
    for part in path.parts:
        current = current / part
        if current.exists() and _linked(current):
            raise ValueError(f"Lien ou jonction refuse : {relative}")
    if not current.resolve().is_relative_to(root):
        raise ValueError(f"Chemin hors dataset : {relative}")
    return current


def validate_manifest(rows: Sequence[dict[str, str]]) -> None:
    """Refuser fuite de chemin/contenu, provenance incoherente et masque mal associe."""
    if not rows:
        raise ValueError("Le manifeste est vide.")
    seen_paths: set[str] = set()
    content_splits: dict[str, set[str]] = {}
    for row in rows:
        if set(row) != set(MANIFEST_FIELDS) or any(not isinstance(value, str) for value in row.values()):
            raise ValueError("Schema de manifeste invalide.")
        category, split, source = row["category"], row["split"], row["source_split"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", category) or split not in SPLITS:
            raise ValueError("Categorie ou split invalide.")
        if source != ("test" if split == "test" else "train"):
            raise ValueError("Fuite de provenance : train/val doivent provenir du train officiel.")
        relative = row["image_path"]
        parts = PurePosixPath(relative).parts
        # Autoriser le layout canonique et l'emballage cat/cat audite.
        if (not relative or PurePosixPath(relative).is_absolute() or ".." in parts
                or "\\" in relative or ":" in relative or PurePosixPath(relative).as_posix() != relative
                or parts[:-3] not in ((category,), (category, category))
                or parts[-3:-1] != (source, row["defect_type"])):
            raise ValueError(f"Chemin image incompatible avec sa provenance : {relative}")
        if relative.casefold() in seen_paths:
            raise ValueError(f"Chemin d'image duplique entre/sur les splits : {relative}")
        seen_paths.add(relative.casefold())
        if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise ValueError("SHA256 d'image invalide.")
        content_splits.setdefault(row["sha256"], set()).add(split)
        if row["label"] == "0":
            if row["defect_type"] != "good" or row["mask_path"] or row["mask_sha256"]:
                raise ValueError("Une image normale exige good et aucun masque.")
        elif row["label"] == "1":
            if split != "test" or row["defect_type"] == "good":
                raise ValueError("Les anomalies reelles sont reservees au test officiel.")
            mask = PurePosixPath(row["mask_path"])
            expected = (*parts[:-3], "ground_truth", row["defect_type"])
            if (not row["mask_path"] or mask.is_absolute() or ".." in mask.parts
                    or "\\" in row["mask_path"] or ":" in row["mask_path"]
                    or mask.as_posix() != row["mask_path"] or mask.parts[:-1] != expected
                    or mask.stem != PurePosixPath(relative).stem + "_mask"
                    or not re.fullmatch(r"[0-9a-f]{64}", row["mask_sha256"])):
                raise ValueError("Masque absent ou incompatible avec son image de test.")
        else:
            raise ValueError("Label attendu : 0 normal ou 1 anormal.")
    if any(len(splits) > 1 for splits in content_splits.values()):
        raise ValueError("Fuite de contenu : une image SHA256 identique est presente dans plusieurs splits.")


def read_manifest(path: Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(MANIFEST_FIELDS):
            raise ValueError("Colonnes de manifeste invalides ou dans un ordre inattendu.")
        rows = list(reader)
    validate_manifest(rows)
    return rows


def prepare_dataset(
    root: Path, categories: Sequence[str] = DEFAULT_CATEGORIES, *,
    seed: int = 42, validation_fraction: float = 0.2,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Auditer les fichiers puis separer exclusivement train/good, par categorie."""
    if type(seed) is not int or type(validation_fraction) not in (int, float) or not 0 < validation_fraction < 1:
        raise ValueError("Seed ou fraction de validation invalide.")
    audit = audit_dataset(root, categories)
    blocking = [issue for category in audit["categories"].values() for issue in category["issues"]
                if issue["severity"] == "error" or issue["code"] in {
                    "nonbinary_mask", "empty_mask", "mask_mode", "multiple_frames", "unexpected_file"}]
    if blocking:
        raise ValueError("Audit incompatible avec la preparation : " + json.dumps(blocking[:5]))
    rows: list[dict[str, str]] = []
    counts = {}
    fraction = Fraction(str(validation_fraction))
    for name, category in sorted(audit["categories"].items()):
        images = [file for file in category["files"] if file["kind"] == "image"]
        normal = sorted(file["path"] for file in images if file["split"] == "train")
        n_val = (len(normal) * fraction.numerator + fraction.denominator - 1) // fraction.denominator
        if not 0 < n_val < len(normal):
            raise ValueError(f"{name} : effectif insuffisant pour deux groupes non vides.")
        random.Random(seed).shuffle(normal)  # RNG local reinitialise pour chaque categorie.
        validation = set(normal[:n_val])
        files_by_path = {file["path"]: file for file in category["files"]}
        for image in images:
            source = image["split"]
            split = "test" if source == "test" else ("val" if image["path"] in validation else "train")
            mask = files_by_path.get(image.get("mask_path", ""))
            rows.append({
                "image_path": image["path"], "category": name, "split": split,
                "label": "0" if image["defect"] == "good" else "1",
                "defect_type": image["defect"], "mask_path": mask["path"] if mask else "",
                "source_split": source, "sha256": image["sha256"],
                "mask_sha256": mask["sha256"] if mask else "",
            })
        category_rows = [row for row in rows if row["category"] == name]
        per_split = Counter(row["split"] for row in category_rows)
        counts[name] = {split: per_split[split] for split in SPLITS}
        counts[name].update(test_good=sum(row["split"] == "test" and row["label"] == "0" for row in category_rows),
                            test_anomalous=sum(row["label"] == "1" for row in category_rows))
    rows.sort(key=lambda row: (row["category"], SPLITS.index(row["split"]), row["image_path"]))
    validate_manifest(rows)
    inventory = [{key: row[key] for key in ("image_path", "sha256", "mask_path", "mask_sha256")}
                 for row in sorted(rows, key=lambda row: row["image_path"])]
    metadata = {
        "schema_version": 1, "phase": 1, "step": "data_preparation",
        "dataset_root": str(Path(root).resolve()), "seed": seed,
        "validation_fraction": validation_fraction, "validation_rounding": "ceil",
        "split_method": SPLIT_METHOD, "categories": sorted(counts), "counts": counts,
        "totals": {split: sum(count[split] for count in counts.values()) for split in SPLITS},
        "labels": {"0": "normal", "1": "anomalous"}, "path_base": "dataset_root",
        "preprocessing": DEFAULT_PREPROCESSING.copy(),
        "source_inventory_sha256": hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest(),
        "prepare_code_sha256": _sha256(Path(__file__)),
        "dataset_code_sha256": _sha256(Path(__file__).with_name("dataset.py")),
        "audit_warnings": [issue for category in audit["categories"].values() for issue in category["issues"]],
        "protocol": {"official_test_reassigned": False, "originals_modified": False,
                     "normalization_fitted": False, "training_performed": False},
    }
    return rows, metadata


def _csv_bytes(rows: Sequence[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def write_manifests(
    rows: list[dict[str, str]], metadata: dict[str, Any], output_dir: Path,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Figer les CSV : un fichier existant different n'est jamais ecrase."""
    validate_manifest(rows)
    root = Path(metadata["dataset_root"]).resolve()
    output_dir = Path(output_dir).resolve()
    if output_dir.is_relative_to(root):
        raise ValueError("Les manifestes doivent etre ecrits hors des originaux.")
    payloads = {"manifest.csv": _csv_bytes(rows)}
    payloads.update({f"{split}.csv": _csv_bytes([row for row in rows if row["split"] == split]) for split in SPLITS})
    report = {**metadata, "manifest_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}}
    payloads["preparation.json"] = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    targets = {output_dir / name: data for name, data in payloads.items()}
    if report_path is not None:
        targets[Path(report_path).absolute()] = payloads["preparation.json"]
    # Verifier toutes les destinations avant la premiere ecriture.
    for path, data in targets.items():
        if path.is_symlink() or path.resolve().is_relative_to(root):
            raise ValueError("Une destination cible les originaux ou un lien symbolique.")
        if path.exists() and path.read_bytes() != data:
            raise FileExistsError(f"Fichier fige different, utiliser un autre repertoire : {path}")
    for path, data in targets.items():
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(data)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[2] / "configs/dataset.yaml")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/manifests"))
    parser.add_argument("--report", type=Path, default=Path("reports/experiments/data_preparation.json"))
    arguments = parser.parse_args(argv)
    try:
        config = yaml.safe_load(arguments.config.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Configuration YAML invalide.")
        validate_preparation_settings(config)
        dataset = config["dataset"]
        if dataset.get("download") is not False or dataset["categories"].get("status") != "confirmed":
            raise ValueError("Categories confirmees et telechargement desactive requis.")
        root = arguments.root or Path(dataset["default_root"])
        settings = dataset["preparation"]
        rows, metadata = prepare_dataset(root, dataset["categories"]["confirmed"],
                                         seed=settings["seed"], validation_fraction=settings["validation_fraction"])
        report = write_manifests(rows, metadata, arguments.output_dir, arguments.report)
    except (OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"Preparation impossible : {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"counts": report["counts"], "totals": report["totals"],
                      "manifest_sha256": report["manifest_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
