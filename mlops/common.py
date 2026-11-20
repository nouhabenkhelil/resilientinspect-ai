"""Read-only access to frozen evidence. No serving or scientific code changes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mlops/local"
REPORTS = ROOT / "reports/experiments"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def unique(pattern: str) -> Path:
    paths = sorted(ROOT.glob(pattern))
    if len(paths) != 1:
        raise ValueError(f"Exactly one canonical source required: {pattern}: {len(paths)}")
    return paths[0]


def records():
    export = read(ROOT / "frontend/src/data/experiments.json")
    for source in export["sources"]:
        if sha256(ROOT / source["path"]) != source["sha256"]:
            raise ValueError(f"Stale official metrics export: {source['path']}")
    result = []
    for row in export["records"]:
        variant, category = row["model"], row["category"]
        transfer = variant.startswith("T")
        summary_path = unique(f"artifacts/transfer_runs/{variant}/{category}/seed42/full_*/summary.json" if transfer
                              else f"artifacts/{variant.lower()}_runs/{category}/full_*/summary.json")
        summary = read(summary_path)
        checkpoint = summary_path.with_name("best.pt")
        if summary["scope"] != "full" or summary["status"] != "completed" or sha256(checkpoint) != summary["checkpoint_sha256"]:
            raise ValueError(f"Invalid full checkpoint: {checkpoint}")
        protocol = ROOT / ("configs/evaluate_transfer.yaml" if transfer else "configs/evaluate_ae_b0.yaml")
        calibration = (summary_path.with_name("calibration.json") if transfer else
                       ROOT / f"reports/evaluation/{variant.lower()}/{sha256(protocol)[:12]}/{category}/calibration.json")
        if calibration.with_suffix(".sha256").read_text().strip() != sha256(calibration):
            raise ValueError(f"Calibration SHA256 mismatch: {calibration}")
        parity = [read(ROOT / f"artifacts/onnx/{variant}/{category}/parity-{system}.json") for system in ("windows", "linux")]
        onnx_ok = all(p["status"] == "passed" for p in parity)
        result.append({**row, "run_dir": summary_path.parent, "summary": summary, "checkpoint": checkpoint,
                       "checkpoint_sha256": sha256(checkpoint), "calibration": calibration,
                       "calibration_sha256": sha256(calibration), "protocol": protocol,
                       "onnx_available": onnx_ok})
    if len(result) != 15 or sum(r["onnx_available"] for r in result) != 14:
        raise ValueError("Expected 15 PyTorch and 14 accepted ONNX models")
    return result
