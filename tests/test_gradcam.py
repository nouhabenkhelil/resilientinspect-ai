"""Grad-CAM T0/T1/T2 sur tenseurs et backbone aleatoire synthetiques uniquement."""

import pytest
import torch
from torch import nn
from torchvision.models import efficientnet_b0

from resilientinspect.evaluation.gradcam import gradcam
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
    monkeypatch.setattr(tr, "_load_imagenet_state", lambda path, allow: (synthetic_backbone, {"source": "synthetic_test_fixture"}))


@pytest.mark.parametrize("variant", tr.VARIANTS)
def test_gradcam_frozen_or_trainable_preserves_weights_modes_and_gradients(variant, synthetic_weights):
    model = tr.build_transfer_model(variant).train()
    images = torch.rand(2, 3, 64, 64)
    image_before = images.clone()
    modes = {name: module.training for name, module in model.named_modules()}
    state = {name: value.clone() for name, value in model.state_dict().items()}
    model.classifier[1].weight.grad = torch.full_like(model.classifier[1].weight, 0.25)
    gradients = {name: None if p.grad is None else p.grad.clone() for name, p in model.named_parameters()}
    target = model.get_submodule(tr.GRADCAM_TARGET)
    assert isinstance(target, nn.Conv2d) and target.out_channels == 1280
    hooks = len(target._forward_hooks)
    cam = gradcam(model, images)
    assert cam.shape == (2, 1, 64, 64) and not cam.requires_grad
    assert torch.isfinite(cam).all() and cam.min() >= 0 and cam.max() <= 1
    assert torch.equal(image_before, images) and images.grad is None
    assert len(target._forward_hooks) == hooks
    assert modes == {name: module.training for name, module in model.named_modules()}
    assert all(torch.equal(value, model.state_dict()[name]) for name, value in state.items())
    for name, p in model.named_parameters():
        assert p.grad is None if gradients[name] is None else torch.equal(p.grad, gradients[name])
    assert torch.equal(cam, gradcam(model, images))


def test_final_conv_documented_8x8_target_at_256():
    model = tr.build_transfer_model("T0").eval()
    shapes = []
    handle = model.get_submodule(tr.GRADCAM_TARGET).register_forward_hook(lambda module, inputs, output: shapes.append(tuple(output.shape)))
    try:
        cam = gradcam(model, torch.rand(1, 3, 256, 256))
    finally:
        handle.remove()
    assert shapes == [(1, 1280, 8, 8)] and cam.shape == (1, 1, 256, 256)


def test_zero_score_has_finite_zero_cam_for_both_classes():
    model = tr.build_transfer_model("T0").eval().requires_grad_(False)
    with torch.no_grad():
        model.classifier[1].weight.zero_()
        model.classifier[1].bias.zero_()
    images = torch.rand(1, 3, 64, 64)
    for target_class in (0, 1):
        cam = gradcam(model, images, target_class=target_class)
        assert torch.equal(cam, torch.zeros_like(cam))


def test_hook_cleanup_and_modes_restored_after_forward_exception(monkeypatch):
    model = tr.build_transfer_model("T0").train()
    target = model.get_submodule(tr.GRADCAM_TARGET)
    hooks = len(target._forward_hooks)
    def broken(images):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(model, "forward", broken)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        gradcam(model, torch.rand(1, 3, 64, 64))
    assert model.training and len(target._forward_hooks) == hooks


@pytest.mark.parametrize("target_class", [2, -1, True])
def test_invalid_target_class_is_rejected(target_class):
    with pytest.raises(ValueError):
        gradcam(tr.build_transfer_model("T0"), torch.zeros(1, 3, 64, 64), target_class=target_class)
