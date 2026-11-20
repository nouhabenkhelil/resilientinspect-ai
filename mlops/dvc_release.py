"""Stage immutable copies, push locally, and restore into a fresh temporary repo."""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from common import ROOT, LOCAL, REPORTS, read, records, sha256, write


def call(*args, cwd=ROOT):
    subprocess.run([sys.executable, "-m", "dvc", *map(str, args)], cwd=cwd, check=True,
                   env={**os.environ, "DVC_NO_ANALYTICS": "true",
                        "DVC_SITE_CACHE_DIR": str(Path(cwd) / ".dvc/site-cache")})


def plan():
    dataset = set((ROOT / "data/manifests").glob("*")) - {ROOT / "data/manifests/.gitkeep"}
    with (ROOT / "data/manifests/manifest.csv").open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            for path_key, hash_key in (("image_path", "sha256"), ("mask_path", "mask_sha256")):
                if row[path_key]:
                    path = ROOT / "data/raw/mvtec_ad" / row[path_key]
                    if not path.resolve().is_relative_to(ROOT / "data/raw/mvtec_ad") or sha256(path) != row[hash_key]:
                        raise ValueError(f"Official dataset SHA256 mismatch: {path}")
                    dataset.add(path)
    inventory = read(ROOT / "deployment/reports/input-inventory.json")
    deployment = set()
    for entry in inventory["inputs"]:
        path = ROOT / entry["target"].removeprefix("/app/")
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"Frozen deployment source changed: {path}")
        deployment.add(path)
    allowed = {".json", ".csv", ".yaml", ".yml", ".py", ".toml", ".sha256"}
    for row in records():
        deployment.update(p for p in row["run_dir"].rglob("*") if p.is_file()
                          and p.suffix in allowed and not any(x.startswith('.') for x in p.relative_to(row["run_dir"]).parts))
        deployment.add(ROOT / row["source"])
        directory = ROOT / f"artifacts/onnx/{row['model']}/{row['category']}"
        deployment.update(p for p in directory.iterdir() if p.is_file() and p.suffix in {".json", ".sha256"})
        if row["onnx_available"]:
            graph = directory / "model.onnx"
            if sha256(graph) != read(directory / "metadata.json")["files"]["model.onnx"]:
                raise ValueError(f"Graph hash mismatch: {graph}")
            deployment.add(graph)
    deployment.update(p for p in (ROOT / "deployment/reports/portability").glob("*") if p.is_file())
    deployment.update((ROOT / "deployment/reports/portability/onnx-benchmark-linux").glob("*"))
    deployment.update((ROOT / "deployment/ONNX_PROTOCOL.md", ROOT / "deployment/reports/input-inventory.json"))
    for directory in ("a1_runs", "b0_runs", "transfer_runs"):
        deployment.add(ROOT / f"artifacts/{directory}/mlflow.db")
    return {"dataset": dataset, "deployment": deployment}


def stage():
    entries = []
    for group, paths in plan().items():
        for source in sorted(paths):
            if not source.is_file() or source.is_symlink():
                raise ValueError(f"Not a regular release file: {source}")
            relative = source.relative_to(ROOT)
            target = ROOT / "mlops" / group / relative
            digest = sha256(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if sha256(target) != digest:
                    raise ValueError(f"Refusing to overwrite an existing release copy: {target}")
            else:
                shutil.copy2(source, target)
            if sha256(target) != digest:
                raise ValueError(f"Copy mismatch: {target}")
            entries.append({"group": group, "path": relative.as_posix(), "sha256": digest, "bytes": source.stat().st_size})
    write(ROOT / "mlops/release-manifest.json", {"schema_version": 1, "entries": entries,
          "policy": "Official manifest hashes preserved; full checkpoints only; 14 accepted graphs; rejected T1/bottle proofs retained without graph; no smoke/cache."})
    if not (ROOT / ".dvc/.gitignore").exists():
        call("init", "--force")
    call("config", "--local", "core.site_cache_dir", ROOT / ".dvc/site-cache")
    call("config", "cache.type", "copy")
    call("config", "core.autostage", "false")
    call("config", "core.analytics", "false")
    for group in ("dataset", "deployment"):
        call("add", "--no-relink", f"mlops/{group}")
    print(f"Staged {len(entries)} verified copies; originals untouched.")


def push(remote):
    remote = remote.expanduser().resolve()
    if remote.is_relative_to(ROOT):
        raise ValueError("Local DVC remote must be outside the Git repository")
    call("remote", "add", "--local", "--force", "--default", "local_store", remote)
    call("push")
    call("status", "--cloud")
    write(LOCAL / "dvc-push.json", {"success": True, "remote": str(remote), "manifest_sha256": sha256(ROOT / "mlops/release-manifest.json")})


def verify(base):
    entries = read(ROOT / "mlops/release-manifest.json")["entries"]
    for entry in entries:
        path = base / "mlops" / entry["group"] / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"Restored SHA256 mismatch: {entry['path']}")
    return {"files": len(entries), "bytes": sum(e["bytes"] for e in entries), "sha256_failures": 0,
            "groups": {g: sum(e["group"] == g for e in entries) for g in ("dataset", "deployment")}}


def restore():
    receipt = read(LOCAL / "dvc-push.json")
    if receipt["manifest_sha256"] != sha256(ROOT / "mlops/release-manifest.json"):
        raise ValueError("Push receipt belongs to another release")
    target = Path(tempfile.mkdtemp(prefix="resilientinspect-dvc-restore-"))
    (target / "mlops").mkdir()
    for group in ("dataset", "deployment"):
        shutil.copy2(ROOT / f"mlops/{group}.dvc", target / f"mlops/{group}.dvc")
    call("init", "--no-scm", cwd=target)
    call("config", "cache.type", "copy", cwd=target)
    call("remote", "add", "--default", "local_store", receipt["remote"], cwd=target)
    call("pull", cwd=target)
    restored = verify(target)
    local = verify(ROOT)
    # Check the immutable sources too, independently of the release copies.
    for entry in read(ROOT / "mlops/release-manifest.json")["entries"]:
        if sha256(ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError(f"Original changed: {entry['path']}")
    write(LOCAL / "dvc-restoration.json", {**restored, "success": True, "isolated_empty_cache": True,
          "restore_directory": str(target), "originals_unchanged": True, "release_copies": local,
          "manifest_sha256": sha256(ROOT / "mlops/release-manifest.json")})
    print(f"Restored and SHA256-verified {restored['files']} files into {target}; originals unchanged.")


def materialize(destination):
    """Restore canonical paths in a separate checkout, never overwrite existing bytes."""
    if destination is None:
        raise ValueError("--destination is required")
    destination = destination.expanduser().resolve()
    if destination == ROOT or destination.is_relative_to(ROOT):
        raise ValueError("Use a separate recovery checkout outside the original repository")
    entries = read(ROOT / "mlops/release-manifest.json")["entries"]
    planned = {}
    # Preflight every file before writing, including duplicate paths between bundles.
    for entry in entries:
        source = ROOT / "mlops" / entry["group"] / entry["path"]
        target = destination / entry["path"]
        if not target.resolve().is_relative_to(destination) or source.is_symlink() or sha256(source) != entry["sha256"]:
            raise ValueError("Unsafe or corrupt recovery source")
        if entry["path"] in planned and planned[entry["path"]][1] != entry["sha256"]:
            raise ValueError("Conflicting release bundles")
        if target.exists() and (not target.is_file() or sha256(target) != entry["sha256"]):
            raise ValueError(f"Refusing to overwrite recovery target: {target}")
        planned[entry["path"]] = (source, entry["sha256"])
    for relative, (source, digest) in planned.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with source.open("rb") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst)
        if sha256(target) != digest:
            raise ValueError("Materialized SHA256 mismatch")
    print(f"Recovered {len(planned)} canonical files into {destination}; existing bytes preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["stage", "push", "restore", "verify", "materialize"])
    parser.add_argument("--remote", type=Path, default=ROOT.parent / "resilientinspect-dvc-store")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.action == "stage": stage()
    elif args.action == "push": push(args.remote)
    elif args.action == "restore": restore()
    elif args.action == "materialize": materialize(args.destination)
    else: print(verify(ROOT))
