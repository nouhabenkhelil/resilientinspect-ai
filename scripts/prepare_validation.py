"""Generate offline-only read-only mounts for the full normal validation split."""
import csv
from pathlib import Path
import yaml

PROJECT = Path(__file__).resolve().parents[1]


def main():
    volumes = [{"type": "bind", "source": "./artifacts/onnx", "target": "/app/artifacts/onnx", "read_only": False,
                "bind": {"create_host_path": False}},
               {"type": "bind", "source": "./deployment/reports/portability", "target": "/evidence",
                "read_only": False, "bind": {"create_host_path": False}}]
    with (PROJECT / "data/manifests/manifest.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["split"] != "val":
                continue
            relative = Path(row["image_path"])
            if relative.is_absolute() or ".." in relative.parts or row["source_split"] != "train" or row["label"] != "0":
                raise ValueError("Unsafe validation provenance")
            volumes.append({"type": "bind", "source": "${RI_DATASET_DIR:-./data/raw/mvtec_ad}/" + relative.as_posix(),
                            "target": "/validation/" + relative.as_posix(), "read_only": True,
                            "bind": {"create_host_path": False}})
    path = PROJECT / "deployment/docker-compose.validation.yml"
    path.write_text("# Offline validation only; never use for serving.\n" + yaml.safe_dump(
        {"services": {"backend": {"volumes": volumes}}}, sort_keys=False), encoding="utf-8")
    print(f"Prepared {len(volumes)-2} validation image mounts; no test/train split mounted.")


if __name__ == "__main__":
    main()
