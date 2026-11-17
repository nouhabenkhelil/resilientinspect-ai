"""API CPU sur images et modeles synthetiques temporaires, sans entrainement."""

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from io import BytesIO
import json
from pathlib import Path
import shutil
from uuid import UUID

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest
import torch

from backend.app.config import PROJECT, Settings
from backend.app.main import create_app
from backend.app.models import LoadedModel, ModelStore
from backend.app.schemas import CATEGORIES, MODELS, ModelMetadata
from resilientinspect.data.dataset import letterbox_pair
from resilientinspect.data.synthetic import normalize_image
from resilientinspect.evaluation import evaluate_ae, evaluate_transfer
from resilientinspect.models.autoencoder import ConvAutoencoder
from resilientinspect.models.autoencoder_improved import ImprovedAutoencoder
from resilientinspect.models.transfer import TransferClassifier
from test_evaluation import write_run as write_b0
from test_a1_checkpoints import write_run as write_a1
from test_transfer_evaluation import process_state, synthetic_run


def image_bytes(format="PNG", mode="RGB", size=(91, 43)):
    image = Image.new(mode, size, (31, 116, 207) if mode == "RGB" else 80)
    buffer = BytesIO()
    image.save(buffer, format=format)
    return buffer.getvalue()


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    service = ModelStore(Settings(project_root=tmp_path_factory.mktemp("api_models")))
    for variant in MODELS:
        for index, category in enumerate(CATEGORIES):
            if variant == "B0":
                network = ConvAutoencoder()
            elif variant == "A1":
                network = ImprovedAutoencoder(channels=(4, 8, 16, 32))
            else:
                network = TransferClassifier(variant, seed=42 + index)
            network.eval().requires_grad_(False)
            metadata = ModelMetadata(model=variant, category=category, version=f"synthetic-{variant}-{category}",
                                     checkpoint_sha256="a" * 64, calibration_sha256="b" * 64, threshold=0.2,
                                     normalization="synthetic fixture", score="synthetic fixture",
                                     explanation="reconstruction_error" if variant in ("B0", "A1") else "gradcam",
                                     serving_environment={"device": "cpu"})
            service.models[variant, category] = LoadedModel(network, metadata)
    return service


@pytest.fixture
def client(store):
    with TestClient(create_app(store=store)) as client:
        yield client


def post(client, *, model="B0", category="bottle", path="/predict", content=None, filename="image.png"):
    return client.post(path, data={"model": model, "category": category},
                       files={"file": (filename, image_bytes() if content is None else content, "application/octet-stream")})


def test_health_metadata_and_swagger(client):
    response = client.get("/health")
    assert response.status_code == 200 and response.json()["ready_models"] == 15
    assert response.json()["device"] == "cpu"
    metadata = client.get("/model/metadata").json()
    assert len(metadata["models"]) == 15 and not metadata["unavailable"]
    selected = client.get("/model/metadata?model=T1&category=leather").json()["models"]
    assert len(selected) == 1 and selected[0]["version"] == "synthetic-T1-leather"
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert set(schema["paths"]) == {"/health", "/model/metadata", "/predict", "/predict/visualize"}
    assert "multipart/form-data" in schema["paths"]["/predict"]["post"]["requestBody"]["content"]


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("category", CATEGORIES)
def test_all_models_categories_and_exact_preprocessing(client, store, model, category):
    loaded = store.models[model, category]
    observed = []
    handle = loaded.network.register_forward_pre_hook(lambda network, args: observed.append(args[0].clone()))
    try:
        response = post(client, model=model, category=category)
    finally:
        handle.remove()
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["category"] == category and result["model"] == model
    assert result["version"] == loaded.metadata.version and result["threshold"] == 0.2
    assert result["decision"] == ("anomaly" if result["anomaly_score"] > 0.2 else "normal")
    assert result["inference_time_ms"] >= 0 and 0 <= result["anomaly_score"] <= 1
    assert str(UUID(result["request_id"])) == response.headers["x-request-id"]
    sample = letterbox_pair(Image.open(BytesIO(image_bytes())), Image.new("L", (91, 43), 0))
    expected = sample["image"].unsqueeze(0)
    if model.startswith("T"):
        expected = normalize_image(expected)
    assert len(observed) == 1 and torch.equal(observed[0], expected)
    with torch.inference_mode():
        output = loaded.network(expected)
    if model.startswith("T"):
        score = float(output.sigmoid()[0])
    else:
        error = evaluate_ae.anomaly_maps(expected, output)[0].numpy()
        score = evaluate_ae.image_score(error, sample["valid_mask"][0].numpy())
    assert result["anomaly_score"] == score


@pytest.mark.parametrize("model", MODELS)
def test_visualizations_are_aligned_and_preserve_model_state(client, store, model):
    loaded = store.models[model, "bottle"]
    before = {key: value.clone() for key, value in loaded.network.state_dict().items()}
    response = post(client, model=model, path="/predict/visualize")
    assert response.status_code == 200, response.text
    result = response.json()
    visual = result["visualization"]
    assert visual["kind"] == ("gradcam" if model.startswith("T") else "reconstruction_error")
    assert visual["is_segmentation"] is False
    assert visual["coordinate_space"] == "letterbox_256"
    assert visual["original_height_width"] == [43, 91]
    top, bottom, left, right = visual["padding_top_bottom_left_right"]
    arrays = {}
    for key in ("image_png_base64", "heatmap_png_base64", "overlay_png_base64"):
        image = Image.open(BytesIO(base64.b64decode(visual[key])))
        assert image.size == (256, 256) and image.mode == "RGB"
        arrays[key] = np.asarray(image)
        assert np.all(arrays[key][:top] == 0) and np.all(arrays[key][256 - bottom:] == 0)
    assert left == right == 0
    assert all(torch.equal(value, before[key]) for key, value in loaded.network.state_dict().items())
    assert all(not module.training for module in loaded.network.modules())
    assert all(not module._forward_hooks for module in loaded.network.modules())
    assert post(client, model=model).json()["anomaly_score"] == result["anomaly_score"]


def test_ae_visualization_uses_unmodified_error_scale(client, store):
    response = post(client, path="/predict/visualize").json()
    visual = response["visualization"]
    assert visual["scale"] == "absolute_l1_0_1"
    sample = letterbox_pair(Image.open(BytesIO(image_bytes())), Image.new("L", (91, 43), 0))
    images = sample["image"].unsqueeze(0)
    with torch.inference_mode():
        error = evaluate_ae.anomaly_maps(images, store.models["B0", "bottle"].network(images))[0].numpy()
    heat = np.asarray(Image.open(BytesIO(base64.b64decode(visual["heatmap_png_base64"]))))
    valid = sample["valid_mask"][0].numpy().astype(bool)
    np.testing.assert_array_equal(heat[..., 0][valid], np.rint(error[valid] * 255).astype(np.uint8))


@pytest.mark.parametrize("content,filename,status,code", [
    (b"", "image.png", 400, "invalid_image"),
    (b"broken", "image.png", 400, "invalid_image"),
    (image_bytes()[:42], "image.png", 400, "invalid_image"),
    (image_bytes(), "image.exe", 415, "unsupported_extension"),
    (image_bytes(), "image.jpg", 415, "format_mismatch"),
    (image_bytes("GIF"), "image.png", 400, "invalid_image"),
])
def test_bad_images_return_clean_errors(client, content, filename, status, code):
    response = post(client, content=content, filename=filename)
    assert response.status_code == status and response.json()["code"] == code
    assert response.json()["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize("format,mode,filename", [("JPEG", "RGB", "photo.JPG"), ("PNG", "L", "gray.png"),
                                                  ("PNG", "RGBA", "alpha.png")])
def test_valid_image_modes_are_converted_to_rgb(client, format, mode, filename):
    assert post(client, content=image_bytes(format, mode), filename=filename).status_code == 200


@pytest.mark.parametrize("model,category", [("T9", "bottle"), ("B0", "metal"), ("../B0", "bottle")])
def test_unknown_model_or_category_is_rejected(client, model, category):
    response = post(client, model=model, category=category)
    assert response.status_code == 422 and response.json()["code"] == "invalid_input"


def test_missing_upload_and_malformed_multipart_are_clean(client):
    assert client.post("/predict", data={"model": "B0", "category": "bottle"}).status_code == 422
    response = client.post("/predict", content=b"broken", headers={"content-type": "multipart/form-data"})
    assert response.status_code == 400 and response.json()["code"] == "http_error"


def test_file_pixel_and_streamed_request_limits(store):
    small = Settings(max_file_bytes=100, max_image_pixels=10)
    with TestClient(create_app(settings=small, store=store)) as client:
        assert post(client, content=b"a" * 101).json()["code"] == "file_too_large"
        assert post(client, content=image_bytes(size=(4, 4))).json()["code"] == "image_too_large"
        response = client.post("/predict", content=iter([b"a" * 40000, b"b" * 40000]),
                               headers={"content-type": "multipart/form-data; boundary=test"})
        assert response.status_code == 413 and response.json()["code"] == "request_too_large"
        assert response.json()["request_id"] == response.headers["x-request-id"]


def test_absent_model_and_inference_failure_have_distinct_errors(client, store, monkeypatch):
    with monkeypatch.context() as changes:
        changes.delitem(store.models, ("B0", "bottle"))
        assert post(client).json()["code"] == "model_unavailable"
        assert client.get("/health").status_code == 503
    def fail(*args, **kwargs):
        raise RuntimeError("sensitive local path")
    monkeypatch.setattr(store.models["B0", "bottle"].network, "forward", fail)
    response = post(client)
    assert response.status_code == 500 and response.json()["code"] == "inference_failed"
    assert "sensitive" not in response.text


def test_strict_threshold_equality_is_normal(client, store, monkeypatch):
    score = post(client).json()["anomaly_score"]
    monkeypatch.setattr(store.models["B0", "bottle"].metadata, "threshold", score)
    result = post(client).json()
    assert result["decision"] == "normal" and result["threshold"] == score


def test_concurrent_gradcam_and_predictions_are_consistent(client):
    expected = post(client, model="T1").json()["anomaly_score"]
    paths = ["/predict/visualize", "/predict", "/predict/visualize", "/predict"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda path: post(client, model="T1", path=path), paths))
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["anomaly_score"] == expected for response in responses)
    assert len({response.json()["request_id"] for response in responses}) == 4


@pytest.fixture(scope="module")
def artifacts(synthetic_run, tmp_path_factory):
    root = tmp_path_factory.mktemp("api_artifacts")
    shutil.copytree(PROJECT / "configs", root / "configs")
    shutil.copytree(synthetic_run[2].parent, root / "data/manifests")
    manifest = root / "data/manifests/manifest.csv"
    digest = evaluate_ae.manifest_digest(manifest)
    protocol_path = root / "configs/evaluate_ae_b0.yaml"
    protocol = evaluate_ae.load_protocol(protocol_path)
    from resilientinspect.evaluation import evaluate_a1
    for variant, writer, module in (("B0", write_b0, evaluate_ae), ("A1", write_a1, evaluate_a1)):
        for category in CATEGORIES:
            writer(root / f"artifacts/{variant.lower()}_runs", category, digest)
        selected, _ = module.discover_checkpoints(root / f"artifacts/{variant.lower()}_runs")
        for category, checkpoint in selected.items():
            calibration = {**module.binding(protocol_path, checkpoint, digest), "category": category,
                           "checkpoint": asdict(checkpoint), "calibration_split": "val", "normal_only": True,
                           "environment": evaluate_ae._environment(torch.device("cpu")), "protocol": protocol,
                           "image_threshold": 0.2, "pixel_threshold": 0.1,
                           "validation_images": 1, "validation_pixels": 100, "validation_scores": [{"score": 0.2}]}
            directory = root / f"reports/evaluation/{variant.lower()}" / evaluate_ae._sha256(protocol_path)[:12] / category
            directory.mkdir(parents=True)
            (directory / "calibration.json").write_bytes(evaluate_ae._json_bytes(calibration))
            (directory / "calibration.sha256").write_text(evaluate_ae._sha256(directory / "calibration.json"), encoding="ascii")
    run = root / "artifacts/transfer_runs/T0/bottle/seed42/full_synthetic"
    shutil.copytree(synthetic_run[3], run)
    report = evaluate_transfer.validate_run(run, manifest=manifest, root=synthetic_run[1],
                                            protocol_path=root / "configs/evaluate_transfer.yaml")
    base = root / "reports/transfer/portability"
    path = base / "T0/bottle/seed42" / report["checkpoint_sha256"][:12] / report["protocol_sha256"][:12] / "compatibility.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(evaluate_ae._json_bytes(report))
    (base / "validation_summary.json").write_bytes(evaluate_ae._json_bytes({"runs": [{"sha256": evaluate_ae._sha256(path)}]}))
    return Settings(project_root=root), run, path


def test_real_loaders_accept_full_artifacts_without_opening_any_dataset_image(artifacts, monkeypatch):
    settings, _, _ = artifacts
    def forbidden(*args, **kwargs):
        raise AssertionError("Ouverture d'image ou recalibration pendant le chargement")
    monkeypatch.setattr(Image, "open", forbidden)
    monkeypatch.setattr(evaluate_ae, "calibrate_records", forbidden)
    service = ModelStore(settings)
    service.load()
    assert len(service.models) == 7  # B0/A1 trois categories et T0 bottle.
    assert ("T1", "bottle") in service.unavailable
    assert service.models["T0", "bottle"].metadata.compatibility_report_sha256
    assert service.models["A1", "leather"].metadata.threshold == 0.2


@pytest.mark.parametrize("mutation", ["checkpoint", "calibration", "report", "smoke", "duplicate"])
def test_transfer_loader_refuses_altered_or_unvalidated_artifacts(artifacts, tmp_path, mutation):
    settings, original_run, original_report = artifacts
    root = tmp_path / "project"
    shutil.copytree(settings.project_root, root)
    run = root / original_run.relative_to(settings.project_root)
    report = root / original_report.relative_to(settings.project_root)
    if mutation == "checkpoint":
        path = run / "best.pt"
        path.write_bytes(path.read_bytes() + b"changed")
    elif mutation == "calibration":
        path = run / "calibration.json"
        path.write_bytes(path.read_bytes() + b"\n")
    elif mutation == "report":
        report.write_bytes(report.read_bytes() + b"\n")
    elif mutation == "smoke":
        run.rename(run.with_name("smoke_only"))
    else:
        shutil.copytree(run, run.with_name("full_duplicate"))
    service = ModelStore(replace(settings, project_root=root))
    with pytest.raises((ValueError, OSError)):
        service._load_transfer("T0", "bottle")


def test_startup_missing_artifacts_remains_observable(tmp_path):
    with TestClient(create_app(Settings(project_root=tmp_path))) as client:
        assert client.get("/health").status_code == 503
        assert len(client.get("/model/metadata").json()["unavailable"]) == 15
        assert post(client).status_code == 503
