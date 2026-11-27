"""Observable DAG and isolated failure demonstrations. Never train or publish."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import platform

from prefect import flow, task, get_run_logger
from prefect.artifacts import create_markdown_artifact
from prefect.cache_policies import NO_CACHE
from prefect.context import get_run_context
from prefect.task_runners import ThreadPoolTaskRunner

from . import checks
from .checks import Settings, TransientCheckError


async def retry_transient(task, task_run, state):
    return isinstance(await state.aresult(raise_on_failure=False), TransientCheckError)


def step(name):
    return task(name=name, cache_policy=NO_CACHE, persist_result=False, retry_condition_fn=retry_transient)


@step("01-environment-and-protected-snapshot")
async def environment(settings: Settings):
    settings.validate()
    baseline = await asyncio.to_thread(checks.bounded_snapshot, settings)
    get_run_logger().info("Environment verified; %s protected files recorded; no training permitted", len(baseline))
    return {"status": "passed", "python": platform.python_version(), "snapshot": baseline}


@step("02-dvc-public-metadata")
async def dvc_metadata(settings: Settings):
    return await asyncio.to_thread(checks.metadata, settings)


@step("03-dvc-artifact-availability-and-sha256")
async def dvc_artifacts(settings: Settings):
    result = await asyncio.to_thread(checks.dvc, settings)
    get_run_logger().info("DVC release verified: %s files / %s bytes", result["files"], result["bytes"])
    return result


@step("04-mlflow-tracking-and-registry-readonly")
async def mlflow_evidence(settings: Settings):
    result = await asyncio.to_thread(checks.probe, settings, "mlflow")
    get_run_logger().info("Tracking: %s models; Registry: %s versions; mode=ro", result["tracked_models"], result["registry_models"])
    return result


@step("05-scientific-fastapi-health")
async def api_health(settings: Settings):
    return await asyncio.to_thread(checks.api, settings)


@step("06-bounded-validation-inference")
async def light_evaluation(settings: Settings):
    result = await asyncio.to_thread(checks.evaluate, settings)
    get_run_logger().info("Light evaluation status: %s; no official metric rewritten", result["status"])
    return result


@step("07-protected-artifacts-unchanged")
async def preservation(settings: Settings, before: dict[str, str]):
    return await asyncio.to_thread(checks.bounded_immutable, settings, before)


@task(name="08-execution-report", cache_policy=NO_CACHE, persist_result=False, retries=0, timeout_seconds=30)
def execution_report(root: str, run_id: str, attempt: int, payload: dict):
    target = Path(root) / "mlops/local/orchestration/runs" / f"{run_id}-{attempt}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    reporting_error = None
    try:
        create_markdown_artifact(key="ri-orchestration-report", markdown=(
            f"# ResilientInspect orchestration: {payload['status']}\n\n"
            f"Mode: **{payload['mode']}**. Training: **never**.\n\n"
            f"Local report: `{target.relative_to(Path(root)).as_posix()}`\n\n"
            "The local JSON contains task states, genuine check results and failure details."
        ))
    except Exception as exc:
        reporting_error = exc
        payload = {**payload, "status": "failed", "reporting_error": str(exc)}
    with target.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    if reporting_error:
        raise reporting_error
    get_run_logger().info("Execution report: %s", target)
    return str(target)


def configured(task_function, settings):
    return task_function.with_options(retries=settings.retries, retry_delay_seconds=settings.retry_delay,
                                      timeout_seconds=settings.timeout)


@flow(name="resilientinspect-readonly-mlops", log_prints=True,
      task_runner=ThreadPoolTaskRunner(max_workers=2), retries=0, timeout_seconds=3600)
def mlops_flow(settings: Settings | None = None):
    """Verify existing DVC/MLflow/FastAPI and one validation example; no training."""
    settings = settings or Settings()
    context = get_run_context().flow_run
    payload = {"mode": "real-readonly-checks", "run_id": str(context.id), "started_at": datetime.now(timezone.utc).isoformat(),
               "status": "failed", "settings": asdict(settings), "checks": {}, "task_states": {}}
    futures = {}
    baseline = None
    error = None
    try:
        env = futures["environment"] = configured(environment, settings).submit(settings)
        initial = env.result()
        baseline = initial["snapshot"]
        payload["checks"]["environment"] = {k: v for k, v in initial.items() if k != "snapshot"}
        meta = futures["metadata"] = configured(dvc_metadata, settings).submit(settings, wait_for=[env])
        dvc = futures["dvc"] = configured(dvc_artifacts, settings).submit(settings, wait_for=[meta])
        tracking = futures["mlflow"] = configured(mlflow_evidence, settings).submit(settings, wait_for=[dvc])
        api = futures["api"] = configured(api_health, settings).submit(settings, wait_for=[tracking])
        evaluation = futures["evaluation"] = configured(light_evaluation, settings).submit(settings, wait_for=[api])
        evaluation.result()  # Resolve the terminal future, including every dependency.
    except Exception as exc:
        error = exc
        payload["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        for name, future in futures.items():
            future.wait()
            payload["task_states"][name] = future.state.name
            if future.state.is_completed() and name != "environment":
                payload["checks"][name] = future.result()
            elif future.state.is_failed():
                # Report the actual failed check, not merely a downstream NotReady.
                try:
                    future.result()
                except Exception as exc:
                    error = exc
                    payload["error"] = {"type": type(exc).__name__, "message": str(exc), "check": name}
        if baseline is not None:
            try:
                payload["checks"]["preservation"] = configured(preservation, settings).submit(settings, baseline).result()
            except Exception as exc:
                error = exc
                payload["preservation_error"] = str(exc)
        payload["status"] = "failed" if error else "completed"
        payload["ended_at"] = datetime.now(timezone.utc).isoformat()
        report = execution_report(settings.root, str(context.id), context.run_count, payload)
    if error:
        raise error  # A failure report must never convert a failed DAG into Completed.
    return {"status": "completed", "report": report, "checks": payload["checks"]}


@task(name="DEMO-only-retry-or-failure", cache_policy=NO_CACHE, persist_result=False,
      retry_condition_fn=retry_transient)
async def demonstration_step(mode: str):
    attempt = get_run_context().task_run.run_count
    get_run_logger().info("DEMONSTRATION ONLY: mode=%s attempt=%s; no scientific artifact touched", mode, attempt)
    if mode == "transient" and attempt == 1:
        raise TransientCheckError("DEMO temporary failure: the next attempt is allowed to recover")
    if mode == "permanent":
        raise checks.CheckError("DEMO permanent failure: must remain Failed")
    if mode == "timeout":
        await asyncio.sleep(2)
    return {"mode": mode, "attempts": attempt, "scientific_processing": False}


@flow(name="resilientinspect-orchestration-demo", log_prints=True, retries=0, timeout_seconds=60)
def demo_flow(mode: str = "transient", retries: int = 1, retry_delay: float = 2):
    """Separate simulation for the defence: success, transient retry, failure, timeout."""
    if mode not in {"success", "transient", "permanent", "timeout"} or not 0 <= retries <= 5 or not 0 <= retry_delay <= 10:
        raise ValueError("Invalid bounded demonstration parameters")
    context = get_run_context().flow_run
    future = demonstration_step.with_options(retries=retries, retry_delay_seconds=retry_delay,
                                             timeout_seconds=.2 if mode == "timeout" else 15).submit(mode)
    error = None
    result = None
    try:
        result = future.result()
    except Exception as exc:
        error = exc
    payload = {"mode": "DEMONSTRATION-ONLY", "scenario": mode, "run_id": str(context.id),
               "status": "failed" if error else "completed", "result": result,
               "task_state": future.state.name, "error": str(error) if error else None}
    report = execution_report(str(checks.ROOT), str(context.id), context.run_count, payload)
    if error:
        raise error
    return {"status": "completed", "report": report, **result}
