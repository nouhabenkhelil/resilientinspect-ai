"""Execute isolated demonstration scenarios against the explicit local Prefect server."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .checks import OUTPUT, ROOT

os.environ.setdefault("PREFECT_API_URL", "http://127.0.0.1:4200/api")
os.environ.setdefault("PREFECT_HOME", str(ROOT / "mlops/local/prefect"))
os.environ.setdefault("PREFECT_SERVER_ALLOW_EPHEMERAL_MODE", "false")

from prefect.client.orchestration import get_client
from prefect.client.schemas.filters import FlowRunFilter, FlowRunFilterId

from .flows import demo_flow


def main():
    evidence = {"scenarios": [], "status": "failed"}
    for mode, completed in (("success", True), ("transient", True), ("permanent", False), ("timeout", False)):
        state = demo_flow(mode, retries=1, retry_delay=2, return_state=True)
        if state.is_completed() != completed:
            raise AssertionError(f"Unexpected flow state for {mode}: {state.name}")
        flow_id = state.state_details.flow_run_id
        with get_client(sync_client=True) as client:
            deadline = time.monotonic() + 15
            while True:
                tasks = client.read_task_runs(flow_run_filter=FlowRunFilter(id=FlowRunFilterId(any_=[flow_id])))
                matches = [task for task in tasks if task.name.startswith("DEMO-only")]
                demo = matches[0] if matches else None
                names = [event.name for event in client.read_task_run_states(demo.id)] if demo else []
                if demo and demo.state.is_final() and names and names[-1] in {"Completed", "Failed", "TimedOut"}:
                    break
                if time.monotonic() > deadline:
                    raise AssertionError("Task event history did not reach the Prefect API")
                time.sleep(.25)
            if mode == "transient" and not {"AwaitingRetry", "Retrying", "Completed"} <= set(names):
                raise AssertionError("No real retry state history was recorded")
            if mode == "permanent" and not demo.state.is_failed():
                raise AssertionError("Permanent failure was hidden")
            if mode == "timeout" and demo.state.name != "TimedOut":
                raise AssertionError("Real async task timeout was not recorded")
        evidence["scenarios"].append({"mode": mode, "flow_run_id": str(flow_id), "flow_state": state.name,
                                      "task_run_id": str(demo.id), "task_states": names, "attempts": demo.run_count})
    evidence["status"] = "passed"
    target = OUTPUT / "runtime-verification.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
