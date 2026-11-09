"""Contrats EfficientNet sur tenseurs/poids aleatoires synthetiques, sans reseau."""

from copy import deepcopy
from pathlib import Path

import pytest
import torch
from torch import nn
from torchvision.models import efficientnet_b0

from resilientinspect.models import transfer as tr


@pytest.fixture(scope="module", autouse=True)
def process_state():
    threads = torch.get_num_threads()
    with torch.random.fork_rng(devices=[]):
        torch.set_num_threads(2)
        yield
    torch.set_num_threads(threads)


@pytest.fixture(scope="module")
def synthetic_backbone():
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(123)
        return efficientnet_b0(weights=None).state_dict()


@pytest.fixture
def synthetic_weights(monkeypatch, synthetic_backbone):
    """Seam privee explicite : ces poids ne sont jamais appeles ImageNet reels."""
    def synthetic_loader(path, allow_download):
        return synthetic_backbone, {"source": "synthetic_test_fixture", "seed": 123}
    monkeypatch.setattr(tr, "_load_imagenet_state", synthetic_loader)


@pytest.mark.parametrize("variant", tr.VARIANTS)
def test_common_head_logits_shape_and_parameter_groups(variant, synthetic_weights):
    model = tr.build_transfer_model(variant).eval()
    assert isinstance(model.classifier[0], nn.Dropout) and model.classifier[0].p == 0.2
    assert isinstance(model.classifier[1], nn.Linear)
    assert (model.classifier[1].in_features, model.classifier[1].out_features) == (1280, 1)
    with torch.no_grad():
        logits = model(torch.rand(2, 3, 256, 256))
    assert logits.shape == (2,) and torch.isfinite(logits).all()
    groups = tr.parameter_groups(model)
    report = tr.trainable_parameter_report(model)
    grouped = [p for group in groups for p in group["params"]]
    expected = [p for p in model.parameters() if p.requires_grad]
    assert {id(p) for p in grouped} == {id(p) for p in expected}
    assert len(grouped) == len({id(p) for p in grouped})
    assert report["head_parameters"] == 1281
    assert report["trainable_parameters"] + report["frozen_parameters"] == report["total_parameters"]
    assert groups[0]["name"] == "head" and groups[0]["lr"] == 1e-3
    if variant == "T1":
        assert report["trainable_parameters"] == 1281 and len(groups) == 1
        assert len(tr.parameter_groups(model, backbone_lr=0.0)) == 1
    else:
        assert groups[1]["name"] == "backbone"
        assert groups[1]["lr"] == (1e-4 if variant == "T2" else 1e-3)
        with pytest.raises(ValueError):
            tr.parameter_groups(model, backbone_lr=0.0)
    assert report["unfrozen_feature_stages"] == (list(range(9)) if variant == "T0" else [6, 7, 8] if variant == "T2" else [])


def test_same_head_same_seed_and_same_pretrained_initial_features(synthetic_weights):
    models = [tr.build_transfer_model(variant, seed=42) for variant in tr.VARIANTS]
    for model in models[1:]:
        assert all(torch.equal(value, model.classifier.state_dict()[name]) for name, value in models[0].classifier.state_dict().items())
    assert all(torch.equal(value, models[2].features.state_dict()[name]) for name, value in models[1].features.state_dict().items())
    assert any(not torch.equal(value, models[1].features.state_dict()[name]) for name, value in models[0].features.state_dict().items())
    changed_seed = tr.build_transfer_model("T0", seed=43)
    assert not torch.equal(models[0].classifier[1].weight, changed_seed.classifier[1].weight)


@pytest.mark.parametrize("variant", tr.VARIANTS)
def test_train_only_updates_selected_stages_and_frozen_bn_buffers(variant, synthetic_weights):
    model = tr.build_transfer_model(variant).train()
    report = tr.trainable_parameter_report(model)
    unfrozen = report["unfrozen_feature_stages"]
    before = {name: value.clone() for name, value in model.state_dict().items()}
    optimizer = torch.optim.Adam(tr.parameter_groups(model))
    logits = model(torch.rand(2, 3, 64, 64))
    nn.functional.binary_cross_entropy_with_logits(logits, torch.tensor([0.0, 1.0])).backward()
    optimizer.step()
    assert not torch.equal(before["classifier.1.weight"], model.classifier[1].weight)
    for index, stage in enumerate(model.features):
        assert all(p.requires_grad == (index in unfrozen) for p in stage.parameters())
        if index not in unfrozen:
            assert all(not module.training for module in stage.modules())
            assert all(torch.equal(before[f"features.{index}.{name}"], value) for name, value in stage.state_dict().items())
            assert all(p.grad is None for p in stage.parameters())
    model.eval().train()
    assert all(not stage.training for index, stage in enumerate(model.features) if index not in unfrozen)


def test_t0_never_opens_weights_or_downloads_and_rng_is_preserved(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Aucun poids externe pour T0")
    monkeypatch.setattr(tr, "_load_imagenet_state", forbidden)
    monkeypatch.setattr(torch.hub, "download_url_to_file", forbidden)
    before = torch.random.get_rng_state()
    model = tr.build_transfer_model("T0")
    assert torch.equal(before, torch.random.get_rng_state())
    assert model.weight_provenance == {"source": "random", "seed": 42}
    for kwargs in ({"allow_download": True}, {"imagenet_weights": Path("unused.pth")}):
        with pytest.raises(ValueError):
            tr.build_transfer_model("T0", **kwargs)


@pytest.mark.parametrize("variant", ["T1", "T2"])
def test_pretrained_rejects_missing_or_incorrect_imagenet_without_network(tmp_path, monkeypatch, variant):
    monkeypatch.setattr(tr, "WEIGHT_CACHE", tmp_path / "empty_cache")
    def forbidden(*args, **kwargs):
        raise AssertionError("Telechargement implicite interdit")
    monkeypatch.setattr(torch.hub, "download_url_to_file", forbidden)
    with pytest.raises(ValueError, match="Poids ImageNet absents"):
        tr.build_transfer_model(variant)
    wrong = tmp_path / "wrong.pth"
    wrong.write_bytes(b"not imagenet")
    with pytest.raises(ValueError, match="Empreinte"):
        tr.build_transfer_model(variant, imagenet_weights=wrong)


@pytest.mark.parametrize("variant,seed", [("unknown", 42), ("T0", -1), ("T0", True)])
def test_invalid_variant_or_seed_is_rejected(variant, seed):
    with pytest.raises(ValueError):
        tr.build_transfer_model(variant, seed=seed)


@pytest.mark.parametrize("lr", [0, -1, float("nan"), True])
def test_invalid_learning_rate_is_rejected(lr):
    with pytest.raises(ValueError):
        tr.parameter_groups(tr.build_transfer_model("T0"), head_lr=lr)


def checkpoint_payload(model):
    return {"variant": "T0", "category": "bottle", "seed": 42, "scope": "smoke", "epoch": 1,
            "val_loss": 0.7, "model_state_dict": model.state_dict(),
            "effective_config": {"variant": "T0", "category": "bottle", "seed": 42},
            "weight_provenance": model.weight_provenance, "manifest_sha256": "a" * 64,
            "synthetic_plan_sha256": "b" * 64}


def test_checkpoint_roundtrip_without_fetch_or_rng_change(tmp_path, monkeypatch):
    model = tr.build_transfer_model("T0").eval()
    path = tmp_path / "best.pt"
    torch.save(checkpoint_payload(model), path)
    def forbidden(*args, **kwargs):
        raise AssertionError("Rechargement sans ImageNet")
    monkeypatch.setattr(tr, "_load_imagenet_state", forbidden)
    before = torch.random.get_rng_state()
    restored = tr.load_transfer_checkpoint(path)
    assert torch.equal(before, torch.random.get_rng_state())
    assert not restored.training and all(not p.requires_grad for p in restored.parameters())
    assert all(torch.equal(value, restored.state_dict()[name]) for name, value in model.state_dict().items())


@pytest.mark.parametrize("mutation", ["variant", "provenance", "sha", "shape", "nan", "config"])
def test_checkpoint_inconsistency_is_rejected(tmp_path, mutation):
    payload = deepcopy(checkpoint_payload(tr.build_transfer_model("T0")))
    if mutation == "variant": payload["variant"] = "B0"
    elif mutation == "provenance": payload["weight_provenance"]["source"] = "imagenet"
    elif mutation == "sha": payload["manifest_sha256"] = "wrong"
    elif mutation == "config": payload["effective_config"]["category"] = "hazelnut"
    elif mutation == "shape": payload["model_state_dict"]["classifier.1.weight"] = torch.zeros(1, 2)
    else: payload["model_state_dict"]["classifier.1.weight"].fill_(float("nan"))
    path = tmp_path / "bad.pt"
    torch.save(payload, path)
    with pytest.raises((ValueError, RuntimeError)):
        tr.load_transfer_checkpoint(path)
