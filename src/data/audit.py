"""Audit descriptif MVTec AD en lecture seule, sans split ni entrainement.

Execution : python -m resilientinspect.data.audit --root data/raw/mvtec_ad
Les comptes incluent les fichiers d'image reconnus, meme corrompus. Les
histogrammes de dimensions/formats/modes concernent les fichiers decodables.
L'appariement des masques utilise (categorie, type de defaut, nom sans suffixe).
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
from typing import Any, Sequence
import warnings

from PIL import Image, __version__ as PILLOW_VERSION


DEFAULT_CATEGORIES = ("bottle", "hazelnut", "leather")
IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif",
    ".ppm", ".pgm", ".pbm",
})
COUNT_FIELDS = (
    "train_good", "test_good", "test_anomalous", "ground_truth_masks",
    "matched_pairs", "missing_masks", "orphan_masks", "corrupt_images",
    "corrupt_masks", "mask_size_mismatches",
)


def _linked(path: Path) -> bool:
    """Exclure aussi les jonctions Windows pour ne pas sortir du dataset."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _audit_category(root: Path, name: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "category": name, "resolved_path": None, "layout": "missing",
        "counts": dict.fromkeys(COUNT_FIELDS, 0), "defects": {},
        "resolutions": {"images": {}, "masks": {}},
        "formats": {"images": {}, "masks": {}},
        "modes": {"images": {}, "masks": {}},
        "extensions": {"images": {}, "masks": {}},
        "issues": [], "files": [], "duplicate_image_groups": [],
    }

    def issue(code: str, path: Path, detail: str, severity: str = "error") -> None:
        result["issues"].append({
            "severity": severity, "code": code,
            "path": path.relative_to(root).as_posix(), "detail": detail,
        })

    def directory(path: Path) -> list[Path]:
        try:
            if not path.resolve().is_relative_to(root) or _linked(path):
                issue("unsafe_link", path, "Lien ou jonction non suivi.")
                return []
            if not path.is_dir():
                issue("missing_directory", path, "Repertoire requis absent.")
                return []
            return sorted(path.iterdir(), key=lambda item: item.name)
        except FileNotFoundError:
            issue("missing_directory", path, "Repertoire requis absent.")
        except OSError as exc:
            issue("directory_read_error", path, str(exc))
        return []

    outer = root / name
    if not outer.is_dir():
        issue("missing_directory", outer, "Categorie absente.")
        return result
    nested = outer / name
    for candidate in (outer, nested):
        if candidate.exists() and (_linked(candidate) or not candidate.resolve().is_relative_to(root)):
            issue("unsafe_link", candidate, "Racine de categorie non sure, non suivie.")
            return result
    canonical_tree = any((outer / part).exists() for part in ("train", "test", "ground_truth"))
    nested_tree = any((nested / part).exists() for part in ("train", "test", "ground_truth"))
    if canonical_tree and nested_tree:
        result["layout"] = "ambiguous"
        issue("ambiguous_layout", outer, "Donnees presentes aux deux niveaux ; aucun choix automatique.")
        return result
    category_root = nested if nested_tree else outer
    result["resolved_path"] = category_root.relative_to(root).as_posix()
    result["layout"] = "nested" if nested_tree else "canonical"
    if nested_tree:
        issue("nested_category", nested, "Imbrication resolue en lecture seule ; aucun fichier deplace.", "warning")
    for entry in directory(category_root):
        if _linked(entry):
            issue("unsafe_link", entry, "Lien ou jonction non suivi.")
            continue
        if entry.name in {"train", "test", "ground_truth"}:
            continue
        if entry.name in {"license.txt", "readme.txt"} and entry.is_file():
            continue
        if entry == nested and not nested_tree and entry.is_dir() and not _linked(entry) and not any(entry.iterdir()):
            issue("empty_nested_wrapper", entry, "Ancien emballage vide conserve, sans donnees a auditer.", "warning")
        else:
            issue("unexpected_category_entry", entry, "Entree hors de la structure attendue, non incluse dans les comptes.")

    def scan_group(folder: Path, split: str, defect: str, kind: str) -> list[dict[str, Any]]:
        records = []
        for path in directory(folder):
            if _linked(path):
                issue("unsafe_link", path, "Lien ou jonction non suivi.")
                continue
            if not path.is_file():
                issue("unexpected_directory", path, "Sous-repertoire inattendu dans un dossier d'images.")
                continue
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                issue("unexpected_file", path, "Fichier non-image exclu des comptes.", "warning")
                continue
            record: dict[str, Any] = {
                "path": path.relative_to(root).as_posix(), "kind": kind,
                "split": split, "defect": defect, "stem": path.stem,
                "extension": path.suffix.lower(), "readable": False,
                "width": None, "height": None, "format": None, "mode": None,
                "size_bytes": None, "sha256": None, "error": None,
            }
            try:
                before = path.stat()
                record["size_bytes"] = before.st_size
                record["sha256"] = _sha256(path)
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(path) as image:
                        image.verify()
                    # verify() seul ne decode pas tous les pixels (notamment JPEG).
                    with Image.open(path) as image:
                        image.load()
                        record.update(width=image.width, height=image.height,
                                      format=image.format, mode=image.mode)
                        if getattr(image, "n_frames", 1) != 1:
                            issue("multiple_frames", path, "Seule la premiere frame est inspectee.", "warning")
                        if kind == "mask":
                            if image.mode in ("1", "L"):
                                values = [i for i, count in enumerate(image.histogram()) if count]
                                record["mask_values"] = values
                                if not set(values).issubset({0, 1}) and not set(values).issubset({0, 255}):
                                    issue("nonbinary_mask", path, "Valeurs autres que 0/1 ou 0/255.", "warning")
                                if max(values, default=0) == 0:
                                    issue("empty_mask", path, "Masque de defaut sans pixel non nul.", "warning")
                            else:
                                issue("mask_mode", path, f"Mode de masque inhabituel : {image.mode}.", "warning")
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise OSError("Fichier modifie pendant l'audit ; relancer sur des donnees stables.")
                record["readable"] = True
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                issue(f"corrupt_{kind}", path, record["error"])
            result["files"].append(record)
            records.append(record)
        return records

    train_entries = directory(category_root / "train")
    test_entries = directory(category_root / "test")
    truth_entries = directory(category_root / "ground_truth")
    train = scan_group(category_root / "train" / "good", "train", "good", "image")
    good_test = scan_group(category_root / "test" / "good", "test", "good", "image")
    for split, records in (("train", train), ("test", good_test)):
        folder = category_root / split / "good"
        if folder.is_dir() and not records:
            issue("empty_required_group", folder, "Aucune image reconnue dans ce groupe requis.")
    for entry in train_entries:
        if entry.name != "good":
            issue("unexpected_train_entry", entry, "Seul train/good est attendu ; aucune utilisation pour l'apprentissage.")
    anomaly_groups: dict[str, list[dict[str, Any]]] = {}
    mask_groups: dict[str, list[dict[str, Any]]] = {}
    for entries, split, groups, kind in (
        (test_entries, "test", anomaly_groups, "image"),
        (truth_entries, "ground_truth", mask_groups, "mask"),
    ):
        for entry in entries:
            if split == "test" and entry.name == "good":
                continue
            if _linked(entry):
                issue("unsafe_link", entry, "Lien ou jonction non suivi.")
            elif not entry.is_dir():
                issue("unexpected_file", entry, "Fichier inattendu hors d'un dossier de defaut.", "warning")
            else:
                groups[entry.name] = scan_group(entry, split, entry.name, kind)
                if not groups[entry.name]:
                    issue("empty_defect_group", entry, "Aucune image reconnue dans ce dossier de defaut.", "warning")
                if split == "ground_truth" and entry.name == "good":
                    issue("unexpected_normal_masks", entry, "Les images normales ne doivent pas avoir de masques de defaut.")

    counts = result["counts"]
    counts["train_good"] = len(train)
    counts["test_good"] = len(good_test)
    counts["test_anomalous"] = sum(map(len, anomaly_groups.values()))
    counts["ground_truth_masks"] = sum(map(len, mask_groups.values()))
    for defect in sorted(anomaly_groups.keys() | mask_groups.keys()):
        images, masks = anomaly_groups.get(defect, []), mask_groups.get(defect, [])
        by_stem: dict[str, list[dict[str, Any]]] = defaultdict(list)
        masks_by_stem: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in images:
            by_stem[record["stem"]].append(record)
        for record in masks:
            stem = record["stem"]
            if stem.endswith("_mask"):
                masks_by_stem[stem[:-5]].append(record)
            else:
                counts["orphan_masks"] += 1
                issue("orphan_mask", root / record["path"], "Nom de masque sans suffixe _mask.")
        matched = 0
        for stem in sorted(by_stem.keys() | masks_by_stem.keys()):
            pair_images, pair_masks = by_stem.get(stem, []), masks_by_stem.get(stem, [])
            if not pair_images:
                for record in pair_masks:
                    counts["orphan_masks"] += 1
                    issue("orphan_mask", root / record["path"], "Aucune image de test de meme categorie, defaut et nom.")
            elif not pair_masks:
                for record in pair_images:
                    counts["missing_masks"] += 1
                    issue("missing_mask", root / record["path"], "Aucun masque de meme categorie, defaut et nom.")
            elif len(pair_images) != 1 or len(pair_masks) != 1:
                issue("ambiguous_pair", root / pair_images[0]["path"], "Plusieurs images ou masques partagent le meme identifiant.")
            else:
                matched += 1
                image, mask = pair_images[0], pair_masks[0]
                image["mask_path"] = mask["path"]
                mask["image_path"] = image["path"]
                if image["readable"] and mask["readable"] and (
                    image["width"], image["height"]
                ) != (mask["width"], mask["height"]):
                    counts["mask_size_mismatches"] += 1
                    issue("mask_size_mismatch", root / mask["path"], f"Dimensions differentes de {image['path']}.")
        counts["matched_pairs"] += matched
        result["defects"][defect] = {"test_images": len(images), "masks": len(masks), "matched_pairs": matched}

    duplicate_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for kind, plural in (("image", "images"), ("mask", "masks")):
        records = [record for record in result["files"] if record["kind"] == kind]
        counts[f"corrupt_{plural}"] = sum(not record["readable"] for record in records)
        result["extensions"][plural] = dict(sorted(Counter(record["extension"] for record in records).items()))
        readable = [record for record in records if record["readable"]]
        for field, value in (("resolutions", lambda record: f"{record['width']}x{record['height']}"),
                             ("formats", lambda record: record["format"]),
                             ("modes", lambda record: record["mode"])):
            result[field][plural] = dict(sorted(Counter(value(record) for record in readable).items()))
        if kind == "image":
            for record in readable:
                duplicate_groups[record["sha256"]].append(record)
    for digest, records in sorted(duplicate_groups.items()):
        if len(records) > 1:
            paths = [record["path"] for record in records]
            cross_split = len({record["split"] for record in records}) > 1
            result["duplicate_image_groups"].append({"sha256": digest, "paths": paths, "across_splits": cross_split})
            issue("duplicate_image_across_splits" if cross_split else "duplicate_image",
                  root / paths[0], "Fichiers d'images identiques octet par octet : " + ", ".join(paths), "warning")
    return result


def audit_dataset(root: Path, categories: Sequence[str] = DEFAULT_CATEGORIES) -> dict[str, Any]:
    """Lire les originaux et retourner un rapport ; aucune ecriture dans root."""
    root = Path(root).resolve()
    if not categories or isinstance(categories, str) or any(
        not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_-]+", name) is None
        for name in categories
    ) or len(set(categories)) != len(categories):
        raise ValueError("Les categories doivent etre des noms simples, uniques et non vides.")
    audited = {name: _audit_category(root, name) for name in categories}
    issues = [issue for category in audited.values() for issue in category["issues"]]
    errors = sum(issue["severity"] == "error" for issue in issues)
    return {
        "schema_version": 1, "phase": 1, "step": "dataset_audit_only",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_root": str(root), "pillow_version": PILLOW_VERSION,
        "auditor_sha256": _sha256(Path(__file__)),
        "status": "error" if errors else "ok",
        "issue_counts": {"error": errors, "warning": len(issues) - errors},
        "categories": audited,
        "totals": {field: sum(category["counts"][field] for category in audited.values()) for field in COUNT_FIELDS},
        "protocol": {
            "read_only": True, "training_performed": False, "threshold_tuning": False,
            "splits_created": False, "counts_include_corrupt_files": True,
            "histograms_readable_files_only": True,
            "pairing": "category + defect + image stem <-> stem_mask (any supported extension)",
            "matched_pairs": "filename pairs, including corrupt or differently sized files; errors reported separately",
        },
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    """Ecrire les diagnostics hors des originaux, jamais dans le dataset."""
    output_dir = Path(output_dir).resolve()
    dataset_root = Path(report["dataset_root"]).resolve()
    if output_dir.is_relative_to(dataset_root):
        raise ValueError("Le repertoire des rapports doit etre hors du dataset.")
    paths = {"json": output_dir / "audit.json", "summary": output_dir / "audit_summary.csv",
             "defects": output_dir / "audit_by_defect.csv"}
    for path in paths.values():
        if path.is_symlink() or path.resolve().is_relative_to(dataset_root):
            raise ValueError("Une destination de rapport cible les donnees originales.")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with paths["summary"].open("w", encoding="utf-8-sig", newline="") as stream:
        fields = ["category", "resolved_path", *COUNT_FIELDS, "resolutions", "formats", "modes", "errors", "warnings"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for name, category in report["categories"].items():
            writer.writerow({
                "category": name, "resolved_path": category["resolved_path"], **category["counts"],
                **{field: json.dumps(category[field], sort_keys=True) for field in ("resolutions", "formats", "modes")},
                "errors": sum(issue["severity"] == "error" for issue in category["issues"]),
                "warnings": sum(issue["severity"] == "warning" for issue in category["issues"]),
            })
    with paths["defects"].open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["category", "defect", "test_images", "masks", "matched_pairs"])
        writer.writeheader()
        for name, category in report["categories"].items():
            for defect, counts in category["defects"].items():
                writer.writerow({"category": name, "defect": defect, **counts})
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/raw/mvtec_ad"))
    parser.add_argument("--categories", nargs="+", default=list(DEFAULT_CATEGORIES))
    parser.add_argument("--output-dir", type=Path, default=Path("reports/eda"))
    arguments = parser.parse_args(argv)
    try:
        report = audit_dataset(arguments.root, arguments.categories)
        paths = write_reports(report, arguments.output_dir)
    except (OSError, ValueError) as exc:
        print(f"Audit impossible : {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "totals": report["totals"],
                      "issues": report["issue_counts"],
                      "reports": {name: str(path) for name, path in paths.items()}}, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
