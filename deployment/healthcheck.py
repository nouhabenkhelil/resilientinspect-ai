"""Readiness means all fifteen validated models, never merely an open port."""

import json
import sys
from urllib.request import urlopen


def ready(body: dict) -> bool:
    return (body.get("status") == "ok" and body.get("device") == "cpu"
            and body.get("ready_models") == body.get("expected_models") == 15)


def main() -> int:
    try:
        with urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
            body = json.load(response)
        if ready(body):
            return 0
        print("Backend non prêt : quinze modèles CPU validés sont requis.", file=sys.stderr)
    except (OSError, ValueError) as error:
        print(f"Backend non prêt : {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
