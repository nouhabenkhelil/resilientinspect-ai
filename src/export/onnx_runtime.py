"""FP32 ONNX deployment contract. Historical scientific modules stay unchanged."""
from collections import OrderedDict
from importlib.metadata import version
import json
import math
from pathlib import Path
from threading import Lock

import numpy as np
import torch

from resilientinspect.data.audit import _sha256
from resilientinspect.data.synthetic import normalize_image
from resilientinspect.evaluation import evaluate_ae, evaluate_transfer

POLICY = {"id": "onnx_fp32_cpu_v1", "tensor_atol": 1e-4, "tensor_rtol": 1e-4,
          "map_atol": 1e-5, "map_rtol": 1e-4, "score_atol": 1e-5, "score_rtol": 1e-4,
          "decision_changes": "both_scores_within_1e-5_of_original_threshold"}


def environment():
    return {**evaluate_transfer._environment(), **{k: version(k) for k in ("onnx", "onnxruntime")},
            "provider": "CPUExecutionProvider", "intra_op_threads": 2, "inter_op_threads": 1,
            "optimization": "ORT_ENABLE_ALL", "spinning": False}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    path.with_suffix(".sha256").write_text(_sha256(path) + "\n", encoding="ascii")


def checked_json(path):
    path = Path(path)
    if path.with_suffix(".sha256").read_text().strip() != _sha256(path):
        raise ValueError(f"Invalid SHA256: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def inputs(sample, variant):
    images = sample["image"].unsqueeze(0).to(dtype=torch.float32)
    return normalize_image(images) if variant.startswith("T") else images


def score_output(output, sample, variant):
    output = torch.as_tensor(output)
    expected = (1,) if variant.startswith("T") else (1, 3, 256, 256)
    if tuple(output.shape) != expected or output.dtype != torch.float32 or not torch.isfinite(output).all():
        raise ValueError("Invalid FP32 model output shape/type/values")
    if variant.startswith("T"):
        return float(output.sigmoid()[0]), None
    error = evaluate_ae.anomaly_maps(sample["image"].unsqueeze(0), output)[0].numpy()
    return evaluate_ae.image_score(error, sample["valid_mask"][0].numpy(), top_fraction=0.01), error


def score_parity(a, b, threshold):
    error = abs(a-b)
    changed = (a > threshold) != (b > threshold)
    boundary = max(abs(a-threshold), abs(b-threshold)) <= POLICY["score_atol"]
    return {"score_error": error, "decision_changed": changed,
            "boundary_change": bool(changed and boundary),
            "score_passed": math.isfinite(a) and math.isfinite(b) and error <= POLICY["score_atol"] + POLICY["score_rtol"] * abs(a),
            "decision_passed": not changed or boundary}


def session(path):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.add_session_config_entry("session.inter_op.allow_spinning", "0")
    result = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
    if result.get_providers() != ["CPUExecutionProvider"]:
        raise ValueError("CPUExecutionProvider exclusively required")
    if (len(result.get_inputs()) != 1 or result.get_inputs()[0].name != "images"
            or result.get_inputs()[0].shape != [1,3,256,256]
            or result.get_inputs()[0].type != "tensor(float)"):
        raise ValueError("Invalid ONNX input contract")
    return result


def artifact_directory(root, metadata):
    return root / "artifacts/onnx" / metadata.model / metadata.category


def verify_artifact(root, metadata):
    import onnx
    from backend.app.portability import code_hashes
    directory = artifact_directory(root, metadata)
    meta = checked_json(directory / "metadata.json")
    for key, value in {"model": metadata.model, "category": metadata.category,
                       "checkpoint_sha256": metadata.checkpoint_sha256,
                       "calibration_sha256": metadata.calibration_sha256, "threshold": metadata.threshold}.items():
        if meta.get(key) != value:
            raise ValueError(f"ONNX source binding mismatch: {key}")
    if meta.get("code_sha256") != code_hashes(root) or meta.get("opset") != 18:
        raise ValueError("ONNX code/opset provenance stale")
    if set(meta.get("files", {})) != {"model.onnx"}:
        raise ValueError("Single graph file required")
    for name, digest in meta["files"].items():
        if Path(name).name != name or not (directory / name).is_file() or _sha256(directory / name) != digest:
            raise ValueError("ONNX graph/data SHA256 mismatch")
    graph = onnx.load(str(directory / "model.onnx"), load_external_data=False)
    # Export is deliberately single-file; unknown external paths are refused.
    if any(t.data_location == onnx.TensorProto.EXTERNAL for t in graph.graph.initializer):
        raise ValueError("External ONNX data not declared by the single-file contract")
    onnx.checker.check_model(graph, full_check=True)
    return directory, meta


def admit(root, metadata):
    directory, meta = verify_artifact(root, metadata)
    platform = "linux" if environment()["platform"].startswith("Linux") else "windows"
    path = directory / f"parity-{platform}.json"
    proof = checked_json(path)
    from backend.app.portability import code_hashes
    if (proof.get("status") != "passed" or proof.get("policy") != POLICY
            or proof.get("environment") != environment() or proof.get("code_sha256") != code_hashes(root)
            or proof.get("metadata_sha256") != _sha256(directory / "metadata.json")
            or proof.get("manifest_sha256") != evaluate_ae.manifest_digest(root / "data/manifests/manifest.csv")
            or proof.get("test_executed") is not False or not proof.get("rows")):
        raise ValueError("ONNX parity evidence absent, failed or stale")
    counts = {"normal": proof["normal_examples"], "synthetic": proof["synthetic_examples"]}
    import csv
    with (root / "data/manifests/manifest.csv").open(encoding="utf-8") as handle:
        expected = sum(r["split"] == "val" and r["category"] == metadata.category for r in csv.DictReader(handle))
    if counts["normal"] != expected or counts["synthetic"] != (2*expected if metadata.model.startswith("T") else 0):
        raise ValueError("ONNX parity validation coverage incomplete")
    if len(proof["rows"]) != sum(counts.values()) or len({r["sample_id"] for r in proof["rows"]}) != len(proof["rows"]):
        raise ValueError("ONNX parity examples missing or duplicated")
    for row in proof["rows"]:
        checks = score_parity(row["pytorch_score"], row["onnx_score"], metadata.threshold)
        if not checks["score_passed"] or not checks["decision_passed"] or not row["tensor_passed"] or not row["map_passed"]:
            raise ValueError("ONNX measured numerical parity failed")
    return directory / "model.onnx", proof


class SessionCache:
    """Bounded sessions reused across requests. Idle thread spinning disabled."""
    def __init__(self, capacity=2):
        self.capacity, self.items, self.lock = capacity, OrderedDict(), Lock()

    def get(self, path):
        key = str(path)
        with self.lock:
            if key not in self.items:
                self.items[key] = session(path)
            self.items.move_to_end(key)
            while len(self.items) > self.capacity:
                self.items.popitem(last=False)
            return self.items[key]
