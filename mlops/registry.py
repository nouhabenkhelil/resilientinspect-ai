"""Package T2 checkpoints and verify actual MLflow Registry URIs on normal val."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import torch

from common import ROOT, LOCAL, REPORTS, read, records, sha256, write
from tracking import mlflow, client, experiment, track, verify_historical


def binding(row):
    directory = ROOT / f"artifacts/onnx/T2/{row['category']}"
    artifacts = {"checkpoint": row["checkpoint"], "calibration": row["calibration"],
                 "protocol": row["protocol"], "architecture": ROOT / "src/models/transfer.py",
                 "summary": row["run_dir"] / "summary.json", "onnx_metadata": directory / "metadata.json",
                 "onnx_windows_proof": directory / "parity-windows.json", "onnx_linux_proof": directory / "parity-linux.json"}
    hashes = {k: sha256(p) for k,p in artifacts.items()}
    payload = {"model": "T2", "category": row["category"], "original_run_id": row["summary"]["run_id"],
               "sha256": hashes, "onnx_available": row["onnx_available"],
               "selection": "retrospective demo_candidate; no independent validation",
               "input": "float32 [1,3,256,256], RGB letterboxed then ImageNet normalized; no image decoding in this model"}
    path = LOCAL / f"bindings/T2-{row['category']}.json"
    write(path,payload)
    artifacts["binding"] = path
    fingerprint = hashlib.sha256((json.dumps(payload,sort_keys=True) + sha256(ROOT / "mlops/registry_model.py")).encode()).hexdigest()
    return artifacts, fingerprint


def register():
    from mlflow.models import ModelSignature
    from mlflow.types import Schema, TensorSpec
    track()
    c = client()
    packaging = experiment(c,"Registry-Packaging")
    summaries = []
    for row in [r for r in records() if r["model"] == "T2"]:
        category = row["category"]
        name = f"ResilientInspect-T2-{category}"
        artifacts, fingerprint = binding(row)
        versions = c.search_model_versions(f"name = '{name}'")
        candidates = [v for v in versions if v.tags.get("ri.packaging_sha256") == fingerprint and v.status == "READY"]
        if len(candidates)>1: raise ValueError("Duplicate compatible registry versions")
        if candidates:
            version = candidates[0]
        else:
            training = next(r for r in read(REPORTS / "mlops_runs.json")["models"] if r["model"]=="T2" and r["category"]==category)
            tags = {"ri.checkpoint_sha256":row["checkpoint_sha256"],"ri.calibration_sha256":row["calibration_sha256"],
                    "ri.protocol_sha256":sha256(row["protocol"]),"ri.packaging_sha256":fingerprint,
                    "ri.original_run_id":row["summary"]["run_id"],"ri.training_tracking_run_id":training["run_id"],
                    "ri.available_engines":"pytorch,onnxruntime","ri.onnx":"validated",
                    "ri.selection":"retrospective; already observed experiments; no independent validation"}
            with mlflow.start_run(experiment_id=packaging,run_name=f"Package-T2-{category}",tags=tags) as run:
                info = mlflow.pyfunc.log_model(name="frozen_checkpoint",python_model=str(ROOT / "mlops/registry_model.py"),
                    artifacts={k:str(p) for k,p in artifacts.items()},
                    signature=ModelSignature(inputs=Schema([TensorSpec(np.dtype("float32"),(1,3,256,256))]),
                                             outputs=Schema([TensorSpec(np.dtype("float32"),(1,2))])),
                    pip_requirements=["--extra-index-url https://download.pytorch.org/whl/cpu"] +
                        [f"{p}=={importlib.metadata.version(p)}" for p in ("mlflow","torch","torchvision","numpy","pandas")],
                    metadata={"selection":tags["ri.selection"],"checkpoint_sha256":row["checkpoint_sha256"]})
                version = mlflow.register_model(info.model_uri,name,tags=tags)
                c.set_model_version_tag(name,version.version,"ri.packaging_run_id",run.info.run_id)
        # Alias is set only after successful inference verification below.
        summaries.append({"name":name,"version":str(version.version),"uri":f"models:/{name}/{version.version}",
                          "category":category,"checkpoint_sha256":row["checkpoint_sha256"],"packaging_sha256":fingerprint})
    write(LOCAL / "registry-candidates.json",summaries)
    verify()


def verify():
    from resilientinspect.export.onnx_cli import load_reference, examples
    from resilientinspect.export import onnx_runtime as runtime
    from resilientinspect.training.train_ae import seed_everything
    seed_everything(42,2)
    c=client()
    results=[]
    for candidate in read(LOCAL / "registry-candidates.json"):
        category=candidate["category"]
        row=next(r for r in records() if r["model"]=="T2" and r["category"]==category)
        artifacts,fingerprint=binding(row)
        if fingerprint!=candidate["packaging_sha256"]: raise ValueError("Registry candidate packaging is stale")
        uri=candidate["uri"]
        downloaded=Path(mlflow.artifacts.download_artifacts(artifact_uri=uri))
        specification=mlflow.models.Model.load(str(downloaded / "MLmodel"))
        paths=specification.flavors["python_function"]["artifacts"]
        for name,original in artifacts.items():
            retrieved=downloaded / paths[name]["path"]
            if sha256(original)!=sha256(retrieved): raise ValueError(f"Registry retrieval SHA256 mismatch: {name}")
        restored=mlflow.pyfunc.load_model(uri)
        loaded,checkpoint=load_reference(ROOT,"T2",category)
        errors=[];changes=0;checked=0
        for _,_,sample in examples(ROOT,ROOT / "data/raw/mvtec_ad",loaded,checkpoint,synthetic=False):
            inputs=runtime.inputs(sample,"T2")
            with torch.inference_mode(): expected=float(torch.sigmoid(loaded.network(inputs)).item())
            actual=restored.predict(inputs.numpy())
            score=float(actual[0,0])
            parity=runtime.score_parity(expected,score,loaded.metadata.threshold)
            if not parity["score_passed"] or not parity["decision_passed"]:
                raise ValueError(f"Registry inference parity failed: {category}")
            if bool(actual[0,1]) != (score>loaded.metadata.threshold): raise ValueError("Registry decision mismatch")
            errors.append(abs(expected-score));changes+=parity["decision_changed"];checked+=1
        c.set_registered_model_alias(candidate["name"],"demo_candidate",candidate["version"])
        # Load the alias too, proving that it resolves to a usable model.
        alias=mlflow.pyfunc.load_model(f"models:/{candidate['name']}@demo_candidate")
        np.testing.assert_array_equal(alias.predict(inputs.numpy()),restored.predict(inputs.numpy()))
        c.set_model_version_tag(candidate["name"],candidate["version"],"ri.registry_validation","passed_normal_val")
        results.append({**candidate,"alias":"demo_candidate","normal_validation_images":checked,
                        "max_score_error":max(errors),"decision_changes":changes,"sha256_verified":True,"status":"passed"})
    verify_historical()
    write(REPORTS / "mlops_registry.json",{"models":results,"total_normal_images":sum(r["normal_validation_images"] for r in results),
          "score_atol":runtime.POLICY["score_atol"],"score_rtol":runtime.POLICY["score_rtol"],
          "selection":"Retrospective demo candidates; no independent validation; no test images read."})
    print(json.dumps({"registered_models":len(results),"normal_validation_images":sum(r["normal_validation_images"] for r in results),
                      "max_score_error":max(r["max_score_error"] for r in results)}))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["register","verify"])
    args=parser.parse_args()
    if args.action=="register":register()
    else:verify()
