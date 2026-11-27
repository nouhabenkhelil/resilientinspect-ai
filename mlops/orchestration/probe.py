"""Read-only adapter executed by the existing MLOps/scientific interpreter."""
from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4
from urllib.parse import urlparse
from urllib.request import url2pathname

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mlops"))
from common import read, records, sha256


def mlflow_evidence():
    """Validate actual SQLite records without constructing a migrating MLflow client."""
    database = ROOT / "mlops/local/mlflow/tracking.db"
    audit = read(ROOT / "mlops/local/historical-databases.json")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        for relative, expected in audit["sha256"].items():
            if sha256(ROOT / relative) != expected:
                raise ValueError("Historical database SHA256 changed")
            with sqlite3.connect((ROOT / relative).as_uri() + "?mode=ro", uri=True) as original:
                for (rid,) in original.execute("SELECT run_uuid FROM runs"):
                    for table, columns in (("metrics", "key,value,timestamp,run_uuid,step,is_nan"), ("params", "key,value,run_uuid")):
                        actual = db.execute(f"SELECT {columns} FROM {table} WHERE run_uuid=? AND key NOT LIKE 'official_test.%' ORDER BY 1,3", (rid,)).fetchall()
                        expected_rows = original.execute(f"SELECT {columns} FROM {table} WHERE run_uuid=? ORDER BY 1,3", (rid,)).fetchall()
                        if actual != expected_rows:
                            raise ValueError("Historical run parameters/metrics changed")
        rows = records()  # Existing canonical SHA256/calibration/export checks.
        tracking = read(ROOT / "reports/experiments/mlops_runs.json")["models"]
        for row in rows:
            linked = next(r for r in tracking if (r["model"], r["category"]) == (row["model"], row["category"]))
            rid = linked["run_id"]
            tags = dict(db.execute("SELECT key,value FROM tags WHERE run_uuid=?", (rid,)))
            if db.execute("SELECT status FROM runs WHERE run_uuid=?", (rid,)).fetchone() != ("FINISHED",):
                raise ValueError("Missing or unfinished tracked full run")
            for key in ("checkpoint_sha256", "calibration_sha256"):
                if tags.get("ri." + key) != row[key]:
                    raise ValueError("MLflow model binding changed")
            metrics = dict(db.execute("SELECT key,value FROM latest_metrics WHERE run_uuid=?", (rid,)))
            for name, value in row["image"].items():
                if value is not None and metrics.get("official_test.image." + name) != value:
                    raise ValueError("Official metric import differs from frozen evidence")
        registry = read(ROOT / "reports/experiments/mlops_registry.json")["models"]
        for candidate in registry:
            name, version = candidate["name"], int(candidate["version"])
            alias = db.execute("SELECT version FROM registered_model_aliases WHERE name=? AND alias='demo_candidate'", (name,)).fetchone()
            if alias != (version,) or candidate["status"] != "passed":
                raise ValueError("Registry version/alias evidence changed")
            tags = dict(db.execute("SELECT key,value FROM model_version_tags WHERE name=? AND version=?", (name, version)))
            if tags.get("ri.checkpoint_sha256") != candidate["checkpoint_sha256"] or tags.get("ri.packaging_sha256") != candidate["packaging_sha256"]:
                raise ValueError("Registry binding changed")
            location = db.execute("SELECT storage_location FROM model_versions WHERE name=? AND version=?", (name, version)).fetchone()
            if not location or urlparse(location[0]).scheme != "file":
                raise ValueError("Expected the existing local Registry storage")
            directory = Path(url2pathname(urlparse(location[0]).path)).resolve()
            if not directory.is_relative_to(ROOT / "mlops/local/mlflow/artifacts"):
                raise ValueError("Registry storage escaped the existing local artifact root")
            specification = yaml.safe_load((directory / "MLmodel").read_text(encoding="utf-8"))
            artifacts = specification["flavors"]["python_function"]["artifacts"]
            binding = read(directory / artifacts["binding"]["path"])
            fingerprint = hashlib.sha256((json.dumps(binding, sort_keys=True) + sha256(ROOT / "mlops/registry_model.py")).encode()).hexdigest()
            if fingerprint != candidate["packaging_sha256"]:
                raise ValueError("Registry packaged binding fingerprint mismatch")
            for key, expected in binding["sha256"].items():
                retrieved = (directory / artifacts[key]["path"]).resolve()
                if not retrieved.is_relative_to(directory) or sha256(retrieved) != expected:
                    raise ValueError("Registry packaged artifact SHA256 mismatch")
    return {"status": "passed", "tracked_models": len(rows), "registry_models": len(registry),
            "historical_runs": audit["preserved_run_ids"], "mode": "sqlite mode=ro; no tag/alias write"}


def evaluate():
    from resilientinspect.export.onnx_cli import load_reference, examples
    from resilientinspect.training.train_ae import seed_everything
    from backend.app.inference import predict
    seed_everything(42, 2)
    loaded, checkpoint = load_reference(ROOT, "T2", "bottle")
    sample_id, kind, sample = next(examples(ROOT, ROOT / "data/raw/mvtec_ad", loaded, checkpoint, synthetic=False))
    result = predict(loaded, sample, uuid4(), visualize=False)
    return {"status": "passed", "scope": "one normal validation image from original train; no test metrics",
            "sample_id": sample_id, "kind": kind, "prediction": result.model_dump(mode="json"),
            "training": False, "calibration": False, "official_metrics_written": False}


def main():
    action = sys.argv[1]
    if action == "dvc":
        from dvc_release import verify
        result = verify(ROOT)
    elif action == "mlflow":
        result = mlflow_evidence()
    elif action == "dependencies":
        missing = [p for p in ("torch", "torchvision", "numpy", "resilientinspect") if importlib.util.find_spec(p) is None]
        result = {"available": not missing, "missing": missing}
    elif action == "evaluate":
        result = evaluate()
    else:
        raise ValueError("Unknown read-only probe")
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
