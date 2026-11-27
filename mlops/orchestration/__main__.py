"""PowerShell-friendly CLI; an explicit local Prefect server is required."""
import argparse
from dataclasses import asdict
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "demo", "serve"])
    parser.add_argument("--scenario", choices=["success", "transient", "permanent", "timeout"], default="transient")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--retry-delay", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--evaluation", choices=["auto", "required", "off"], default="auto")
    parser.add_argument("--api-container", default="resilientinspect-industrial-science-1",
                        help="Empty string selects --api-url instead; no ports are published")
    parser.add_argument("--api-url", default="http://127.0.0.1:8001/health")
    parser.add_argument("--remote-status", action="store_true")
    parser.add_argument("--interval", type=int, default=3600)
    args = parser.parse_args()
    os.environ.setdefault("PREFECT_API_URL", "http://127.0.0.1:4200/api")
    os.environ.setdefault("PREFECT_SERVER_ALLOW_EPHEMERAL_MODE", "false")
    from .checks import ROOT, Settings
    os.environ.setdefault("PREFECT_HOME", str(ROOT / "mlops/local/prefect"))
    from .flows import mlops_flow, demo_flow
    settings = Settings(retries=args.retries, retry_delay=args.retry_delay, timeout=args.timeout,
                        evaluation=args.evaluation, api_container=args.api_container, api_url=args.api_url,
                        remote_status=args.remote_status)
    if args.action == "demo":
        demo_flow(args.scenario, args.retries, args.retry_delay)
    elif args.action == "run":
        mlops_flow(settings)
    else:
        from prefect.schedules import Interval
        settings.validate()
        if args.interval < 30:
            parser.error("Scheduling interval must be at least 30 seconds")
        mlops_flow.serve(name="local-readonly", schedule=Interval(args.interval, timezone="Africa/Lagos"),
                         limit=1, pause_on_shutdown=True,
                         tags=["local", "read-only", "no-training"], parameters={"settings": asdict(settings)})


if __name__ == "__main__":
    main()
