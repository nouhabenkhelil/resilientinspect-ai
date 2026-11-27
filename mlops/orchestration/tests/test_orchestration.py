"""Synthetic fixtures, isolated Prefect SQLite. No real weights or services required."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest
from prefect.client.orchestration import get_client
from prefect.client.schemas.filters import FlowRunFilter, FlowRunFilterId
from prefect.testing.utilities import prefect_test_harness

from mlops.orchestration import checks, flows
from mlops.orchestration.checks import Settings, CheckError, TransientCheckError


@pytest.fixture(scope="session")
def engine():
    with prefect_test_harness(server_startup_timeout=60):
        yield


@pytest.fixture
def repository(tmp_path):
    files = {"artifacts/model.pt": b"fixture weights only", "pyproject.toml": b"# fixture",
             "src/sample.py": b"# protected fixture", "mlops/local/mlflow/tracking.db": b"fixture db"}
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = tmp_path / "mlops/release-manifest.json"
    manifest.write_text(json.dumps({"entries": [{"path": "artifacts/model.pt", "group": "deployment",
        "sha256": checks.digest(tmp_path / "artifacts/model.pt"), "bytes": 20}]}))
    return Settings(root=str(tmp_path), mlops_python=sys.executable, scientific_python=str(tmp_path / "missing-python"),
                    retries=1, retry_delay=.01, timeout=10)


def task_runs(flow_id):
    with get_client(sync_client=True) as client:
        return client.read_task_runs(flow_run_filter=FlowRunFilter(id=FlowRunFilterId(any_=[flow_id])))


@pytest.fixture
def stub_checks(monkeypatch):
    order = []
    def complete(name, result):
        def operation(*args, **kwargs):
            order.append(name)
            return result
        return operation
    monkeypatch.setattr(checks, "metadata", complete("metadata", {"status": "passed"}))
    monkeypatch.setattr(checks, "dvc", complete("dvc", {"status": "passed", "files": 1, "bytes": 20}))
    monkeypatch.setattr(checks, "probe", complete("mlflow", {"status": "passed", "tracked_models": 15, "registry_models": 3}))
    monkeypatch.setattr(checks, "api", complete("api", {"status": "passed"}))
    return order


def test_snapshot_detects_changes_and_traversal(repository):
    before = checks.snapshot(repository)
    assert checks.immutable(repository, before)["changed"] == 0
    Path(repository.root, "artifacts/model.pt").write_bytes(b"tampered fixture")
    with pytest.raises(CheckError, match="Protected artifacts changed"):
        checks.immutable(repository, before)
    with pytest.raises(CheckError, match="escapes"):
        checks.safe_path(Path(repository.root), "../outside")


def test_bounded_hash_worker_preserves_fixture_bytes(repository):
    before = checks.bounded_snapshot(repository)
    assert checks.bounded_immutable(repository, before)["files"] == len(before)
    assert checks.snapshot(repository) == before


def test_command_timeout_is_real_and_bounded(repository):
    started = time.monotonic()
    with pytest.raises(TransientCheckError, match="timed out"):
        checks.command(repository, [sys.executable, "-c", "import time; time.sleep(3)"], timeout=.1)
    assert time.monotonic() - started < 2


def test_command_nonzero_is_not_success(repository):
    with pytest.raises(CheckError, match="exited 7"):
        checks.command(repository, [sys.executable, "-c", "raise SystemExit(7)"])


@pytest.mark.parametrize("values", [{"retries": 6}, {"timeout": 0}, {"evaluation": "train"}, {"retry_delay": -1}])
def test_invalid_configuration_rejected(repository, values):
    with pytest.raises(CheckError):
        replace(repository, **values).validate()


def test_light_evaluation_skip_is_explicit_and_required_fails(repository):
    assert checks.evaluate(repository)["status"] == "skipped"
    assert checks.evaluate(replace(repository, evaluation="off"))["reason"].startswith("explicitly")
    with pytest.raises(CheckError, match="Required"):
        checks.evaluate(replace(repository, evaluation="required"))


def test_api_rejects_external_or_authenticated_destinations(repository):
    for url in ("https://external.invalid/health", "http://name:secret@localhost/health"):
        with pytest.raises(CheckError, match="local HTTP"):
            checks.api(replace(repository, api_container="", api_url=url))


def test_reporting_failure_never_leaves_a_completed_report(tmp_path, monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError("fixture reporting service outage")
    monkeypatch.setattr(flows, "create_markdown_artifact", unavailable)
    with pytest.raises(RuntimeError, match="reporting service"):
        flows.execution_report.fn(str(tmp_path), "fixture-report", 1, {"status": "completed", "mode": "fixture"})
    report = checks.read(tmp_path / "mlops/local/orchestration/runs/fixture-report-1.json")
    assert report["status"] == "failed"
    assert "reporting_error" in report


def test_internal_api_availability_error_is_retryable(repository, monkeypatch):
    def unavailable(*args, **kwargs):
        raise CheckError("fixture docker health connection error")
    monkeypatch.setattr(checks, "command", unavailable)
    with pytest.raises(TransientCheckError, match="temporarily unavailable"):
        checks.api(repository)


def test_real_flow_dependencies_report_and_immutability(engine, repository, stub_checks):
    before = checks.snapshot(repository)
    state = flows.mlops_flow(repository, return_state=True)
    assert state.is_completed()
    result = state.result()
    report = checks.read(Path(result["report"]))
    assert report["status"] == "completed"
    assert report["checks"]["evaluation"]["status"] == "skipped"
    assert report["checks"]["preservation"]["changed"] == 0
    assert checks.snapshot(repository) == before
    assert stub_checks == ["metadata", "dvc", "mlflow", "api"]
    runs = task_runs(state.state_details.flow_run_id)
    by_prefix = {run.name[:2]: run for run in runs}
    for current, previous in [("02", "01"), ("03", "02"), ("04", "03"), ("05", "04"), ("06", "05")]:
        dependencies = by_prefix[current].task_inputs["wait_for"]
        assert str(by_prefix[previous].id) in {str(item.id) for item in dependencies}


def test_critical_failure_blocks_dependents_and_writes_failed_report(engine, repository, stub_checks, monkeypatch):
    def broken(settings):
        raise CheckError("fixture integrity failure")
    monkeypatch.setattr(checks, "dvc", broken)
    state = flows.mlops_flow(repository, return_state=True)
    assert state.is_failed()
    assert "mlflow" not in stub_checks and "api" not in stub_checks
    reports = list(Path(repository.root, "mlops/local/orchestration/runs").glob("*.json"))
    assert len(reports) == 1
    report = checks.read(reports[0])
    assert report["status"] == "failed"
    assert report["task_states"]["dvc"] == "Failed"
    assert report["checks"]["preservation"]["changed"] == 0


def test_transient_real_task_retries_and_finishes(engine, repository, stub_checks, monkeypatch):
    attempts = []
    def temporary(settings):
        attempts.append(1)
        if len(attempts) == 1:
            raise TransientCheckError("fixture service temporarily unavailable")
        return {"status": "passed", "files": 1, "bytes": 20}
    monkeypatch.setattr(checks, "dvc", temporary)
    state = flows.mlops_flow(repository, return_state=True)
    assert state.is_completed() and len(attempts) == 2
    run = next(r for r in task_runs(state.state_details.flow_run_id) if r.name.startswith("03"))
    assert run.run_count == 2
    with get_client(sync_client=True) as client:
        names = {s.name for s in client.read_task_run_states(run.id)}
    assert {"AwaitingRetry", "Retrying", "Completed"} <= names


@pytest.mark.parametrize("mode,completed", [("success", True), ("transient", True), ("permanent", False), ("timeout", False)])
def test_demonstrations_have_genuine_prefect_states(engine, tmp_path, monkeypatch, mode, completed):
    monkeypatch.setattr(checks, "ROOT", tmp_path)
    state = flows.demo_flow(mode, retries=1, retry_delay=.01, return_state=True)
    assert state.is_completed() is completed
    if completed:
        assert state.result()["attempts"] == (2 if mode == "transient" else 1)
    report = checks.read(next((tmp_path / "mlops/local/orchestration/runs").glob("*.json")))
    assert report["mode"] == "DEMONSTRATION-ONLY"
    assert report["status"] == ("completed" if completed else "failed")
