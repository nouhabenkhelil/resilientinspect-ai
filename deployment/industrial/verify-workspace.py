"""Read-only provenance/exclusion check. No scientific exports or inference reruns."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "deployment/industrial/local"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    sources = sorted((ROOT / "backend/app").glob("*.py")) + sorted((ROOT / "src").rglob("*.py"))
    sources += [ROOT / "deployment/validate_portability.py"]
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}
    proofs = []
    for name in ("windows", "linux"):
        path = ROOT / f"deployment/reports/portability/{name}.json"
        data = json.loads(path.read_text())
        assert data["code_sha256"] == hashes, f"Stale {name} code binding"
        assert sha(path) == path.with_suffix(".sha256").read_text().strip(), f"Invalid {name} digest"
        proofs.append({"name": name, "status": data["status"], "models": len(data["models"]), "sha256": sha(path)})
    onnx = []
    for path in sorted((ROOT / "artifacts/onnx").glob("*/*/metadata.json")):
        metadata = json.loads(path.read_text())
        assert sha(path) == path.with_suffix(".sha256").read_text().strip()
        assert metadata["code_sha256"] == hashes
        assert metadata["files"] == {"model.onnx": sha(path.parent / "model.onnx")}
        statuses = {}
        for platform in ("windows", "linux"):
            proof = path.parent / f"parity-{platform}.json"
            parity = json.loads(proof.read_text())
            assert sha(proof) == proof.with_suffix(".sha256").read_text().strip()
            assert parity["metadata_sha256"] == sha(path) and parity["code_sha256"] == hashes
            expected = "failed" if (metadata["model"], metadata["category"]) == ("T1", "bottle") else "passed"
            assert parity["status"] == expected
            statuses[platform] = parity["status"]
        onnx.append({"model": metadata["model"], "category": metadata["category"], "parity": statuses})
    assert len(onnx) == 15
    baseline = LOCAL / "baseline.json"
    preserved = []
    if baseline.exists():
        for entry in json.loads(baseline.read_text(encoding="utf-8-sig")):
            assert sha(ROOT / entry["path"]) == entry["sha256"], "Pre-existing edit changed: " + entry["path"]
            preserved.append(entry["path"])
    changed = subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", "src", "backend/app", "pyproject.toml", "frontend/DESIGN.md", "docker-compose.yml", "docker-compose.mounts.yml"], cwd=ROOT, stderr=subprocess.DEVNULL).decode().splitlines()
    assert not changed, "Protected source/design/legacy Compose changed"
    candidates = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    assert not any(n.startswith("deployment/industrial/local/") or n.startswith(".venv-portal/") for n in candidates)
    result = {"code_files": len(hashes), "proofs": proofs, "onnx_bindings": onnx, "preexisting_edits_preserved": preserved,
              "protected_files_unchanged": True, "private_local_files_excluded": True}
    LOCAL.mkdir(parents=True, exist_ok=True)
    (LOCAL / "workspace-verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
