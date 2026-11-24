"""Validate public DVC metadata without data/cache access or contacting a remote."""
from collections import Counter
import configparser
import json
from pathlib import Path, PurePosixPath
import re

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    configuration = configparser.ConfigParser()
    configuration.read(ROOT / ".dvc/config", encoding="utf-8")
    if configuration.get("cache", "type") != "copy":
        raise ValueError("Expected independent copy cache")
    if configuration.getboolean("core", "autostage"):
        raise ValueError("DVC must not stage private files automatically")
    # Personal paths and remote URLs belong in ignored config.local, not public config.
    if any(section.startswith('remote ') for section in configuration.sections()):
        raise ValueError("Public DVC config unexpectedly contains a remote")
    manifest = json.loads((ROOT / "mlops/release-manifest.json").read_text(encoding="utf-8"))
    entries = manifest["entries"]
    identities = set()
    for entry in entries:
        identity = (entry["group"], entry["path"])
        path = PurePosixPath(entry["path"])
        if identity in identities or path.is_absolute() or ".." in path.parts or "\\" in entry["path"] or ":" in entry["path"]:
            raise ValueError("Duplicate/unsafe DVC release entry")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) or type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise ValueError("Invalid SHA256/size in release manifest")
        identities.add(identity)
    groups = Counter(entry["group"] for entry in entries)
    if set(groups) != {"dataset", "deployment"}:
        raise ValueError("Unexpected DVC release groups")
    for group, count in groups.items():
        pointer = yaml.safe_load((ROOT / f"mlops/{group}.dvc").read_text(encoding="utf-8"))
        outputs = pointer["outs"]
        if len(outputs) != 1:
            raise ValueError("Expected one directory per DVC pointer")
        output = outputs[0]
        if output["path"] != group or output["hash"] != "md5" or not re.fullmatch(r"[0-9a-f]{32}\.dir", output["md5"]):
            raise ValueError("Invalid DVC pointer target/hash")
        if output["nfiles"] != count or output["size"] != sum(e["bytes"] for e in entries if e["group"] == group):
            raise ValueError("DVC pointer and SHA256 manifest coverage differ")
    weights = [e for e in entries if e["path"].endswith(".pt")]
    graphs = [e for e in entries if e["path"].endswith(".onnx")]
    if len(weights) != 15 or any("/full_" not in e["path"] or "/smoke_" in e["path"] for e in weights):
        raise ValueError("DVC must contain exactly 15 canonical full checkpoints")
    if len(graphs) != 14 or any("/T1/bottle/" in e["path"] for e in graphs):
        raise ValueError("DVC ONNX coverage must retain the T1/bottle refusal")
    print(f"DVC metadata passed: {len(entries)} file references, 15 full checkpoints, 14 graphs; no remote accessed or artifacts claimed present.")


if __name__ == "__main__":
    main()
