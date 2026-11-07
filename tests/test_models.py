"""Contrats B0 sur tenseurs synthetiques ; aucune lecture du dataset officiel."""

from io import BytesIO
from pathlib import Path

import pytest
import torch
from torch import nn
import yaml

from resilientinspect.models.autoencoder import ConvAutoencoder


CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs/ae_baseline.yaml"


@pytest.fixture(scope="module")
def config():
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module", autouse=True)
def limited_cpu_threads():
    """Limiter le cout CPU des tests, puis restaurer le reglage de l'appelant."""
    previous = torch.get_num_threads()
    torch.set_num_threads(min(2, previous))
    yield
    torch.set_num_threads(previous)


@pytest.fixture
def model(config):
    # L'initialisation du test ne change pas l'etat aleatoire des autres tests.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(42)
        return ConvAutoencoder(**config["model"]["kwargs"])


def synthetic_batch(batch_size=2, *, device="cpu"):
    generator = torch.Generator(device=device).manual_seed(42)
    return torch.rand(batch_size, 3, 256, 256, generator=generator, device=device)


def assert_reconstruction(reconstruction, images):
    assert reconstruction.shape == images.shape
    assert reconstruction.dtype == images.dtype
    assert reconstruction.device == images.device
    assert torch.isfinite(reconstruction).all()
    assert torch.all((reconstruction >= 0) & (reconstruction <= 1))


@pytest.mark.parametrize("batch_size", [1, 2])
@pytest.mark.parametrize("training", [False, True], ids=["eval", "train"])
def test_rgb_reconstruction_shape_range_and_finiteness(model, batch_size, training):
    model.train(training)
    images = synthetic_batch(batch_size)
    before = images.clone()
    with torch.no_grad():
        reconstruction = model(images)
    assert_reconstruction(reconstruction, images)
    assert torch.equal(images, before)


def check_backward(model, images, config):
    model.train()
    images.requires_grad_(True)
    reconstruction = model(images)
    assert_reconstruction(reconstruction, images)
    criterion = nn.L1Loss(**config["loss"]["kwargs"])
    loss = criterion(reconstruction, images)
    assert loss.ndim == 0 and torch.isfinite(loss) and loss > 0
    loss.backward()
    for name, parameter in model.named_parameters():
        assert parameter.grad is not None, name
        assert torch.isfinite(parameter.grad).all(), name
    assert model.encoder[0][0].weight.grad.abs().sum() > 0
    assert model.decoder[-1][1].weight.grad.abs().sum() > 0
    assert images.grad is not None and torch.isfinite(images.grad).all()


def test_l1_backward_reaches_encoder_and_decoder_without_nan_or_inf(model, config):
    check_backward(model, synthetic_batch(), config)


@pytest.mark.parametrize("value", [0.0, 1.0], ids=["black", "white"])
@pytest.mark.parametrize("training", [False, True], ids=["eval", "train"])
def test_constant_images_remain_finite_with_batch_norm(model, value, training):
    model.train(training)
    images = torch.full((2, 3, 256, 256), value)
    with torch.no_grad():
        assert_reconstruction(model(images), images)


def test_yaml_builds_the_documented_b0_and_initial_l1_choice(model, config):
    assert config["model"]["name"] == "B0"
    assert config["model"]["class"] == "resilientinspect.models.autoencoder.ConvAutoencoder"
    assert config["model"]["input_shape"] == [3, 256, 256]
    assert config["model"]["skip_connections"] is False
    assert config["loss"]["name"] == "l1" and config["loss"]["class"] == "torch.nn.L1Loss"
    assert config["loss"]["kwargs"] == {"reduction": "mean"}
    # Contrat latent et decoder verifie sur le graphe reel, pas uniquement dans le YAML.
    with torch.no_grad():
        latent = model.encoder(synthetic_batch(1))
        assert list(latent.shape[1:]) == config["model"]["bottleneck_shape"]
        assert_reconstruction(model.decoder(latent), synthetic_batch(1))
    assert sum(parameter.numel() for parameter in model.parameters()) == 195_107


def test_state_dict_roundtrip_preserves_batch_norm_buffers_and_eval_output(model, config):
    images = synthetic_batch()
    with torch.no_grad():
        model.train()
        model(images)  # Met a jour les buffers BN avec des tenseurs synthetiques uniquement.
        model.eval()
        expected = model(images)
    stream = BytesIO()
    torch.save(model.state_dict(), stream)
    stream.seek(0)
    restored = ConvAutoencoder(**config["model"]["kwargs"])
    restored.load_state_dict(torch.load(stream, map_location="cpu", weights_only=True))
    restored.eval()
    with torch.no_grad():
        assert torch.equal(restored(images), expected)
    assert all(torch.equal(value, restored.state_dict()[key]) for key, value in model.state_dict().items())


def test_three_encoder_blocks_also_preserve_the_fixed_rgb_contract():
    model = ConvAutoencoder(channels=(8, 16, 32)).eval()
    images = synthetic_batch(1)
    with torch.no_grad():
        assert_reconstruction(model(images), images)


@pytest.mark.parametrize("shape", [(3, 256, 256), (1, 1, 256, 256), (1, 3, 255, 256), (0, 3, 256, 256)])
def test_invalid_input_shapes_fail_explicitly(model, shape):
    with pytest.raises(ValueError, match="Entree attendue"):
        model(torch.zeros(shape))


@pytest.mark.parametrize("channels", [(), (16, 32), (8, 16, 32, 64, 128), (16, 0, 64), (16, False, 64), (16, 32.0, 64)])
def test_invalid_channels_are_not_silently_coerced(channels):
    with pytest.raises(ValueError, match="3 ou 4 entiers"):
        ConvAutoencoder(channels=channels)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA indisponible : execution a verifier sur Kaggle/T4.")
def test_cuda_synthetic_forward_and_backward(model, config):
    check_backward(model.to("cuda"), synthetic_batch(device="cuda"), config)
