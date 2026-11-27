"""Bounded read-only checks; scientific dependencies stay in their existing venv."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "mlops/local/orchestration"


class CheckError(RuntimeError):
    """Permanent integrity/configuration error: retrying cannot repair evidence."""


class TransientCheckError(CheckError):
    """Temporary availability error, eligible for a bounded retry."""


@dataclass(frozen=True)
class Settings:
    root: str = str(ROOT)
    mlops_python: str = str(ROOT / (".venv-mlops/Scripts/python.exe" if os.name == "nt" else ".venv-mlops/bin/python"))
    scientific_python: str = str(ROOT / (".venv-mlops/Scripts/python.exe" if os.name == "nt" else ".venv-mlops/bin/python"))
    api_url: str = "http://127.0.0.1:8001/health"
    api_container: str = "resilientinspect-industrial-science-1"
    evaluation: str = "auto"
    retries: int = 1
    retry_delay: float = 2
    timeout: float = 300
    remote_status: bool = False

    def validate(self):
        if not 0 <= self.retries <= 5 or not 0 <= self.retry_delay <= 60 or not 5 <= self.timeout <= 3600:
            raise CheckError("Retry/timeout configuration outside safe bounds")
        if self.evaluation not in {"auto", "required", "off"}:
            raise CheckError("Unknown evaluation policy")
        if not Path(self.root).is_dir():
            raise CheckError("Repository root missing")
        if not Path(self.mlops_python).is_file():
            raise CheckError("Existing MLOps interpreter missing; no automatic scientific installation")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise CheckError("Evidence path escapes the repository")
    return path


def snapshot(settings: Settings) -> dict[str, str]:
    """Hash canonical release files and protected code, without serialising their bytes."""
    root = Path(settings.root)
    paths = {safe_path(root, item["path"]) for item in read(root / "mlops/release-manifest.json")["entries"]}
    for folder in ("src", "backend/app", "configs"):
        paths.update(p for p in (root / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    paths.update({root / "pyproject.toml", root / "mlops/release-manifest.json"})
    paths.update(p for p in (root / "deployment/reports/portability").glob("*.*") if p.suffix in {".json", ".sha256"})
    paths.add(root / "mlops/local/mlflow/tracking.db")
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)}


def immutable(settings: Settings, before: dict[str, str]):
    root = Path(settings.root)
    changed = [name for name, expected in before.items()
               if not safe_path(root, name).is_file() or digest(safe_path(root, name)) != expected]
    if changed:
        raise CheckError(f"Protected artifacts changed: {changed[:5]}")
    return {"status": "passed", "files": len(before), "changed": 0}


def command(settings: Settings, argv: list[str], *, timeout: float | None = None, input_text: str | None = None):
    """No shell, bounded children, no commands that train/pull/push/replace models."""
    try:
        result = subprocess.run(argv, cwd=settings.root, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout or settings.timeout - 1, input=input_text,
                                env={**os.environ, "PYTHONIOENCODING": "utf-8", "DVC_NO_ANALYTICS": "true",
                                     "DVC_SITE_CACHE_DIR": str(Path(settings.root) / ".dvc/site-cache"),
                                     "MLFLOW_DISABLE_TELEMETRY": "true", "OMP_NUM_THREADS": "2",
                                     "MKL_NUM_THREADS": "2", "MPLBACKEND": "Agg"})
    except (subprocess.TimeoutExpired, TimeoutError) as error:
        raise TransientCheckError("Read-only subprocess timed out") from error
    if result.returncode:
        # Errors are local reports/logs only, never include argv/env credentials.
        raise CheckError(f"Read-only check exited {result.returncode}: {result.stderr[-1800:]}")
    return result.stdout


def bounded_snapshot(settings: Settings):
    return json.loads(command(settings, [sys.executable, str(Path(__file__).resolve()), "snapshot", settings.root]))


def bounded_immutable(settings: Settings, before: dict[str, str]):
    return json.loads(command(settings, [sys.executable, str(Path(__file__).resolve()), "immutable", settings.root],
                              input_text=json.dumps(before)))


def probe(settings: Settings, action: str, *, scientific=False):
    text = command(settings, [settings.scientific_python if scientific else settings.mlops_python,
                             str(Path(settings.root) / "mlops/orchestration/probe.py"), action])
    return json.loads(text.strip().splitlines()[-1])


def metadata(settings: Settings):
    command(settings, [settings.mlops_python, "scripts/ci/check_dvc_metadata.py"])
    return {"status": "passed", "check": "existing public DVC metadata verifier"}


def dvc(settings: Settings):
    verified = probe(settings, "dvc")
    args = [settings.mlops_python, "-m", "dvc", "status", "--json"]
    if json.loads(command(settings, args)) != {}:
        raise CheckError("DVC copies/cache differ from the current pointers")
    if settings.remote_status and json.loads(command(settings, [*args, "--cloud"])) != {}:
        raise CheckError("DVC remote is not synchronized")
    return {"status": "passed", **verified, "remote_checked": settings.remote_status}


def api(settings: Settings):
    if settings.api_container:
        # Existing internal service: do not publish a port or bypass portal authentication.
        program = "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=10))))"
        try:
            payload = json.loads(command(settings, ["docker", "exec", settings.api_container, "python", "-c", program], timeout=15))
        except CheckError as error:
            raise TransientCheckError("Existing internal FastAPI health temporarily unavailable") from error
        transport = "docker exec /health (existing internal FastAPI)"
    else:
        address = urlparse(settings.api_url)
        if address.scheme != "http" or address.hostname not in {"localhost", "127.0.0.1", "::1"} or address.username or address.password:
            raise CheckError("Only explicit local HTTP health checks are supported")
        try:
            with urlopen(settings.api_url, timeout=10) as response:
                payload = json.load(response)
        except HTTPError as error:
            if error.code >= 500:
                raise TransientCheckError(f"API temporarily unavailable ({error.code})") from error
            raise CheckError(f"API health refused ({error.code}); authentication is never bypassed") from error
        except (URLError, TimeoutError) as error:
            raise TransientCheckError("Local API health unavailable") from error
        transport = "local HTTP /health"
    if payload.get("status") != "ok" or payload.get("ready_models_by_engine") != {"pytorch": 15, "onnxruntime": 14}:
        raise CheckError("Scientific API is degraded or expected engine coverage changed")
    return {"status": "passed", "transport": transport, "health": payload}


def evaluate(settings: Settings):
    if settings.evaluation == "off":
        return {"status": "skipped", "reason": "explicitly disabled; no evaluation claimed"}
    root = Path(settings.root)
    if not Path(settings.scientific_python).is_file() or not (root / "data/raw/mvtec_ad/bottle/train/good").is_dir():
        if settings.evaluation == "required":
            raise CheckError("Required lightweight evaluation dependencies/data missing")
        return {"status": "skipped", "reason": "scientific interpreter or validation data unavailable"}
    available = probe(settings, "dependencies", scientific=True)
    if not available["available"]:
        if settings.evaluation == "required":
            raise CheckError("Required scientific dependencies missing")
        return {"status": "skipped", "reason": "scientific dependencies missing", "missing": available["missing"]}
    return probe(settings, "evaluate", scientific=True)


if __name__ == "__main__":
    configuration = Settings(root=sys.argv[2])
    if sys.argv[1] == "snapshot":
        outcome = snapshot(configuration)
    elif sys.argv[1] == "immutable":
        outcome = immutable(configuration, json.load(sys.stdin))
    else:
        raise ValueError("Unknown bounded integrity operation")
    print(json.dumps(outcome))
