"""Install a SHA256-pinned official actionlint release and validate both workflows."""
import hashlib
from pathlib import Path
import platform
import subprocess
import tarfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.7.12"
RELEASES = {
    "Linux": ("linux_amd64.tar.gz", "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"),
    "Windows": ("windows_amd64.zip", "6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9"),
}


def main():
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Pinned actionlint binaries support x86_64 only")
    suffix, expected = RELEASES[platform.system()]
    directory = ROOT / "scripts/ci/local/tools"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f"actionlint_{VERSION}_{suffix}"
    if not archive.exists():
        url = f"https://github.com/rhysd/actionlint/releases/download/v{VERSION}/{archive.name}"
        with urlopen(url, timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise SystemExit("Official actionlint archive SHA256 mismatch")
    name = "actionlint.exe" if platform.system() == "Windows" else "actionlint"
    binary = directory / name
    # Extract only the named binary, never arbitrary archive paths.
    if suffix.endswith(".zip"):
        with zipfile.ZipFile(archive) as packed:
            data = packed.read(name)
    else:
        with tarfile.open(archive) as packed:
            data = packed.extractfile(name).read()
    binary.write_bytes(data)
    binary.chmod(0o755)
    subprocess.run([str(binary), "-shellcheck=", "-pyflakes=", ".github/workflows/ci-tests.yml", ".github/workflows/docker-build.yml"], cwd=ROOT, check=True)
    print(f"actionlint {VERSION}: workflow syntax, contexts and expressions passed (shell snippets disabled; Python scripts used).")


if __name__ == "__main__":
    main()
