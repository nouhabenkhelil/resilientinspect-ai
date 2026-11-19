"""Deployment-only relocation and CPU parity evidence; archives remain immutable."""

from dataclasses import asdict
import csv
import json
import math
from pathlib import Path, PurePosixPath

from resilientinspect.data.audit import _sha256
from resilientinspect.evaluation import evaluate_transfer


POLICY = {"id": "deployment_windows_linux_fp32_v1", "atol": 1e-5, "rtol": 1e-4,
          "decision_changes": "both_scores_within_atol_of_original_threshold"}


def checkpoint_matches(recorded, checkpoint, root, variant):
    """Require identical identity and canonical suffix, never follow archived paths."""
    expected = asdict(checkpoint)
    if not isinstance(recorded, dict) or set(recorded) != set(expected):
        return False
    if recorded == expected:
        return _sha256(Path(checkpoint.path)) == checkpoint.sha256
    path = PurePosixPath(str(recorded["path"]).replace("\\", "/"))
    relative = Path(checkpoint.path).resolve().relative_to(root.resolve())
    canonical = ("artifacts", f"{variant.lower()}_runs", checkpoint.category,
                 f"full_{checkpoint.run_id}", "best.pt")
    return (relative.parts == canonical and path.parts[-5:] == canonical
            and ".." not in path.parts
            and all(recorded[key] == value for key, value in expected.items() if key != "path")
            and _sha256(Path(checkpoint.path)) == checkpoint.sha256)


def compatible_environment(reference, current):
    # OS name and architecture spelling are provenance, not numerical versions.
    ignored = {"platform", "machine"}
    return ({k: v for k, v in reference.items() if k not in ignored}
            == {k: v for k, v in current.items() if k not in ignored})


def code_hashes(root):
    paths = sorted((root / "backend/app").glob("*.py"))
    paths += sorted((root / "src").rglob("*.py"))
    paths += [root / "deployment/validate_portability.py"]
    return {path.relative_to(root).as_posix(): _sha256(path) for path in paths}


def require_evidence(root, loaded):
    current = evaluate_transfer._environment()
    if not current["platform"].startswith("Linux"):
        return
    path = root / "deployment/reports/portability/linux.json"
    if path.with_suffix(".sha256").read_text().strip() != _sha256(path):
        raise ValueError("Deployment parity report SHA256 mismatch")
    report = json.loads(path.read_text())
    reference = path.with_name("windows.json")
    original = json.loads(reference.read_text())
    manifest = root / "data/manifests/manifest.csv"
    if (report.get("status") != "passed" or report.get("policy") != POLICY
            or report.get("environment") != current or report.get("code_sha256") != code_hashes(root)
            or report.get("reference_sha256") != _sha256(reference)
            or report.get("manifest_sha256") != _sha256(manifest)
            or original.get("manifest_sha256") != _sha256(manifest)
            or original.get("code_sha256") != report.get("code_sha256")
            or not compatible_environment(original.get("environment", {}), current)
            or not original.get("environment", {}).get("platform", "").startswith("Windows")
            or report.get("test_executed") is not False):
        raise ValueError("Deployment parity evidence stale or incompatible")
    key = f"{loaded.metadata.model}/{loaded.metadata.category}"
    result = report["models"][key]
    if (result["checkpoint_sha256"] != loaded.metadata.checkpoint_sha256
            or result["calibration_sha256"] != loaded.metadata.calibration_sha256
            or result["threshold"] != loaded.metadata.threshold
            or result["status"] != "passed" or not result["scores"]):
        raise ValueError("Deployment parity model binding invalid")
    archived = original["models"][key]
    if any(archived[k] != result[k] for k in ("checkpoint_sha256", "calibration_sha256", "threshold")):
        raise ValueError("Windows reference binding invalid")
    with manifest.open(encoding="utf-8") as handle:
        expected = {r["image_path"]: r["sha256"] for r in csv.DictReader(handle)
                    if r["split"] == "val" and r["category"] == loaded.metadata.category}
    baseline = {r["image_path"]: r for r in archived["scores"]}
    if (len(result["scores"]) != len(expected) or len(baseline) != len(expected)
            or {r["image_path"] for r in result["scores"]} != set(expected)):
        raise ValueError("Deployment parity coverage incomplete")
    for row in result["scores"]:
        ref = baseline[row["image_path"]]
        a, b, threshold = row["score"], ref["score"], result["threshold"]
        if (row["sha256"] != expected[row["image_path"]] or ref["sha256"] != row["sha256"]
                or not math.isfinite(a) or not math.isfinite(b)
                or abs(a-b) > POLICY["atol"] + POLICY["rtol"] * abs(b)
                or ((a > threshold) != (b > threshold)
                    and max(abs(a-threshold), abs(b-threshold)) > POLICY["atol"])):
            raise ValueError("Deployment numerical parity failed")
