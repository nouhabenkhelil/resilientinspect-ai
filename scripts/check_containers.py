"""Real Docker HTTP integration on SHA256-verified normal validation images."""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import struct
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid
import csv
import hashlib
from PIL import Image


PROJECT = Path(__file__).resolve().parents[1]


def multipart(model, category, content, filename="validation.png"):
    boundary = f"resilientinspect-{uuid.uuid4().hex}"
    sections = []
    for name, value in (("model", model), ("category", category)):
        sections.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    sections.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode() + content + b"\r\n")
    sections.append(f"--{boundary}--\r\n".encode())
    return b"".join(sections), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def call(url, body=None, headers=None):
    request = Request(url, data=body, headers=headers or {})
    try:
        response = urlopen(request, timeout=125 if body is not None else 10)
    except HTTPError as error:
        response = error
    except (URLError, OSError) as error:
        return {"status": None, "error": str(error)}
    with response:
        raw = response.read()
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            value = raw.decode("utf-8", errors="replace")
        return {"status": response.status, "content_type": response.headers.get("Content-Type"),
                "request_id_header": response.headers.get("X-Request-ID"), "body": value}


def check(base, direct, dataset, manifest):
    rows = list(csv.DictReader(manifest.open(encoding="utf-8")))
    reference = json.loads((PROJECT / "deployment/reports/portability/windows.json").read_text())
    POLICY = reference["policy"]
    images = {}
    for category in ("bottle", "hazelnut", "leather"):
        row = next(r for r in rows if r["category"] == category and r["split"] == "val" and r["source_split"] == "train" and r["label"] == "0")
        path = dataset / row["image_path"]
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError("Validation image SHA256 mismatch")
        with Image.open(path) as im:
            images[category] = (content, [im.height, im.width], row["image_path"])
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "frontend_url": base,
              "direct_api_url": direct, "validation_inputs": {k: v[2] for k, v in images.items()},
              "checks": {}, "predictions": [], "failures": []}
    checks, failures = report["checks"], report["failures"]
    for name, url in (("frontend", base + "/"), ("nginx_health", base + "/nginx-health"),
                      ("direct_health", direct + "/health"), ("proxy_health", base + "/api/health"),
                      ("direct_metadata", direct + "/model/metadata"),
                      ("proxy_metadata", base + "/api/model/metadata")):
        checks[name] = call(url)
    # Do not retain full HTML or images in the report.
    html = checks["frontend"].get("body", "")
    checks["frontend"]["body"] = "React HTML" if isinstance(html, str) and '<div id="root">' in html else html
    if checks["frontend"].get("status") != 200 or checks["frontend"]["body"] != "React HTML":
        failures.append("Frontend HTML unavailable")
    checks["static_assets"] = []
    if isinstance(html, str):
        for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html):
            result = call(base + asset)
            content = result.pop("body", "")
            result["path"] = asset
            if result.get("status") != 200:
                failures.append(f"Static asset unavailable: {asset}")
            if asset.endswith(".js") and isinstance(content, str):
                result["same_origin_api"] = '/api' in content and 'backend:8000' not in content
                if not result["same_origin_api"]:
                    failures.append("Browser bundle must use same-origin /api without Docker hostnames")
            checks["static_assets"].append(result)
    for name in ("direct_health", "proxy_health"):
        body = checks[name].get("body", {})
        if (checks[name].get("status") != 200 or not isinstance(body, dict)
                or body.get("status") != "ok" or body.get("ready_models") != 15):
            failures.append(f"{name}: 15 validated CPU models required")
    body = checks["direct_metadata"].get("body", {})
    models = body.get("models", []) if isinstance(body, dict) else []
    proxy_body = checks["proxy_metadata"].get("body", {})
    if not isinstance(proxy_body, dict) or proxy_body.get("models") != models:
        failures.append("Proxy metadata differs from direct API")
    if len(models) != 15:
        failures.append(f"Only {len(models)}/15 models available")
    # Even in degraded mode, record a real POST and its actual error; no fake result.
    candidates = models or [{"model": "B0", "category": "bottle"}]
    for model in candidates:
        previous = None
        for path in ("/predict", "/predict/visualize"):
            image_content, dimensions, _ = images[model["category"]]
            content, headers = multipart(model["model"], model["category"], image_content)
            result = call(base + "/api" + path, content, headers)
            value = result.get("body", {})
            result.update({"path": path, "model": model["model"], "category": model["category"]})
            if result.get("status") != 200 or not isinstance(value, dict):
                failures.append(f"{model['model']}/{model['category']}{path}: HTTP {result.get('status')}")
            else:
                try:
                    assert value["model"] == model["model"] and value["category"] == model["category"]
                    assert value["threshold"] == model["threshold"] and value["version"] == model["version"]
                    assert value["decision"] == ("anomaly" if value["anomaly_score"] > value["threshold"] else "normal")
                    assert value["request_id"] == result["request_id_header"]
                    if previous is not None:
                        assert previous == value["anomaly_score"]
                    previous = value["anomaly_score"]
                    baseline = reference["models"][f"{model['model']}/{model['category']}"]
                    archived = next(r for r in baseline["scores"] if r["image_path"] == images[model["category"]][2])
                    assert value["threshold"] == baseline["threshold"]
                    assert abs(value["anomaly_score"] - archived["score"]) <= POLICY["atol"] + POLICY["rtol"] * abs(archived["score"])
                    if value["decision"] != archived["decision"]:
                        assert max(abs(value["anomaly_score"] - value["threshold"]), abs(archived["score"] - value["threshold"])) <= POLICY["atol"]
                    if path.endswith("/visualize"):
                        visual = value.pop("visualization")
                        assert visual["kind"] == model["explanation"] and visual["is_segmentation"] is False
                        assert visual["original_height_width"] == dimensions
                        assert visual["coordinate_space"] == "letterbox_256"
                        for key in ("image_png_base64", "heatmap_png_base64", "overlay_png_base64"):
                            image = base64.b64decode(visual.pop(key), validate=True)
                            if model["category"] == "bottle" and model["model"] in ("B0", "T2"):
                                destination = PROJECT / "deployment/reports/visualizations" / f"{model['model']}-{key.removesuffix('_png_base64')}.png"
                                destination.parent.mkdir(parents=True, exist_ok=True)
                                destination.write_bytes(image)
                            assert image.startswith(b"\x89PNG\r\n\x1a\n") and struct.unpack(">II", image[16:24]) == (256, 256)
                        value["visualization_metadata"] = visual
                except (AssertionError, KeyError, ValueError) as error:
                    failures.append(f"Response contract mismatch: {model['model']}/{model['category']}{path} {error}")
            report["predictions"].append(result)
    content, headers = multipart("B0", "bottle", b"invalid", "invalid.gif")
    checks["invalid_file"] = call(base + "/api/predict", content, headers)
    if checks["invalid_file"].get("status") != 415:
        failures.append("Invalid extension must return HTTP 415 through Nginx")
    report["passed"] = not failures
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", default="http://localhost:18080")
    parser.add_argument("--api", default="http://localhost:8001")
    parser.add_argument("--output", type=Path, default=PROJECT / "deployment/reports/container-integration.json")
    parser.add_argument("--dataset", type=Path, default=PROJECT / "data/raw/mvtec_ad")
    parser.add_argument("--manifest", type=Path, default=PROJECT / "data/manifests/manifest.csv")
    args = parser.parse_args()
    report = check(args.frontend.rstrip("/"), args.api.rstrip("/"), args.dataset, args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Integration {'PASSED' if report['passed'] else 'FAILED'}: {args.output}")
    for failure in report["failures"]:
        print(f"- {failure}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
