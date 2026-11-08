"""Contrats A1, SSIM et non-fuite sur donnees synthetiques temporaires uniquement."""

from copy import deepcopy
import json
import os
from pathlib import Path
import random

from mlflow import MlflowClient
import numpy as np
from PIL import Image
import pytest
import torch
import yaml

from resilientinspect.data.augment import TrainAugmentedDataset, validate_augmentation
from resilientinspect.data.dataset import MVTecDataset
from resilientinspect.data.prepare import prepare_dataset, write_manifests
from resilientinspect.models.autoencoder import ConvAutoencoder
from resilientinspect.models.autoencoder_improved import ControlledSkip, ImprovedAutoencoder, ResidualBlock
from resilientinspect.training.a1_config import load_a1_checkpoint, validate_a1_config
from resilientinspect.training.losses import ReconstructionLoss
from resilientinspect.training import train_ae
from test_prepare import make_dataset, snapshot

PROJECT = Path(__file__).resolve().parents[1]
ARCH = PROJECT / "configs/ae_improved.yaml"
TRAIN = PROJECT / "configs/train_ae_a1.yaml"


@pytest.fixture(scope="module", autouse=True)
def restore_process_state():
    threads = torch.get_num_threads()
    deterministic = torch.are_deterministic_algorithms_enabled()
    benchmark, cudnn = torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic
    precision = torch.get_float32_matmul_precision()
    python_state, numpy_state = random.getstate(), np.random.get_state()
    environment = {k: os.environ.get(k) for k in ("MPLCONFIGDIR", "CUBLAS_WORKSPACE_CONFIG")}
    with torch.random.fork_rng(devices=[]):
        torch.set_num_threads(2)
        yield
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(deterministic)
    torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic = benchmark, cudnn
    torch.set_float32_matmul_precision(precision)
    random.setstate(python_state)
    np.random.set_state(numpy_state)
    for name, value in environment.items():
        if value is None: os.environ.pop(name, None)
        else: os.environ[name] = value


def architecture():
    return yaml.safe_load(ARCH.read_text(encoding="utf-8"))


def batch(n=2, size=256, dtype=torch.float32):
    return torch.rand(n, 3, size, size, generator=torch.Generator().manual_seed(42), dtype=dtype)


@pytest.mark.parametrize("training", [True, False])
@pytest.mark.parametrize("n", [1, 2])
def test_a1_forward_has_same_rgb_shape_range_and_no_input_mutation(training, n):
    model = ImprovedAutoencoder().train(training)
    images = batch(n)
    before = images.clone()
    with torch.no_grad(): result = model(images)
    assert result.shape == images.shape and result.dtype == torch.float32
    assert torch.isfinite(result).all() and result.min() >= 0 and result.max() <= 1
    assert torch.equal(images, before)


def test_backward_reaches_every_encoder_decoder_residual_and_skip_parameter():
    model = ImprovedAutoencoder()
    images = batch().requires_grad_()
    loss = ReconstructionLoss()(model(images), images)
    loss.backward()
    assert loss.ndim == 0 and torch.isfinite(loss)
    for name, parameter in model.named_parameters():
        assert parameter.grad is not None and torch.isfinite(parameter.grad).all(), name
    assert all(parameter.grad.abs().sum() > 0 for name, parameter in model.named_parameters() if "project.weight" in name)
    assert model.encoder[0][0].weight.grad.abs().sum() > 0
    assert model.output[1].weight.grad.abs().sum() > 0
    assert images.grad is not None and torch.isfinite(images.grad).all()


@pytest.mark.parametrize("residuals", [True, False])
@pytest.mark.parametrize("skips", [True, False])
def test_architecture_ablations_are_independent(residuals, skips):
    model = ImprovedAutoencoder(residual_blocks=residuals, skip_connections=skips)
    assert any(isinstance(m, ResidualBlock) for m in model.modules()) is residuals
    assert bool(model.skips) is skips
    with torch.no_grad(): assert model(batch(1)).shape == (1, 3, 256, 256)


def test_only_two_low_resolution_skip_branches_are_bounded():
    model = ImprovedAutoencoder()
    shapes = []
    handles = [module.register_forward_hook(lambda module, inputs, output: shapes.append(tuple(output.shape[-2:])))
               for module in model.skips.values()]
    with torch.no_grad(): model(batch(1))
    for handle in handles: handle.remove()
    assert shapes == [(32, 32), (64, 64)]
    skip = ControlledSkip(4, 0.1)
    with torch.no_grad(): skip.project.weight.fill_(100)
    assert skip(torch.ones(2, 4, 4, 4)).abs().max() <= 0.1000001
    assert len(model.skips) == 2


@pytest.mark.parametrize("kwargs", [{"channels": [16, 32]}, {"skip_scale": 1}, {"skip_scale": float("nan")},
                                    {"residual_blocks": 1}, {"skip_connections": "yes"}])
def test_invalid_architecture_options_are_rejected(kwargs):
    with pytest.raises(ValueError): ImprovedAutoencoder(**kwargs)


def test_pinned_architecture_and_same_training_budget_as_b0():
    arch = architecture()
    a1 = train_ae.load_config(TRAIN)
    b0 = train_ae.load_config(PROJECT / "configs/train_ae_b0.yaml")
    validate_a1_config(arch, a1["training"]["loss"])
    assert sum(p.numel() for p in ImprovedAutoencoder().parameters()) == 2_754_371
    assert sum(p.numel() for p in ConvAutoencoder().parameters()) == 195_107
    assert a1["seed"] == b0["seed"] == 42
    assert a1["dataset_config"] == b0["dataset_config"]
    assert {k:v for k,v in a1["training"].items() if k != "loss"} == {k:v for k,v in b0["training"].items() if k != "loss"}
    assert a1["smoke"] == b0["smoke"]


def numpy_ssim_reference(x, y):
    # Oracle independant : fenetres 2D NumPy, pas convolution PyTorch separable.
    position = np.arange(11, dtype=np.float64) - 5
    weights = np.exp(-(position[:, None] ** 2 + position[None, :] ** 2) / (2 * 1.5**2))
    weights /= weights.sum()
    def local_mean(array):
        windows = np.lib.stride_tricks.sliding_window_view(array, (11, 11), axis=(-2, -1))
        return np.einsum("...ij,ij->...", windows, weights)
    mx, my = local_mean(x), local_mean(y)
    vx, vy = np.maximum(local_mean(x*x) - mx*mx, 0), np.maximum(local_mean(y*y) - my*my, 0)
    covariance = local_mean(x*y) - mx*my
    similarity = ((2*mx*my + 0.01**2) * (2*covariance + 0.03**2)
                  / ((mx*mx + my*my + 0.01**2) * (vx+vy+0.03**2)))
    return np.clip(similarity, -1, 1).mean()


def test_ssim_matches_independent_numpy_reference_and_analytical_constants():
    x = batch(1, 16, torch.float64)
    y = 0.8 * x.flip(-1) + 0.1
    terms = ReconstructionLoss().components(x, y)
    expected = numpy_ssim_reference(x.numpy(), y.numpy())
    assert terms["ssim_loss"].item() == pytest.approx((1 - expected) / 2, abs=1e-12)
    assert terms["loss"].item() == pytest.approx(0.8 * (x-y).abs().mean().item() + 0.2 * (1-expected)/2, abs=1e-12)
    black, white = torch.zeros_like(x), torch.ones_like(x)
    assert ReconstructionLoss().components(black, white)["ssim_loss"].item() == pytest.approx((1-0.0001/1.0001)/2)


@pytest.mark.parametrize("kind", ["black", "white", "random", "near_constant"])
def test_ssim_identity_and_gradients_remain_finite_float32(kind):
    x = batch(1, 16)
    if kind == "black": x.zero_()
    elif kind == "white": x.fill_(1)
    elif kind == "near_constant": x = x * 1e-5 + 0.5
    x.requires_grad_()
    criterion = ReconstructionLoss()
    terms = criterion.components(x, x.detach())
    assert terms["ssim_loss"].item() == pytest.approx(0, abs=2e-5)
    terms["loss"].backward()
    assert torch.isfinite(x.grad).all()


def test_ssim_combined_loss_passes_double_precision_gradcheck():
    x = (batch(1, 12, torch.float64) * 0.8 + 0.1).requires_grad_()
    target = x.detach().flip(-1) * 0.9 + 0.02
    assert torch.autograd.gradcheck(ReconstructionLoss(), (x, target), fast_mode=True, atol=1e-5, rtol=1e-3)


def test_l1_ablation_matches_existing_pytorch_objective_exactly():
    x, y = batch(1, 16), batch(1, 16).flip(-1)
    criterion = ReconstructionLoss(name="l1", l1_weight=1, ssim_weight=0)
    assert torch.equal(criterion(x, y), torch.nn.functional.l1_loss(x, y))
    assert set(criterion.components(x, y)) == {"loss", "l1_loss"}


@pytest.mark.parametrize("kwargs", [{"l1_weight": 0.8, "ssim_weight": 0.5}, {"sigma": 0},
                                    {"window_size": 10}, {"ssim_weight": float("nan")}])
def test_invalid_loss_settings_are_rejected(kwargs):
    with pytest.raises(ValueError): ReconstructionLoss(**kwargs)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_loss_rejects_nonfinite_or_out_of_range_images(value):
    x = batch(1, 16)
    x[0, 0, 0, 0] = value
    with pytest.raises(ValueError): ReconstructionLoss()(x, batch(1, 16))


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("improved_a1")
    root = make_dataset(tmp / "raw")
    rows, report = prepare_dataset(root)
    manifest_dir = tmp / "manifests"
    write_manifests(rows, report, manifest_dir)
    config = train_ae.load_config(TRAIN)
    config.update(model_config=str(ARCH), dataset_config=str(PROJECT / "configs/dataset.yaml"))
    path = tmp / "training.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return tmp, root, manifest_dir / "manifest.csv", path


def test_augmentation_is_stateless_reproducible_and_preserves_geometry(synthetic):
    _, root, manifest, _ = synthetic
    base = MVTecDataset(manifest, root, split="train", categories=["bottle"])
    augmented = TrainAugmentedDataset(base, {**architecture()["augmentation"], "probability": 1}, 42)
    before = snapshot(root)
    state = torch.get_rng_state()
    first = augmented[0]
    torch.rand(17)  # Un autre modele ne doit pas modifier les tirages d'augmentation.
    second = augmented[0]
    original = base[0]
    assert torch.equal(first["image"], second["image"])
    assert not torch.equal(original["image"], first["image"])
    for key in ("mask", "valid_mask", "original_size", "padding"):
        assert torch.equal(first[key], original[key])
    assert first["image"].min() >= 0 and first["image"].max() <= 1
    assert not first["image"][:, first["valid_mask"][0] == 0].any()
    augmented.set_epoch(1)
    assert not torch.equal(augmented[0]["image"], first["image"])
    assert snapshot(root) == before
    torch.set_rng_state(state)


@pytest.mark.parametrize("split", ["val", "test"])
def test_augmentation_refuses_every_non_train_split(synthetic, split):
    _, root, manifest, _ = synthetic
    dataset = MVTecDataset(manifest, root, split=split, categories=["bottle"])
    with pytest.raises(ValueError, match="train/good"):
        TrainAugmentedDataset(dataset, architecture()["augmentation"], 42)


def test_loaders_wrap_only_train_and_validation_is_unmodified(synthetic):
    _, root, manifest, _ = synthetic
    settings = train_ae.load_config(TRAIN)["training"]
    loaders = train_ae.build_loaders(manifest, root, "bottle", settings, 42, torch.device("cpu"), architecture()["augmentation"])
    assert isinstance(loaders["train"].dataset, TrainAugmentedDataset)
    assert type(loaders["val"].dataset) is MVTecDataset
    plain = MVTecDataset(manifest, root, split="val", categories=["bottle"])
    assert torch.equal(plain[0]["image"], loaders["val"].dataset[0]["image"])
    assert not {r["sha256"] for r in loaders["train"].dataset.rows} & {r["sha256"] for r in loaders["val"].dataset.rows}


@pytest.mark.parametrize("key,value", [("brightness", 0.5), ("enabled", 1), ("probability", float("nan"))])
def test_augmentation_configuration_is_strict(key, value):
    config = architecture()["augmentation"]
    config[key] = value
    with pytest.raises(ValueError): validate_augmentation(config)


@pytest.fixture(scope="module")
def runs(synthetic):
    tmp, root, manifest, config = synthetic
    before = snapshot(root), snapshot(manifest.parent)
    original_open = Image.open
    opened = []
    def guarded_open(path, *args, **kwargs):
        relative = Path(path).relative_to(root).as_posix()
        assert relative.startswith("bottle/train/good/")
        assert "/test/" not in relative and "/ground_truth/" not in relative
        opened.append(relative)
        return original_open(path, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Image, "open", guarded_open)
        one = train_ae.run_training(config, root=root, manifest=manifest, output_dir=tmp / "output", device="cpu", smoke=True)
        two = train_ae.run_training(config, root=root, manifest=manifest, output_dir=tmp / "output", device="cpu", smoke=True)
    assert before == (snapshot(root), snapshot(manifest.parent))
    assert len(opened) == 12
    return one, two


def test_two_a1_smokes_reproduce_history_and_checkpoint_weights(runs):
    one, two = runs
    assert one["variant"] == two["variant"] == "A1" and one["scope"] == "smoke"
    assert one["history"] == two["history"] and one["run_id"] != two["run_id"]
    row = one["history"][0]
    assert row["train_batches"] == 2 and row["val_batches"] == 1
    assert row["train_images"] == 4 and row["val_images"] == 2
    for split in ("train", "val"):
        assert row[f"{split}_loss"] == pytest.approx(0.8*row[f"{split}_l1_loss"] + 0.2*row[f"{split}_ssim_loss"])
    a = torch.load(Path(one["run_dir"]) / "best.pt", weights_only=True, map_location="cpu")
    b = torch.load(Path(two["run_dir"]) / "best.pt", weights_only=True, map_location="cpu")
    assert all(torch.equal(value, b["model_state_dict"][key]) for key, value in a["model_state_dict"].items())
    assert one["test_used"] is False and one["selection_split"] == "val"


def test_checkpoint_roundtrip_uses_saved_architecture_even_if_config_changes(runs, tmp_path):
    path = Path(runs[0]["run_dir"]) / "best.pt"
    model = load_a1_checkpoint(path)
    saved = torch.load(path, weights_only=True, map_location="cpu")
    direct = ImprovedAutoencoder(**saved["architecture"]["model"]["kwargs"])
    direct.load_state_dict(saved["model_state_dict"], strict=True)
    direct.eval()
    with torch.inference_mode(): assert torch.equal(model(batch(1)), direct(batch(1)))
    assert not model.training and all(not p.requires_grad for p in model.parameters())
    assert saved["architecture"] == architecture()
    corrupted = deepcopy(saved)
    corrupted["model_state_dict"]["skips.0.scale"].fill_(0.9)
    bad = tmp_path / "bad.pt"
    torch.save(corrupted, bad)
    with pytest.raises(ValueError, match="Echelle"): load_a1_checkpoint(bad)


def test_mlflow_provenance_and_loss_components_are_recorded(runs):
    result = runs[0]
    client = MlflowClient(tracking_uri=result["tracking_uri"])
    run = client.get_run(result["run_id"])
    assert run.info.status == "FINISHED" and run.data.tags["variant"] == "A1"
    assert run.data.params["loss.ssim_weight"] == "0.2" and run.data.params["architecture.skip_scale"] == "0.1"
    assert run.data.params["augmentation.enabled"] == "True"
    assert "val_l1_loss" in run.data.metrics and "train_ssim_loss" in run.data.metrics
    source_names = {Path(path).name for path in result["source_sha256"]}
    assert {"autoencoder_improved.py", "losses.py", "augment.py", "a1_config.py"} <= source_names


def test_a1_validation_keeps_weights_bn_buffers_and_gradients_unchanged(synthetic):
    _, root, manifest, _ = synthetic
    settings = train_ae.load_config(TRAIN)["training"]
    loaders = train_ae.build_loaders(manifest, root, "bottle", settings, 42, torch.device("cpu"), architecture()["augmentation"])
    model = ImprovedAutoencoder()
    before = {name: value.clone() for name, value in model.state_dict().items()}
    result = train_ae.run_epoch(model, loaders["val"], torch.device("cpu"), criterion=ReconstructionLoss())
    assert result["images"] == 2 and not model.training
    assert all(torch.equal(value, model.state_dict()[name]) for name, value in before.items())
    assert all(p.grad is None for p in model.parameters())


def test_test_split_is_rejected_before_any_a1_forward_or_loss():
    from torch.utils.data import DataLoader
    loader = DataLoader([{"image": batch(1)[0], "split": "test", "image_path": "forbidden"}])
    class Forbidden(torch.nn.Module):
        def forward(self, image): raise AssertionError("test forward")
    with pytest.raises(ValueError, match="Split interdit"):
        train_ae.run_epoch(Forbidden(), loader, torch.device("cpu"), criterion=ReconstructionLoss())


def test_a1_full_cpu_run_is_refused_before_any_image_read(synthetic, monkeypatch):
    tmp, root, manifest, config = synthetic
    def forbidden(*args, **kwargs): raise AssertionError("Images ouvertes avant garde CPU")
    monkeypatch.setattr(Image, "open", forbidden)
    with pytest.raises(ValueError, match="--smoke"):
        train_ae.run_training(config, root=root, manifest=manifest, output_dir=tmp / "refused", device="cpu")
    assert not (tmp / "refused").exists()


@pytest.mark.parametrize("protected", ["artifacts/b0_runs", "reports/evaluation/b0"])
def test_a1_outputs_cannot_enter_frozen_b0_directories(synthetic, protected):
    _, root, manifest, config = synthetic
    with pytest.raises(ValueError, match="B0 figes"):
        train_ae.run_training(config, root=root, manifest=manifest, output_dir=PROJECT / protected, device="cpu", smoke=True)


@pytest.mark.parametrize("category", ["bottle", "hazelnut", "leather"])
def test_cli_passes_a1_category_and_defaults_to_separate_output(monkeypatch, tmp_path, capsys, category):
    def record_call(config, **kwargs):
        assert config == TRAIN and kwargs["category"] == category
        assert kwargs["output_dir"] == Path("artifacts/a1_runs") and kwargs["smoke"] is True
        return {"run_id": "synthetic", "run_dir": str(tmp_path), "category": category,
                "scope": "smoke", "best_epoch": 1, "best_val_loss": 0.0}
    monkeypatch.setattr(train_ae, "run_training", record_call)
    assert train_ae.main(["--config", str(TRAIN), "--category", category, "--device", "cpu", "--smoke"]) == 0
    capsys.readouterr()


@pytest.mark.skipif(not torch.cuda.is_available(), reason="A1 CUDA/SSIM backward a verifier reellement sur Kaggle/T4.")
def test_cuda_forward_and_mixed_loss_backward():
    train_ae.seed_everything(42, 2)
    model = ImprovedAutoencoder().cuda()
    images = batch().cuda()
    loss = ReconstructionLoss().cuda()(model(images), images)
    loss.backward()
    assert torch.isfinite(loss)
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())
