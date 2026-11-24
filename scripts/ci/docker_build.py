"""Build-only Compose derived from production build definitions, no runtime mounts."""
import argparse
import json
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "scripts/ci/local/compose-build.yml"


def configuration(root=ROOT):
    production = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    pins = json.loads((root / "scripts/ci/images.json").read_text(encoding="utf-8"))
    if set(production["services"]) != {"backend", "frontend"}:
        raise ValueError("Review CI service coverage after changing production services")
    services = {}
    for name, context, dockerfile in (("backend", ".", "backend/Dockerfile"), ("frontend", "./frontend", "Dockerfile")):
        source = production["services"][name]
        if source["build"] != {"context": context, "dockerfile": dockerfile} or not source["read_only"]:
            raise ValueError("Production build/security configuration changed; explicit CI review required")
        args = {"PYTHON_IMAGE": pins["python"]} if name == "backend" else {"NODE_IMAGE": pins["node"], "NGINX_IMAGE": pins["nginx"]}
        services[name] = {"build": {"context": str((root / context).resolve()), "dockerfile": dockerfile, "args": args},
                          "image": f"resilientinspect-ci-{name}:local", "platform": "linux/amd64"}
    return {"name": "resilientinspect-ci-build", "services": services}


def call(*args):
    subprocess.run(list(args), cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=["backend", "frontend"])
    parser.add_argument("--config-only", action="store_true")
    args = parser.parse_args()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    config = configuration()
    OUTPUT.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    compose = ["docker", "compose", "--file", str(OUTPUT)]
    call(*compose, "config", "--quiet")
    if args.config_only:
        print("Build-only Compose validated; no runtime mounts, ports or model admission.")
        return
    if not args.service:
        parser.error("--service required unless --config-only")
    service = config["services"][args.service]
    build = service["build"]
    check = ["docker", "build", "--check", "--file", str(Path(build["context"]) / build["dockerfile"])]
    for key, value in build["args"].items():
        check += ["--build-arg", f"{key}={value}"]
    call(*check, build["context"])
    call(*compose, "build", args.service)
    if args.service == "backend":
        probe = ("from pathlib import Path; import torch,torchvision,onnxruntime as ort; "
                 "from backend.app.main import create_app; "
                 "assert torch.version.cuda is None; assert 'CPUExecutionProvider' in ort.get_available_providers(); "
                 "assert not Path('/app/artifacts').exists() and not Path('/app/data').exists(); "
                 "assert create_app().openapi()['paths']; print('CPU/ORT image import passed; scientific models not loaded')")
        call("docker", "run", "--rm", "--network", "none", "--entrypoint", "python", service["image"], "-c", probe)
    else:
        # Host entry permits nginx -t to resolve its upstream without running an API.
        call("docker", "run", "--rm", "--network", "none", "--add-host", "backend:127.0.0.1",
             "--entrypoint", "nginx", service["image"], "-t")
    print(f"Built and smoke-checked {args.service}; no image published or service restarted.")


if __name__ == "__main__":
    main()
