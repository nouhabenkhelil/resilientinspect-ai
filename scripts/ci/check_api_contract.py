"""Compare a technical OpenAPI snapshot to actual FastAPI code; no lifespan/inference."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.main import create_app

OUTPUT = ROOT / "scripts/ci/api-contract.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    schema = create_app().openapi()
    # Exclude version/documentation prose; retain all machine contract constraints.
    snapshot = {"paths": schema["paths"], "schemas": schema["components"]["schemas"]}
    text = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.write:
        OUTPUT.write_text(text, encoding="utf-8")
    elif json.loads(OUTPUT.read_text(encoding="utf-8")) != snapshot:
        raise SystemExit("OpenAPI snapshot differs from FastAPI; review the contract before regeneration")
    print("Actual FastAPI OpenAPI contract verified; no models loaded or inference performed.")


if __name__ == "__main__":
    main()
