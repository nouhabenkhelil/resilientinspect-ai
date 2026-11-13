"""Controle du rapport sans execution de modele, d'entrainement ou de test MVTec."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
PDF = ROOT / "Rapport_MiParcours_TrackX_ResilientInspectAI.pdf"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    assert PDF.is_file(), "Compiler le rapport avant verification."
    info = subprocess.check_output(["pdfinfo", str(PDF)]).decode("utf-8", errors="replace")
    (ROOT / "build/pdfinfo.txt").write_text(info, encoding="utf-8")
    match = re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE)
    assert match and int(match.group(1)) == 5, info
    assert "A4" in info, info
    subprocess.run(["pdftotext", "-layout", str(PDF), str(ROOT / "build/rapport_extracted.txt")], check=True)
    subprocess.run(["pdftotext", "-bbox-layout", str(PDF), str(ROOT / "build/rapport_bbox.html")], check=True)
    extracted = (ROOT / "build/rapport_extracted.txt").read_text(encoding="utf-8")
    pages = [page for page in extracted.split("\f") if page.strip()]
    assert len(pages) == 5
    source = (ROOT / "rapport_miparcours.tex").read_text(encoding="utf-8")
    log = (ROOT / "build/Rapport_MiParcours_TrackX_ResilientInspectAI.log").read_text(encoding="utf-8", errors="replace")
    forbidden = [token for token in ("Overfull", "Underfull", "Missing character", "Undefined control sequence") if token in log]
    assert not forbidden, forbidden

    with (ROOT / "audit/metrics_exact.csv").open(encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    metrics = ["image_auroc", "image_ap", "image_f1", "pixel_auroc", "pixel_ap", "dice_micro", "iou_micro"]
    values = []
    for row in records:
        path = PROJECT / f"reports/evaluation/{row['model'].lower()}/f515662ab4ef/category_metrics.csv"
        with path.open(encoding="utf-8", newline="") as stream:
            original = next(item for item in csv.DictReader(stream) if item["category"] == row["category"])
        for key in metrics:
            assert row[key] == original[key], (row, original)
            values.append(row[key])
    for variant in ("b0", "a1"):
        macro = json.loads((PROJECT / f"reports/evaluation/{variant}/f515662ab4ef/macro_metrics.json").read_text(encoding="utf-8"))
        values.extend(str(macro[key]["mean"]) for key in metrics)
    assert len(values) == 56
    assert all(value in pages[2] and value in source for value in values), "Metrique absente ou arrondie."

    ns = {"x": "http://www.w3.org/1999/xhtml"}
    geometry = []
    for index, page in enumerate(ET.parse(ROOT / "build/rapport_bbox.html").getroot().findall(".//x:page", ns), 1):
        width, height = float(page.attrib["width"]), float(page.attrib["height"])
        words = page.findall(".//x:word", ns)
        assert all(float(word.attrib["xMin"]) >= 35 and float(word.attrib["xMax"]) <= width - 35
                   and float(word.attrib["yMin"]) >= 10 and float(word.attrib["yMax"]) <= height - 10 for word in words)
        assert f"{index}/5" in pages[index - 1]
        geometry.append({"page": index, "words": len(words), "within_page_margins": True})

    figures = json.loads((ROOT / "audit/figure_sources.json").read_text(encoding="utf-8"))
    assert all(sha256(PROJECT / item["source"]) == item["sha256"] == sha256(ROOT / "figures" / name)
               for name, item in figures.items())
    before = json.loads((ROOT / "audit/preservation_before.json").read_text(encoding="utf-8"))
    changed = []
    for name, expected in before.items():
        path = PROJECT / name
        if not path.is_file():
            changed.append(name)
            continue
        stat = path.stat()
        if {"sha256": sha256(path), "mtime_ns": stat.st_mtime_ns, "size": stat.st_size} != expected:
            changed.append(name)
    assert not changed, changed
    report = {
        "audit_date": "2026-11-11", "pdf": str(PDF), "pdf_sha256": sha256(PDF), "pages": 5,
        "page_format": "A4", "latex_errors_or_overflows": [], "exact_metrics_verified": 56,
        "gabarit_sections_reviewed": ["1", "2.1", "2.2", "2.3", "2.4", "component_progress", "3", "4", "5_Gantt_RACI", "annexes"],
        "geometry": geometry, "real_visual_proofs": len(figures), "copied_figures_match_originals": True,
        "protected_preexisting_files": len(before), "all_protected_sha256_size_mtime_unchanged": True,
        "training_or_official_evaluation_executed": False, "project_tests_rerun": False,
        "names_and_emails_confirmed_by_user": True,
        "remaining_placeholders": ["official track code", "group identifier", "individual roles", "RACI assignments", "final presentation date"],
        "missing_evidence": ["A1 MLflow screenshot", "transfer/test screenshot", "full T0/T1/T2 experiments and real-test metrics"],
        "scientific_source_files": {str(path.relative_to(ROOT)): sha256(path) for path in
                                    [ROOT / "rapport_miparcours.tex", ROOT / "audit/metrics_exact.csv", ROOT / "audit/figure_sources.json"]},
    }
    (ROOT / "audit/quality_check.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"pages": 5, "exact_metrics": 56, "unchanged_protected_files": len(before), "status": "verified"}))


if __name__ == "__main__":
    main()
