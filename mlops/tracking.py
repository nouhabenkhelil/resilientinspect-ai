"""Consolidate authentic logs without altering the three historical SQLite files."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import time

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")
os.environ.setdefault("MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR", "false")

import mlflow
from mlflow import MlflowClient
from mlflow.entities import Metric, Param
import yaml

from common import ROOT, LOCAL, REPORTS, read, records, sha256, write

DB = LOCAL / "mlflow/tracking.db"
ARTIFACTS = LOCAL / "mlflow/artifacts"
URI = "sqlite:///" + DB.as_posix()
SOURCES = [ROOT / f"artifacts/{name}/mlflow.db" for name in ("a1_runs", "b0_runs", "transfer_runs")]


def connect_readonly(path):
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def migrate():
    """Copy same-schema historical rows, retaining UUIDs, steps and timestamps."""
    audit_path = LOCAL / "historical-databases.json"
    hashes = {p.relative_to(ROOT).as_posix(): sha256(p) for p in SOURCES}
    if audit_path.exists():
        if read(audit_path)["sha256"] != hashes:
            raise ValueError("Historical MLflow database changed since initial audit")
        if not DB.exists():
            raise ValueError("Consolidated database missing; recover it before continuing")
        return
    if DB.exists():
        raise ValueError("Refusing to overwrite an unaudited tracking database")
    DB.parent.mkdir(parents=True, exist_ok=True)
    destination = sqlite3.connect(DB)
    first = connect_readonly(SOURCES[0])
    first.backup(destination)
    first.close()
    # This database is a new local consolidation; the originals remain byte-identical.
    destination.execute("UPDATE experiments SET name='Historical-A1' WHERE experiment_id=1")
    run_sources = []
    for index, source in enumerate(SOURCES):
        origin = connect_readonly(source)
        origin.row_factory = sqlite3.Row
        if index:
            experiment = dict(origin.execute("SELECT * FROM experiments WHERE experiment_id=1").fetchone())
            experiment["experiment_id"] = index + 1
            experiment["name"] = "Historical-" + ("B0" if index == 1 else "Transfer-Smoke")
            columns = list(experiment)
            destination.execute(f"INSERT INTO experiments ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", list(experiment.values()))
            for table in ("runs", "metrics", "latest_metrics", "params", "tags"):
                source_columns = [r[1] for r in origin.execute(f'PRAGMA table_info("{table}")')]
                target_columns = [r[1] for r in destination.execute(f'PRAGMA table_info("{table}")')]
                if source_columns != target_columns:
                    raise ValueError(f"Migration needs explicit schema review: {table}")
                for raw in origin.execute(f'SELECT * FROM "{table}"'):
                    row = dict(raw)
                    if table == "runs": row["experiment_id"] = index + 1
                    destination.execute(f'INSERT INTO "{table}" ({",".join(source_columns)}) VALUES ({",".join("?" for _ in source_columns)})', list(row.values()))
        for run in origin.execute("SELECT run_uuid,artifact_uri,experiment_id FROM runs"):
            rid = run["run_uuid"]
            local_artifacts = ARTIFACTS / rid
            original_artifacts = source.parent / "mlartifacts" / rid / "artifacts"
            artifact_source = original_artifacts
            if not artifact_source.is_dir():
                # A DVC release excludes duplicate MLflow weights and smoke artifacts.
                # Reattach canonical full-run files after recovery, with an explicit tag.
                canonical = list(source.parent.glob(f"*/full_{rid}"))
                if len(canonical) > 1: raise ValueError("Ambiguous historical run recovery")
                artifact_source = canonical[0] if canonical else None
            if artifact_source is not None:
                shutil.copytree(artifact_source, local_artifacts, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(".matplotlib", "__pycache__"))
                for path in artifact_source.rglob("*"):
                    if path.is_file() and not any(x in {".matplotlib", "__pycache__"} for x in path.parts):
                        if sha256(path) != sha256(local_artifacts / path.relative_to(artifact_source)):
                            raise ValueError("Historical artifact copy mismatch")
            else:
                local_artifacts.mkdir(parents=True, exist_ok=True)
            destination.execute("UPDATE runs SET artifact_uri=? WHERE run_uuid=?", (local_artifacts.as_uri(), rid))
            tags = {"ri.provenance": "original_training_log", "ri.source_database": source.relative_to(ROOT).as_posix(),
                    "ri.source_database_sha256": hashes[source.relative_to(ROOT).as_posix()],
                    "ri.original_artifact_uri": run["artifact_uri"], "ri.original_experiment_id": str(run["experiment_id"])}
            tags["ri.artifact_relocation"] = ("original_artifact_copy" if artifact_source == original_artifacts else
                    "canonical_full_files_recovered" if artifact_source else "smoke_artifacts_not_in_DVC_release; metadata_only")
            for key, value in tags.items():
                destination.execute("INSERT INTO tags(key,value,run_uuid) VALUES(?,?,?)", (key, value, rid))
            run_sources.append({"run_id": rid, "source": source.relative_to(ROOT).as_posix()})
        origin.close()
    for experiment_id in (1, 2, 3):
        destination.execute("UPDATE experiments SET artifact_location=? WHERE experiment_id=?", ((ARTIFACTS / f"experiment-{experiment_id}").as_uri(), experiment_id))
    destination.commit()
    destination.close()
    write(audit_path, {"sha256": hashes, "runs": run_sources, "preserved_run_ids": len(run_sources)})
    verify_historical()


def verify_historical():
    audit = read(LOCAL / "historical-databases.json")
    with sqlite3.connect(DB) as target:
        for source in SOURCES:
            if sha256(source) != audit["sha256"][source.relative_to(ROOT).as_posix()]:
                raise ValueError("Historical source database modified")
            with connect_readonly(source) as origin:
                for (rid,) in origin.execute("SELECT run_uuid FROM runs"):
                    for table, columns in (("metrics", "key,value,timestamp,run_uuid,step,is_nan"),
                                           ("params", "key,value,run_uuid")):
                        original = origin.execute(f"SELECT {columns} FROM {table} WHERE run_uuid=? ORDER BY 1,3", (rid,)).fetchall()
                        restored = target.execute(f"SELECT {columns} FROM {table} WHERE run_uuid=? AND key NOT LIKE 'official_test.%' ORDER BY 1,3", (rid,)).fetchall()
                        if original != restored:
                            raise ValueError(f"Historical {table} changed for {rid}")
                    fields = "name,status,start_time,end_time"
                    if origin.execute(f"SELECT {fields} FROM runs WHERE run_uuid=?", (rid,)).fetchone() != target.execute(f"SELECT {fields} FROM runs WHERE run_uuid=?", (rid,)).fetchone():
                        raise ValueError(f"Historical run timing/status changed for {rid}")
    return True


def client():
    mlflow.set_tracking_uri(URI)
    mlflow.set_registry_uri(URI)
    return MlflowClient(tracking_uri=URI, registry_uri=URI)


def experiment(c, name):
    found = c.get_experiment_by_name(name)
    return found.experiment_id if found else c.create_experiment(name, artifact_location=(ARTIFACTS / name).as_uri())


def flattened(value, prefix=""):
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict): result.update(flattened(item, name))
        else: result[name] = json.dumps(item) if not isinstance(item, str) else item
    return result


def numbers(value, prefix=""):
    return {key: float(item) for key, item in flatten_raw(value, prefix).items()
            if type(item) in (float, int) and math.isfinite(item)}


def flatten_raw(value, prefix=""):
    result = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict): result.update(flatten_raw(item, name))
        else: result[name] = item
    return result


def batch(c, rid, *, metrics=None, params=None):
    now = int(time.time() * 1000)
    c.log_batch(rid, metrics=[Metric(k, v, now, 0) for k, v in (metrics or {}).items()],
                params=[Param(k, str(v)) for k, v in (params or {}).items()])


def track():
    migrate()
    c = client()
    historical = {row["run_id"] for row in read(LOCAL / "historical-databases.json")["runs"]}
    imported_experiment = experiment(c, "Archived-Transfer-Imported")
    table = []
    for row in records():
        original_id = row["summary"]["run_id"]
        key = f"{row['model']}/{row['category']}/{row['checkpoint_sha256']}"
        if original_id in historical:
            rid, provenance = original_id, "original_training_log"
        else:
            found = c.search_runs([imported_experiment], f"tags.`ri.key` = '{key}'")
            if len(found) > 1: raise ValueError("Duplicate retrospective runs")
            if found: rid = found[0].info.run_id
            else:
                rid = c.create_run(imported_experiment, tags={"mlflow.runName": f"{row['model']}-{row['category']}-archived-full-seed42",
                    "ri.key": key, "ri.original_run_id": original_id, "ri.provenance": "retrospective_archive_import",
                    "ri.history_timestamps": "import time; epoch values and steps copied from archived summary"}).info.run_id
            provenance = "retrospective_archive_import"
            if c.get_run(rid).data.tags.get("ri.history_import_sha256") != sha256(row["run_dir"] / "summary.json"):
                if c.get_run(rid).data.metrics: raise ValueError("Partial import requires review; refusing duplicate history")
                config = yaml.safe_load((row["run_dir"] / "effective_config.yaml").read_text())
                batch(c, rid, params=flattened(config))
                now = int(time.time() * 1000)
                for epoch in row["summary"]["history"]:
                    c.log_batch(rid, metrics=[Metric(k, float(v), now, int(epoch["epoch"])) for k,v in epoch.items()
                                if k != "epoch" and type(v) in (float,int) and math.isfinite(v)])
                c.set_tag(rid, "ri.history_import_sha256", sha256(row["run_dir"] / "summary.json"))
                c.set_terminated(rid)
        tags = {"ri.key": key, "ri.variant": row["model"], "ri.category": row["category"], "ri.seed": "42",
                "ri.original_run_id": original_id, "ri.checkpoint_sha256": row["checkpoint_sha256"],
                "ri.calibration_sha256": row["calibration_sha256"], "ri.protocol_sha256": sha256(row["protocol"]),
                "ri.onnx": "validated" if row["onnx_available"] else "refused_numerical_tolerance",
                "ri.available_engines": "pytorch,onnxruntime" if row["onnx_available"] else "pytorch",
                "ri.selection": "retrospective; already observed experiments; no independent validation"}
        for k,v in tags.items(): c.set_tag(rid,k,v)
        report_path = ROOT / row["source"]
        report_hash = sha256(report_path)
        previous = c.get_run(rid).data.tags.get("ri.official_metrics_sha256")
        if previous and previous != report_hash: raise ValueError("Official metric source changed")
        if not previous:
            batch(c, rid, metrics={**numbers(row["image"], "official_test.image"),
                    **numbers(row["confusion"], "official_test.confusion"), "official_test.threshold": row["threshold"]})
            for path in [report_path, row["run_dir"] / "summary.json", row["run_dir"] / "effective_config.yaml",
                         row["calibration"], row["protocol"], row["checkpoint"]]:
                c.log_artifact(rid, str(path), "frozen_evidence")
            c.set_tag(rid, "ri.official_metrics_sha256", report_hash)
            c.set_tag(rid, "ri.official_metrics_provenance", "retrospective archived official test metrics; no evaluation rerun")
        table.append({"model": row["model"], "category": row["category"], "seed": 42,
                      "run_id": rid, "original_run_id": original_id, "provenance": provenance,
                      "checkpoint_sha256": row["checkpoint_sha256"], "calibration_sha256": row["calibration_sha256"],
                      "protocol_sha256": sha256(row["protocol"]), "onnx_available": row["onnx_available"],
                      "official_test_auroc": row["image"]["auroc"], "official_test_f1": row["image"]["f1"]})
    benchmark_source = ROOT / "deployment/reports/portability/onnx-benchmark-linux/benchmark.json"
    benchmark_sha = sha256(benchmark_source)
    if benchmark_source.with_suffix(".sha256").read_text().strip()!=benchmark_sha:
        raise ValueError("Benchmark SHA256 mismatch")
    benchmark=read(benchmark_source)
    public_benchmark=read(ROOT / "frontend/src/data/onnx-performance.json")
    if public_benchmark["environment"]!=benchmark["environment"]:
        raise ValueError("Benchmark environment export mismatch")
    technical = experiment(c, "Technical-ONNX-Benchmark")
    benchmark_ids = []
    for row in public_benchmark["models"]:
        raw=next(r for r in benchmark["models"] if (r["model"],r["category"])==(row["model"],row["category"]))
        if any(row[name]!=raw["conditions"][name] for name in ("score","forward")):
            raise ValueError("Benchmark numerical export mismatch")
        key = f"{benchmark_sha}/{row['model']}/{row['category']}"
        found = c.search_runs([technical], f"tags.`ri.key` = '{key}'")
        if len(found) > 1: raise ValueError("Duplicate benchmark imports")
        if found: rid = found[0].info.run_id
        else:
            rid = c.create_run(technical, tags={"mlflow.runName": f"{row['model']}-{row['category']}-CPU",
                "ri.key": key, "ri.provenance": "retrospective_technical_benchmark_import", "ri.source_sha256": benchmark_sha}).info.run_id
            batch(c,rid,metrics=numbers(row),params={"model":row["model"],"category":row["category"],"dtype":"float32","threads":2,"batch_size":1,"warmup":20,"iterations":100})
            for path in [benchmark_source, benchmark_source.with_suffix(".csv"), ROOT / "deployment/ONNX_PROTOCOL.md"]:
                c.log_artifact(rid,str(path),"measured_evidence")
            c.set_terminated(rid)
        if c.get_run(rid).data.tags.get("ri.full_benchmark_metrics_sha256")!=benchmark_sha:
            batch(c,rid,metrics=numbers(raw,"measured"))
            c.set_tag(rid,"ri.full_benchmark_metrics_sha256",benchmark_sha)
        benchmark_ids.append(rid)
    verify_historical()
    write(REPORTS / "mlops_runs.json", {"models": table, "benchmark_run_ids": benchmark_ids,
          "historical_runs_preserved": len(historical), "original_databases_unchanged": True})
    with (REPORTS / "mlops_runs.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    print("Tracking verified: 6 full training logs reused, 9 archive imports, 6 technical benchmarks; 12 historical runs preserved.")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["migrate", "track", "verify"])
    args=parser.parse_args()
    if args.action == "migrate": migrate()
    elif args.action == "track": track()
    else: print(verify_historical())
