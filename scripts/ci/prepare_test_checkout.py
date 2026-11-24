"""Copy only Git candidates to a new ignored artifact-free Linux test context."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from repository_guard import ROOT, path_problem


def main():
    directory = ROOT / "scripts/ci/local"
    directory.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix="test-checkout-", dir=directory))
    names = set(subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")) - {""}
    for name in names:
        if path_problem(name):
            raise ValueError(f"Private file cannot enter CI test context: {name}")
        source, destination = ROOT / name, target / name
        if source.is_symlink():
            raise ValueError("No symlinks in clean test context")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    # Isolated metadata is enough for git check-ignore/provenance unit tests.
    # No commit is created and the original repository is never modified.
    subprocess.run(["git", "init", "--quiet", str(target)], check=True)
    # Ignore the serving build allowlist: this separate context contains only audited candidates.
    (target / ".dockerignore").write_text("**/node_modules/\n**/__pycache__/\n", encoding="utf-8")
    (directory / "test-checkout.json").write_text(json.dumps({"path": str(target), "files": len(names), "scientific_artifacts": False}, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
