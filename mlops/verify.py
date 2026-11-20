"""Verify final MLOps links and existing evidence; never regenerate numerical proofs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.request import urlopen

from common import ROOT, LOCAL, REPORTS, read, records, sha256, write
from tracking import client, verify_historical


def main():
    from backend.app.portability import code_hashes
    rows=records()
    verify_historical()
    expected_code=code_hashes(ROOT)
    for name in ("windows", "linux"):
        path=ROOT / f"deployment/reports/portability/{name}.json"
        if sha256(path)!=path.with_suffix(".sha256").read_text().strip() or read(path)["code_sha256"]!=expected_code:
            raise ValueError("PyTorch deployment proof changed or stale")
    for row in rows:
        directory=ROOT / f"artifacts/onnx/{row['model']}/{row['category']}"
        for name in ("metadata", "parity-windows", "parity-linux"):
            path=directory / f"{name}.json"
            if sha256(path)!=path.with_suffix(".sha256").read_text().strip() or read(path)["code_sha256"]!=expected_code:
                raise ValueError("ONNX deployment proof changed or stale")
    c=client()
    table=read(REPORTS / "mlops_runs.json")["models"]
    for row in rows:
        linked=next(r for r in table if (r["model"],r["category"])==(row["model"],row["category"]))
        run=c.get_run(linked["run_id"])
        if run.data.tags["ri.checkpoint_sha256"]!=row["checkpoint_sha256"] or run.data.tags["ri.calibration_sha256"]!=row["calibration_sha256"]:
            raise ValueError("Tracking link mismatch")
        for metric,value in row["image"].items():
            if value is not None and run.data.metrics[f"official_test.image.{metric}"]!=value:
                raise ValueError("Official metric not faithfully imported")
    registry=read(REPORTS / "mlops_registry.json")
    for row in registry["models"]:
        alias=c.get_model_version_by_alias(row["name"],"demo_candidate")
        if str(alias.version)!=str(row["version"]) or alias.tags["ri.checkpoint_sha256"]!=row["checkpoint_sha256"] or row["status"]!="passed":
            raise ValueError("Registry verification or alias mismatch")
        c.set_model_version_tag(row["name"],row["version"],"ri.pyfunc_engine","pytorch")
    receipt=read(LOCAL / "dvc-restoration.json")
    if not receipt["success"] or receipt["sha256_failures"] or not receipt["originals_unchanged"] or receipt["manifest_sha256"]!=sha256(ROOT / "mlops/release-manifest.json"):
        raise ValueError("DVC restoration receipt mismatch")
    entries=read(ROOT / "mlops/release-manifest.json")["entries"]
    if sum(e["path"].endswith(".pt") for e in entries)!=15 or sum(e["path"].endswith(".onnx") for e in entries)!=14:
        raise ValueError("Unexpected checkpoint/graph release coverage")
    for args in (["status","--json"],["status","--cloud","--json"]):
        result=subprocess.check_output([sys.executable,"-m","dvc",*args],cwd=ROOT,text=True,
                     env={**os.environ,"DVC_NO_ANALYTICS":"true","DVC_SITE_CACHE_DIR":str(ROOT / ".dvc/site-cache")})
        if json.loads(result)!={}: raise ValueError("DVC workspace/cache/remote not synchronized")
    with urlopen("http://127.0.0.1:18080/api/health",timeout=30) as response: health=json.load(response)
    if health["ready_models_by_engine"]!={"pytorch":15,"onnxruntime":14}: raise ValueError("Serving model count changed")
    with urlopen("http://127.0.0.1:5000/",timeout=30) as response:
        if response.status!=200 or b"MLflow" not in response.read(): raise ValueError("MLflow UI unavailable")
    browser=read(REPORTS / "mlops_browser.json")
    if browser["status"]!="passed" or browser["page_errors"]: raise ValueError("MLflow browser QA incomplete")
    protected=subprocess.check_output(["git","diff","HEAD","--name-only","--","pyproject.toml","src","backend/app","configs","deployment/validate_portability.py"],cwd=ROOT,text=True)
    if protected.strip(): raise ValueError("Protected scientific files modified")
    files=subprocess.check_output(["git","ls-files","--cached","--others","--exclude-standard"],cwd=ROOT,text=True).splitlines()
    forbidden=[]
    for name in files:
        path=ROOT / name
        if path.name==".gitkeep":continue
        if path.suffix.lower() in {".pt",".pth",".ckpt",".onnx",".sqlite",".sqlite3",".db"} or name.startswith(("mlops/local/","mlops/dataset/","mlops/deployment/","data/raw/",".dvc/cache/")):
            forbidden.append(name)
    if forbidden: raise ValueError(f"Forbidden Git artifacts: {forbidden}")
    result={"status":"passed","dvc_files_restored":receipt["files"],"dvc_bytes":receipt["bytes"],
            "dvc_sha256_failures":0,"dvc_status_clean":True,"dvc_remote_synchronized":True,
            "original_historical_databases_unchanged":True,"historical_runs_preserved":12,
            "full_training_runs_reused":6,"retrospective_full_imports":9,"technical_benchmark_runs":6,
            "registry_models":len(registry["models"]),"registry_normal_validation_images":registry["total_normal_images"],
            "registry_max_score_error":max(r["max_score_error"] for r in registry["models"]),
            "serving_models":health["ready_models_by_engine"],"mlflow_ui_http":200,"mlflow_browser":browser["status"],
            "protected_code_unchanged":True,"existing_numerical_proofs_retained":True,"forbidden_git_artifacts":forbidden}
    write(REPORTS / "mlops_verification.json",result)
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
