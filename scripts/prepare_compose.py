"""Generate read-only file mounts. Never copy or rewrite scientific inputs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath

import yaml


PROJECT = Path(__file__).resolve().parents[1]
CATEGORIES = ("bottle", "hazelnut", "leather")


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def generate(project: Path, overrides: dict[str, str] | None = None) -> tuple[dict, dict]:
    overrides = overrides or {}
    definitions = {
        "RI_ARTIFACTS_DIR": ("artifacts", "artifacts"),
        "RI_MANIFESTS_DIR": ("data/manifests", "data/manifests"),
        "RI_CONFIGS_DIR": ("configs", "configs"),
        "RI_EVALUATION_DIR": ("reports/evaluation", "reports/evaluation"),
        "RI_PORTABILITY_DIR": ("reports/transfer/portability", "reports/transfer/portability"),
    }
    roots = {key: (project / overrides.get(key, default)).resolve()
             for key, (default, _) in definitions.items()}
    volumes, inventory, blockers = [], [], []
    targets = set()

    def mount(key: str, relative: str | Path) -> Path:
        relative = Path(relative)
        path = roots[key] / relative
        if (not path.is_file() or path.is_symlink()
                or not path.resolve().is_relative_to(roots[key])):
            raise ValueError(f"Required regular file missing or unsafe: {path}")
        default, destination = definitions[key]
        target = f"/app/{destination}/{relative.as_posix()}"
        if target in targets:
            return path
        targets.add(target)
        volumes.append({"type": "bind", "source": f"${{{key}:-./{default}}}/{relative.as_posix()}",
                        "target": target, "read_only": True, "bind": {"create_host_path": False}})
        inventory.append({"target": target, "sha256": sha256(path), "bytes": path.stat().st_size})
        return path

    def sources(run: Path, summary: dict) -> None:
        names = set()
        for original in summary.get("source_sha256", {}):
            name = original.replace("\\", "/").rsplit("/", 1)[-1]
            if name in names or Path(name).suffix not in (".py", ".yaml", ".toml"):
                raise ValueError(f"Unsafe or duplicate archived source name: {name}")
            names.add(name)
            mount("RI_ARTIFACTS_DIR", run / "source" / name)

    mount("RI_MANIFESTS_DIR", "manifest.csv")
    mount("RI_MANIFESTS_DIR", "preparation.json")
    for name in ("evaluate_ae_b0.yaml", "evaluate_transfer.yaml", "train_t0.yaml", "train_t1.yaml",
                 "train_t2.yaml", "synthetic_transfer.yaml"):
        mount("RI_CONFIGS_DIR", name)
    ae_protocol = sha256(roots["RI_CONFIGS_DIR"] / "evaluate_ae_b0.yaml")[:12]
    transfer_protocol = sha256(roots["RI_CONFIGS_DIR"] / "evaluate_transfer.yaml")[:12]

    # Mount ALL canonical full runs, so ambiguity remains visible to ModelStore.
    # Do not silently choose a new checkpoint, a smoke run or an MLflow copy.
    for variant in ("B0", "A1"):
        for category in CATEGORIES:
            parent = Path(f"{variant.lower()}_runs/{category}")
            runs = sorted((roots["RI_ARTIFACTS_DIR"] / parent).glob("full_*"))
            if not runs:
                raise ValueError(f"No full run for {variant}/{category}")
            for path in runs:
                run = path.relative_to(roots["RI_ARTIFACTS_DIR"])
                for name in ("best.pt", "summary.json", "effective_config.yaml"):
                    mount("RI_ARTIFACTS_DIR", run / name)
                if (path / "environment.json").exists():
                    mount("RI_ARTIFACTS_DIR", run / "environment.json")
                if variant == "A1":
                    for name in ("architecture.yaml", "provenance.json", "data_usage.json"):
                        if (path / name).exists():
                            mount("RI_ARTIFACTS_DIR", run / name)
                    sources(run, json.loads((path / "summary.json").read_text(encoding="utf-8")))
            directory = Path(f"{variant.lower()}/{ae_protocol}/{category}")
            calibration = mount("RI_EVALUATION_DIR", directory / "calibration.json")
            mount("RI_EVALUATION_DIR", directory / "calibration.sha256")
            stored_path = json.loads(calibration.read_text(encoding="utf-8"))["checkpoint"]["path"]
            if PureWindowsPath(stored_path).is_absolute():
                blockers.append({"model": variant, "category": category, "reason": "Frozen calibration compares an absolute Windows checkpoint path to the Linux path."})

    mount("RI_PORTABILITY_DIR", "validation_summary.json")
    for variant in ("T0", "T1", "T2"):
        for category in CATEGORIES:
            parent = Path(f"transfer_runs/{variant}/{category}/seed42")
            runs = sorted((roots["RI_ARTIFACTS_DIR"] / parent).glob("full_*"))
            if not runs:
                raise ValueError(f"No full run for {variant}/{category}")
            for path in runs:
                run = path.relative_to(roots["RI_ARTIFACTS_DIR"])
                for name in ("best.pt", "summary.json", "effective_config.yaml", "synthetic_plan.json",
                             "calibration.json", "calibration.sha256", "environment.json", "provenance.json"):
                    mount("RI_ARTIFACTS_DIR", run / name)
                summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
                sources(run, summary)
                relative = Path(f"{variant}/{category}/seed42/{summary['checkpoint_sha256'][:12]}/{transfer_protocol}/compatibility.json")
                report_path = mount("RI_PORTABILITY_DIR", relative)
                report = json.loads(report_path.read_text(encoding="utf-8"))
                if not report["evaluation_environment"]["platform"].startswith("Linux"):
                    blockers.append({"model": variant, "category": category, "reason": "Frozen CPU compatibility report requires the exact Windows platform; Linux is not validated."})

    document = {"services": {"scientific_files": {"volumes": volumes}}}
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "file_mounts": len(volumes),
              "linux_admission_blockers": blockers, "inputs": inventory,
              "scientific_files_modified": False, "dataset_images_read": False}
    return document, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument("--check", action="store_true", help="Verify the saved plan and all input hashes without writing")
    args = parser.parse_args()
    project = args.project.resolve()
    try:
        document, report = generate(project, {key: value for key, value in os.environ.items() if key.startswith("RI_")})
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Mount preparation failed: {error}\n")
    destination = project / "deployment"
    if args.check:
        saved = yaml.safe_load((project / "docker-compose.mounts.yml").read_text(encoding="utf-8"))
        inventory = json.loads((destination / "reports/input-inventory.json").read_text(encoding="utf-8"))
        if saved != document or inventory["inputs"] != report["inputs"]:
            parser.exit(1, "Mount plan or scientific input hashes changed; review before regenerating.\n")
        print(f"Verified {report['file_mounts']} unchanged scientific inputs; no file written.")
        return 0
    destination.mkdir(exist_ok=True)
    (destination / "reports").mkdir(exist_ok=True)
    (project / "docker-compose.mounts.yml").write_text(
        "# Generated by scripts/prepare_compose.py; paths only, never model contents.\n"
        + yaml.safe_dump(document, sort_keys=False, width=120), encoding="utf-8")
    (destination / "reports/input-inventory.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {report['file_mounts']} read-only file mounts; no input copied or modified.")
    if report["linux_admission_blockers"]:
        print(f"WARNING: {len(report['linux_admission_blockers'])} Linux admission blockers. See deployment/README.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
