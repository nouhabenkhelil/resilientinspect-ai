"""Tableau B0/A1 depuis les rapports existants, sans inference ni recalibration."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

from resilientinspect.evaluation.evaluate_ae import CATEGORIES, _json_bytes, _write_csv, _write_once

PROJECT = Path(__file__).resolve().parents[2]
METRICS = {
    "image_auroc": ("image", "auroc"),
    "image_ap": ("image", "ap"),
    "image_f1": ("image_decision", "f1"),
    "pixel_auroc": ("pixel", "auroc"),
    "pixel_ap": ("pixel", "ap"),
    "dice_micro": ("segmentation_micro", "dice"),
    "iou_micro": ("segmentation_micro", "iou"),
}
BINDINGS = ("protocol_sha256", "manifest_sha256", "dataset_code_sha256")


def _safe_output(output: Path, sources: tuple[Path, Path]) -> None:
    destination = output.resolve()
    allowed = PROJECT / "reports/evaluation/a1"
    if destination.is_relative_to(PROJECT) and not destination.is_relative_to(allowed):
        raise ValueError("Sorties projet limitees a reports/evaluation/a1.")
    for source in sources:
        resolved = source.resolve()
        if destination.is_relative_to(resolved) or resolved.is_relative_to(destination):
            raise ValueError("Sorties interdites dans ou au-dessus des rapports sources.")


def _read_report(path: Path, category: str, variant: str) -> tuple[dict[str, Any], dict[str, Any]]:
    data = path.read_bytes()
    report = json.loads(data)
    if (not isinstance(report, dict) or report.get("category") != category or report.get("split") != "test"
            or report.get("variant", variant) != variant or report.get("resolution") != [256, 256]
            or report.get("padding_excluded") is not True):
        raise ValueError(f"Rapport {variant}/{category} incompatible avec le protocole B0.")
    for key in (*BINDINGS, "checkpoint_sha256", "calibration_sha256"):
        digest = report.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"Provenance {key} absente ou invalide : {path}")
    values = {}
    for name, (section, key) in METRICS.items():
        value = report["metrics"][section][key]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError(f"Metrique {name} invalide : {path}")
        values[name] = value
    source = {"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest(),
              **{key: report[key] for key in (*BINDINGS, "checkpoint_sha256", "calibration_sha256")}}
    return report, {"category": category, "model": variant, "status": "evaluated", **values, "source": source}


def build_comparison(b0_dir: Path, a1_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Lit les six rapports possibles ; A1 absent reste pending, sans score estime.

    Chaque fichier B0 est obligatoire. Les sorties sont immuables : utiliser un
    autre dossier pour un nouveau tableau apres l'evaluation officielle A1.
    """
    b0_dir, a1_dir, output_dir = Path(b0_dir), Path(a1_dir), Path(output_dir)
    if b0_dir.resolve() == a1_dir.resolve():
        raise ValueError("Deux dossiers sources B0 et A1 distincts sont requis.")
    _safe_output(output_dir, (b0_dir, a1_dir))
    rows = []
    reference = None
    for category in CATEGORIES:
        b0, row = _read_report(b0_dir / category / "metrics.json", category, "B0")
        binding = {key: b0[key] for key in BINDINGS}
        if reference is not None and binding != reference:
            raise ValueError("Rapports B0 de protocoles ou jeux de donnees differents.")
        reference = binding
        rows.append(row)
        path = a1_dir / category / "metrics.json"
        if path.exists():
            a1, row = _read_report(path, category, "A1")
            if any(a1[key] != b0[key] for key in BINDINGS):
                raise ValueError(f"Protocoles ou jeux de donnees B0/A1 incompatibles : {category}")
        else:
            row = {"category": category, "model": "A1", "status": "pending",
                   **{name: None for name in METRICS}, "source": None}
        rows.append(row)
    result = {"schema_version": 1, "comparison": "B0/A1", "binding": reference, "rows": rows,
              "inference_executed": False, "calibration_executed": False,
              "note": "pending signifie aucun metrics.json A1 disponible ; aucune metrique estimee."}
    flat = [{key: value for key, value in row.items() if key != "source"} for row in rows]
    _write_once(output_dir / "comparison.json", _json_bytes(result))
    _write_csv(output_dir / "comparison.csv", flat)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b0-dir", type=Path, required=True)
    parser.add_argument("--a1-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/evaluation/a1/comparison"))
    args = parser.parse_args(argv)
    try:
        result = build_comparison(args.b0_dir, args.a1_dir, args.output_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Comparaison impossible : {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output_dir), "rows": len(result["rows"]),
                      "a1_evaluated": sum(row["model"] == "A1" and row["status"] == "evaluated" for row in result["rows"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
