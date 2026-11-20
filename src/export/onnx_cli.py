"""Export, full validation parity and CPU benchmark, without training/test access."""
import argparse
import csv
from datetime import datetime, timezone
import gc
import io
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch

from backend.app.config import Settings
from backend.app.models import ModelStore
from backend.app.portability import code_hashes
from resilientinspect.data.audit import _sha256
from resilientinspect.data.dataset import MVTecDataset
from resilientinspect.data.synthetic import SyntheticAnomalyDataset
from resilientinspect.evaluation import evaluate_ae, a1_checkpoints
from resilientinspect.training.train_ae import seed_everything
from . import onnx_runtime as runtime

ROOT = Path(__file__).resolve().parents[2]


def load_reference(root, variant, category):
    """Offline scientific loader: full selection, hashes, provenance, frozen thresholds."""
    store = ModelStore(Settings(project_root=root))
    if variant.startswith("T"):
        run = list((root / f"artifacts/transfer_runs/{variant}/{category}/seed42").glob("full_*"))
        loaded = store._load_transfer(variant, category)
        return loaded, run[0] / "best.pt"
    module = evaluate_ae if variant == "B0" else a1_checkpoints
    checkpoints, _ = module.discover_checkpoints(root / f"artifacts/{variant.lower()}_runs")
    checkpoint = checkpoints[category]
    loaded = store._load_ae(variant, checkpoint, evaluate_ae.manifest_digest(store.settings.manifest))
    return loaded, Path(checkpoint.path)


def examples(root, dataset, loaded, checkpoint, synthetic=True):
    manifest = root / "data/manifests/manifest.csv"
    normal = MVTecDataset(manifest, dataset, split="val", categories=[loaded.metadata.category], verify_hashes=True)
    if any(r["source_split"] != "train" or r["label"] != "0" for r in normal.rows):
        raise ValueError("Only normal original val sources allowed")
    for index in range(len(normal)):
        sample = normal[index]
        yield "normal:" + sample["image_path"], "normal", sample
    if synthetic and loaded.metadata.model.startswith("T"):
        plan = json.loads(checkpoint.with_name("synthetic_plan.json").read_text())
        validation = SyntheticAnomalyDataset(manifest, dataset, category=loaded.metadata.category,
            split="val", config=plan["config"], seed=42, plan=plan)
        for index in range(len(validation)):
            sample = validation[index]
            yield sample["sample_id"], "synthetic", {**sample, "image": sample["raw_image"]}


def export(root, loaded, checkpoint):
    import onnx
    directory = runtime.artifact_directory(root, loaded.metadata)
    directory.mkdir(parents=True, exist_ok=True)
    graph = directory / "model.onnx"
    is_transfer = loaded.metadata.model.startswith("T")
    network = loaded.network.eval().float()
    # Legacy exporter explicit: static batch/spatial contract, no hidden dynamo fallback.
    torch.onnx.export(network, (torch.zeros(1,3,256,256),), str(graph), dynamo=False,
                      input_names=["images"], output_names=["logits" if is_transfer else "reconstruction"],
                      opset_version=18, external_data=False, do_constant_folding=True)
    onnx.checker.check_model(onnx.load(str(graph)), full_check=True)
    probe = runtime.session(graph)
    output = probe.get_outputs()[0]
    if output.shape != ([1] if is_transfer else [1,3,256,256]) or output.type != "tensor(float)":
        raise ValueError("ONNX output contract invalid")
    weights = io.BytesIO()
    torch.save(network.state_dict(), weights)
    meta = {"model": loaded.metadata.model, "category": loaded.metadata.category,
            "checkpoint_sha256": loaded.metadata.checkpoint_sha256,
            "calibration_sha256": loaded.metadata.calibration_sha256, "threshold": loaded.metadata.threshold,
            "files": {"model.onnx": _sha256(graph)}, "opset": 18,
            "input": {"name": "images", "shape": [1,3,256,256], "dtype": "float32",
                      "normalization": loaded.metadata.normalization},
            "output": {"name": output.name, "shape": output.shape, "dtype": "float32"},
            "environment": runtime.environment(), "exporter": "torch.onnx.export(dynamo=False)",
            "code_sha256": code_hashes(root), "created_at": datetime.now(timezone.utc).isoformat(),
            "checkpoint_training_bytes": checkpoint.stat().st_size,
            "inference_state_dict_bytes": weights.tell(), "graph_bytes": graph.stat().st_size}
    runtime.write_json(directory / "metadata.json", meta)
    return meta


def validate(root, dataset, loaded, checkpoint):
    directory, meta = runtime.verify_artifact(root, loaded.metadata)
    ort = runtime.session(directory / "model.onnx")
    rows = []
    for sample_id, kind, sample in examples(root, dataset, loaded, checkpoint):
        inputs = runtime.inputs(sample, loaded.metadata.model)
        with torch.inference_mode():
            reference = loaded.network(inputs)
        output = ort.run(None, {"images": inputs.numpy()})[0]
        if output.dtype != np.float32 or tuple(output.shape) != tuple(reference.shape) or not np.isfinite(output).all():
            raise ValueError("Output shape/finite/type mismatch")
        delta = np.abs(reference.numpy()-output)
        tensor_passed = bool(np.all(delta <= runtime.POLICY["tensor_atol"] + runtime.POLICY["tensor_rtol"] * np.abs(reference.numpy())))
        a, a_map = runtime.score_output(reference, sample, loaded.metadata.model)
        b, b_map = runtime.score_output(output, sample, loaded.metadata.model)
        map_error, map_passed = 0., True
        if a_map is not None:
            map_delta = np.abs(a_map-b_map)
            map_error = float(map_delta.max())
            map_passed = bool(np.all(map_delta <= runtime.POLICY["map_atol"] + runtime.POLICY["map_rtol"]*np.abs(a_map)))
        rows.append({"sample_id": sample_id, "kind": kind, "label": sample["label"],
                     "pytorch_score": a, "onnx_score": b, "tensor_passed": tensor_passed,
                     "tensor_max_error": float(delta.max()), "tensor_mean_error": float(delta.mean()),
                     "map_max_error": map_error, "map_passed": map_passed,
                     **runtime.score_parity(a,b,loaded.metadata.threshold)})
    failed = sum(not all(r[k] for k in ("tensor_passed", "map_passed", "score_passed", "decision_passed")) for r in rows)
    report = {"status": "passed" if failed == 0 else "failed", "policy": runtime.POLICY,
              "reference_engine": "pytorch", "candidate_engine": "onnxruntime", "dtype": "float32",
              "model": loaded.metadata.model, "category": loaded.metadata.category,
              "metadata_sha256": _sha256(directory / "metadata.json"), "environment": runtime.environment(),
              "code_sha256": code_hashes(root), "manifest_sha256": evaluate_ae.manifest_digest(root / "data/manifests/manifest.csv"),
              "test_executed": False, "normal_examples": sum(r["kind"] == "normal" for r in rows),
              "synthetic_examples": sum(r["kind"] == "synthetic" for r in rows), "failures": failed,
              "max_score_error": max(r["score_error"] for r in rows),
              "mean_score_error": float(np.mean([r["score_error"] for r in rows])),
              "decision_changes": sum(r["decision_changed"] for r in rows),
              "unjustified_changes": sum(not r["decision_passed"] for r in rows), "rows": rows}
    os_name = "linux" if platform.system() == "Linux" else "windows"
    runtime.write_json(directory / f"parity-{os_name}.json", report)
    return report


def stats(values):
    values = np.array(values)
    return {"mean_ms": float(values.mean()), "p50_ms": float(np.median(values)),
            "p95_ms": float(np.quantile(values,.95)), "std_ms": float(values.std()),
            "images_per_second": float(1000/values.mean())}


def benchmark(root, dataset, loaded, checkpoint, iterations=100, warmup=20, load_ms=None):
    import psutil
    if iterations < 100 or warmup < 20:
        raise ValueError("At least 100 measurements and 20 warmups required")
    graph, parity = runtime.admit(root, loaded.metadata)
    started = time.perf_counter()
    ort = runtime.session(graph)
    ort_load = (time.perf_counter()-started)*1000
    samples = [s for _,_,s in examples(root,dataset,loaded,checkpoint,synthetic=False)]
    prepared = [runtime.inputs(s,loaded.metadata.model) for s in samples]
    def run(engine, condition, index):
        sample = samples[index % len(samples)]
        inp = prepared[index % len(samples)] if condition == "forward" else runtime.inputs(sample,loaded.metadata.model)
        if engine == "pytorch":
            with torch.inference_mode():
                output = loaded.network(inp)
        else:
            output = ort.run(None, {"images": inp.numpy()})[0]
        if condition == "score":
            runtime.score_output(output,sample,loaded.metadata.model)
    result, raw = {}, []
    for condition in ("forward", "score"):
        for engine in ("pytorch", "onnxruntime"):
            for i in range(warmup):
                run(engine,condition,i)
        times = {"pytorch": [], "onnxruntime": []}
        for i in range(iterations):
            for engine in (("pytorch","onnxruntime") if i%2 == 0 else ("onnxruntime","pytorch")):
                started = time.perf_counter_ns()
                run(engine,condition,i)
                elapsed = (time.perf_counter_ns()-started)/1e6
                times[engine].append(elapsed)
                raw.append({"model": loaded.metadata.model, "category": loaded.metadata.category,
                            "engine": engine, "condition": condition, "iteration": i, "ms": elapsed})
        result[condition] = {engine: stats(rows) for engine,rows in times.items()}
        result[condition]["speedup_mean"] = result[condition]["pytorch"]["mean_ms"]/result[condition]["onnxruntime"]["mean_ms"]
    explanation = None
    if loaded.metadata.model.startswith("T"):
        from resilientinspect.evaluation.gradcam import gradcam
        for i in range(warmup):
            gradcam(loaded.network, prepared[i % len(prepared)])
        times = []
        for i in range(iterations):
            started = time.perf_counter_ns()
            gradcam(loaded.network, prepared[i % len(prepared)])
            elapsed = (time.perf_counter_ns()-started)/1e6
            times.append(elapsed)
            raw.append({"model": loaded.metadata.model, "category": loaded.metadata.category,
                        "engine": "pytorch", "condition": "gradcam", "iteration": i, "ms": elapsed})
        explanation = stats(times)
    return {"model": loaded.metadata.model, "category": loaded.metadata.category, "measurements": iterations,
            "warmup": warmup, "batch": 1, "dtype": "float32", "threads": 2, "conditions": result,
            "pytorch_load_with_integrity_ms": load_ms, "onnx_session_load_ms": ort_load,
            "rss_process_both_engines_bytes": psutil.Process().memory_info().rss,
            "parity_status": parity["status"], "decision_changes": parity["decision_changes"],
            "sizes": runtime.checked_json(graph.with_name("metadata.json")), "api_ms": None,
            "gradcam": explanation}, raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "validate", "benchmark"))
    parser.add_argument("--models", nargs="+", default=["B0", "A1", "T0", "T1", "T2"])
    parser.add_argument("--categories", nargs="+", default=["bottle", "hazelnut", "leather"])
    parser.add_argument("--dataset", type=Path, default=ROOT / "data/raw/mvtec_ad")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/experiments/onnx")
    args = parser.parse_args()
    seed_everything(42,2)
    reports, raw = [], []
    for variant in args.models:
        if variant not in ("B0","A1","T0","T1","T2"):
            parser.error("Unknown model")
        for category in args.categories:
            if category not in ("bottle","hazelnut","leather"):
                parser.error("Unknown category")
            started = time.perf_counter()
            loaded, checkpoint = load_reference(ROOT,variant,category)
            load_ms = (time.perf_counter()-started)*1000
            if args.action == "export":
                report = export(ROOT,loaded,checkpoint)
            elif args.action == "validate":
                report = validate(ROOT,args.dataset,loaded,checkpoint)
            else:
                report, rows = benchmark(ROOT,args.dataset,loaded,checkpoint,load_ms=load_ms)
                raw.extend(rows)
            reports.append(report)
            print(f"{args.action}: {variant}/{category} {report.get('status','completed')}",flush=True)
            del loaded
            gc.collect()
    args.output.mkdir(parents=True,exist_ok=True)
    summary = {"action": args.action, "environment": runtime.environment(), "processor": platform.processor(),
               "logical_cpu_count": __import__('os').cpu_count(), "test_executed": False, "models": reports}
    runtime.write_json(args.output / ("parity.json" if args.action == "validate" else args.action + ".json"), summary)
    if raw:
        with (args.output / "benchmark.csv").open('w',newline='',encoding='utf-8') as handle:
            writer = csv.DictWriter(handle,fieldnames=list(raw[0]));writer.writeheader();writer.writerows(raw)
    return int(any(r.get("status") == "failed" for r in reports))


if __name__ == "__main__":
    raise SystemExit(main())
