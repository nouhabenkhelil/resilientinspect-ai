"""Inspect the Git index/current candidates, not ignored local scientific artifacts."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 5 * 1024 * 1024
FORBIDDEN_SUFFIXES = {".pt", ".pth", ".ckpt", ".onnx", ".safetensors", ".h5", ".hdf5", ".npy", ".npz", ".pkl", ".pickle", ".joblib", ".db", ".sqlite", ".sqlite3"}
PRIVATE_DIRS = {"mlruns", "mlartifacts", "node_modules", ".venv", ".venv-mlops", ".mlflow-ui", "__pycache__", ".aws", ".secrets", "secrets", "datasets", "mvtec_ad"}
PRIVATE_PREFIXES = ("artifacts/", "data/", ".dvc/cache/", ".dvc/tmp/", ".dvc/site-cache/", "mlops/local/", "mlops/dataset/", "mlops/deployment/", "scripts/ci/local/", "frontend/reports/screenshots/", "deployment/industrial/local/", "services/portal/local/")
SECRET_PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b"),
]


def path_problem(name):
    path = PurePosixPath(name)
    if path.name == ".gitkeep":
        return None
    if any(part.lower() in PRIVATE_DIRS or part.startswith(".venv-") for part in path.parts):
        return "private environment/cache/store directory"
    if name.startswith(PRIVATE_PREFIXES):
        return "private artifact/data output"
    if path.suffix.lower() in FORBIDDEN_SUFFIXES or re.search(r"\.(?:db|sqlite|sqlite3)-(?:wal|shm|journal)$", name):
        return "model/array/database artifact"
    if path.name.startswith(".env") and path.name != ".env.example":
        return "real environment file"
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
        return "credential/key file"
    if name == ".dvc/config.local":
        return "machine-specific DVC configuration"
    return None


def inspect_bytes(name, data, dataset_hashes):
    issues = []
    if len(data) > MAX_BYTES:
        issues.append("file exceeds 5 MiB (no automatic exceptions)")
    if data.startswith(b"SQLite format 3\x00"):
        issues.append("SQLite content, regardless of extension")
    if hashlib.sha256(data).hexdigest() in dataset_hashes:
        issues.append("MVTec image/mask content, regardless of path")
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        issues.append("credential/private-key pattern (value redacted)")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-untracked", action="store_true")
    args = parser.parse_args()
    flags = ["git", "ls-files", "--cached", "-z"]
    if args.include_untracked:
        flags += ["--others", "--exclude-standard"]
    names = set(subprocess.check_output(flags, cwd=ROOT).decode().split("\0")) - {""}
    manifest = json.loads((ROOT / "mlops/release-manifest.json").read_text(encoding="utf-8"))
    dataset_hashes = {r["sha256"] for r in manifest["entries"] if r["path"].startswith("data/raw/")}
    errors = []
    checked = 0
    for name in sorted(names):
        path = ROOT / name
        # Index entries scheduled for removal are absent from git ls-files already.
        if not path.is_file():
            errors.append((name, "tracked file missing from checkout"))
            continue
        reason = path_problem(name)
        if reason:
            errors.append((name, reason))
            continue
        if path.is_symlink():
            errors.append((name, "symlinks require an explicit policy review"))
            continue
        data = path.read_bytes()
        errors.extend((name, issue) for issue in inspect_bytes(name, data, dataset_hashes))
        # Renamed torch.save archives are rejected while legitimate Word docs remain allowed.
        if data.startswith(b"PK\x03\x04") and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                if any(n.endswith("/data.pkl") or n == "data.pkl" for n in archive.namelist()):
                    errors.append((name, "PyTorch checkpoint archive, regardless of extension"))
        checked += 1
    if errors:
        for name, reason in errors:
            print(f"BLOCKED {name}: {reason}")
        raise SystemExit(f"Repository guard failed: {len(errors)} findings; no secret values printed")
    print(f"Repository guard passed: {checked} files, 5 MiB limit, artifact/content/credential checks. Git history is not rewritten or certified secret-free.")


if __name__ == "__main__":
    main()
