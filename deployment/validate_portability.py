"""Offline validation only. Never starts FastAPI or recalibrates thresholds.

The candidate store defers admission until measured evidence has been written.
The serving ModelStore has no environment variable or flag to bypass evidence.
"""
import argparse
import csv
import json
from pathlib import Path
import platform
from uuid import uuid4

from PIL import Image

from backend.app.config import Settings
from backend.app.models import ModelStore
from backend.app.inference import predict
from backend.app.portability import POLICY, code_hashes, compatible_environment
from resilientinspect.data.audit import _sha256
from resilientinspect.data.dataset import letterbox_pair
from resilientinspect.evaluation import evaluate_transfer


class OfflineCandidateStore(ModelStore):
    def _require_deployment_parity(self, loaded):
        # Only this offline measurement program defers the evidence check.
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("windows", "linux"), required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    if args.phase == "linux" and not args.reference:
        parser.error("Linux requires a Windows reference")
    if (args.phase == "windows") != (platform.system() == "Windows"):
        parser.error("Phase does not match actual OS")
    root = Path(__file__).resolve().parents[1]
    settings = Settings(project_root=root)
    store = OfflineCandidateStore(settings)
    store.load()
    if len(store.models) != 15 or store.unavailable:
        raise ValueError(f"Incomplete candidate store: {store.unavailable}")
    rows = list(csv.DictReader(settings.manifest.open(encoding="utf-8")))
    rows = [r for r in rows if r["split"] == "val"]
    if not rows or any(r["source_split"] != "train" or r["label"] != "0" for r in rows):
        raise ValueError("Only original normal validation images allowed")
    reference = json.loads(args.reference.read_text()) if args.reference else None
    environment = evaluate_transfer._environment()
    hashes = code_hashes(root)
    if reference and (reference["code_sha256"] != hashes or reference["policy"] != POLICY
                      or not reference["environment"]["platform"].startswith("Windows")
                      or not compatible_environment(reference["environment"], environment)):
        raise ValueError("Reference versions/code/policy do not match")
    report = {"policy": POLICY, "environment": environment, "code_sha256": hashes,
              "test_executed": False, "split": "val", "models": {},
              "manifest_sha256": _sha256(settings.manifest),
              "reference_sha256": _sha256(args.reference) if args.reference else None}
    for (variant, category), loaded in store.models.items():
        key = f"{variant}/{category}"
        results = []
        previous = reference["models"][key] if reference else None
        meta = loaded.metadata
        result = {"checkpoint_sha256": meta.checkpoint_sha256,
                  "calibration_sha256": meta.calibration_sha256, "threshold": meta.threshold}
        if previous and any(previous[k] != v for k, v in result.items()):
            raise ValueError("Reference model binding mismatch")
        originals = {r["image_path"]: r for r in previous["scores"]} if previous else {}
        for row in rows:
            if row["category"] != category:
                continue
            path = args.dataset / row["image_path"]
            if not path.resolve().is_relative_to(args.dataset.resolve()) or _sha256(path) != row["sha256"]:
                raise ValueError(f"Image integrity failure: {path}")
            with Image.open(path) as image:
                rgb = image.convert("RGB")
                sample = letterbox_pair(rgb, Image.new("L", rgb.size, 0), (256, 256))
            prediction = predict(loaded, sample, uuid4())
            value = {"image_path": row["image_path"], "sha256": row["sha256"],
                     "score": prediction.anomaly_score, "decision": prediction.decision}
            if previous:
                original = originals[row["image_path"]]
                if original["sha256"] != row["sha256"]:
                    raise ValueError("Reference image integrity mismatch")
                error = abs(value["score"] - original["score"])
                changed = value["decision"] != original["decision"]
                justified = max(abs(value["score"] - meta.threshold), abs(original["score"] - meta.threshold)) <= POLICY["atol"]
                value.update(absolute_error=error, reference_score=original["score"],
                             passed=error <= POLICY["atol"] + POLICY["rtol"] * abs(original["score"])
                             and (not changed or justified), decision_changed=changed)
            results.append(value)
        if not results or (previous and len(results) != len(originals)):
            raise ValueError("Incomplete validation coverage")
        result.update(scores=results, status="passed" if all(r.get("passed", True) for r in results) else "failed")
        report["models"][key] = result
        print(f"{key}: {len(results)} images, {result['status']}", flush=True)
    report["status"] = "passed" if all(m["status"] == "passed" for m in report["models"].values()) else "failed"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".sha256").write_text(_sha256(args.output) + "\n", encoding="ascii")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
