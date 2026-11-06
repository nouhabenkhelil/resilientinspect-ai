"""Geometrie image/masque et chargement PyTorch, sans entrainement."""

from pathlib import Path

from PIL import Image
import pytest
import torch
from torch.utils.data import DataLoader, Dataset

from resilientinspect.data.dataset import MVTecDataset, letterbox_pair
from test_prepare import prepared, snapshot


def test_train_samples_are_tensors_with_zero_masks_and_fixed_pixel_scaling(prepared):
    root, _, _, output = prepared
    dataset = MVTecDataset(output / "manifest.csv", root, split="train")
    assert isinstance(dataset, Dataset)
    sample = dataset[0]
    assert sample["image"].shape == (3, 256, 256)
    assert sample["mask"].shape == sample["valid_mask"].shape == (1, 256, 256)
    assert sample["image"].dtype == torch.float32
    assert sample["image"].is_contiguous()
    assert 0 <= sample["image"].min() <= sample["image"].max() <= 1
    assert torch.count_nonzero(sample["mask"]) == 0
    assert sample["label"] == 0 and not sample["has_mask"] and sample["mask_path"] == ""
    with Image.open(root / sample["image_path"]) as original:
        expected = torch.tensor(original.getpixel((0, 0)), dtype=torch.float32) / 255
    assert torch.equal(sample["image"][:, 128, 128], expected)


def test_letterbox_preserves_ratio_and_mask_alignment(prepared):
    root, _, _, output = prepared
    dataset = MVTecDataset(output / "manifest.csv", root, split="test", categories=["bottle"])
    sample = next(dataset[index] for index in range(len(dataset)) if dataset.rows[index]["label"] == "1")
    assert sample["original_size"].tolist() == [8, 16]
    assert sample["resized_size"].tolist() == [128, 256]
    assert sample["padding"].tolist() == [64, 64, 0, 0]
    expected = torch.zeros((1, 256, 256))
    expected[:, 96:160, 64:192] = 1
    assert torch.equal(sample["mask"], expected)
    assert set(sample["mask"].unique().tolist()) == {0.0, 1.0}
    assert torch.count_nonzero(sample["image"][:, :64]) == 0
    assert torch.count_nonzero(sample["mask"][:, :64]) == 0
    assert sample["valid_mask"].sum().item() == 128 * 256
    assert sample["image"][:, 128, 128].tolist() == [1, 1, 1]
    assert sample["image"][:, 80, 20].tolist() == [0, 0, 0]
    assert 0 < ((sample["image"] > 0) & (sample["image"] < 1)).sum().item()  # RGB bilineaire.
    assert sample["label"] == 1 and sample["has_mask"]


def test_dataloader_batches_and_repeated_access_are_reproducible(prepared):
    root, _, _, output = prepared
    dataset = MVTecDataset(output / "manifest.csv", root, split="val")
    before = snapshot(root)
    first, second = dataset[0], dataset[0]
    for key in ("image", "mask", "valid_mask", "padding"):
        assert torch.equal(first[key], second[key])
    batch = next(iter(DataLoader(dataset, batch_size=2, shuffle=False, num_workers=0)))
    assert batch["image"].shape == (2, 3, 256, 256)
    assert batch["mask"].shape == (2, 1, 256, 256)
    assert set(batch["split"]) == {"val"}
    assert snapshot(root) == before


def test_training_loader_never_opens_test_images_or_masks(prepared, monkeypatch):
    root, _, _, output = prepared
    original_open = Image.open
    opened = []
    def tracked_open(path, *args, **kwargs):
        relative = Path(path).relative_to(root).as_posix()
        assert "/test/" not in relative and "/ground_truth/" not in relative
        opened.append(relative)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Image, "open", tracked_open)
    for split in ("train", "val"):
        dataset = MVTecDataset(output / "manifest.csv", root, split=split)
        dataset[0]
    assert len(opened) == 2


@pytest.mark.parametrize("split", ["all", "validation", "", None])
def test_invalid_split_cannot_silently_mix_official_test(prepared, split):
    root, _, _, output = prepared
    with pytest.raises(ValueError): MVTecDataset(output / "manifest.csv", root, split=split)


def test_split_must_be_explicit_and_unknown_category_is_an_error(prepared):
    root, _, _, output = prepared
    with pytest.raises(TypeError): MVTecDataset(output / "manifest.csv", root)
    with pytest.raises(ValueError):
        MVTecDataset(output / "manifest.csv", root, split="train", categories=["unknown"])


@pytest.mark.parametrize("kind", ["image", "mask"])
def test_modification_since_manifest_is_detected(prepared, kind):
    root, rows, _, output = prepared
    row = next(row for row in rows if row["category"] == "bottle" and row["label"] == "1")
    field = "image_path" if kind == "image" else "mask_path"
    (root / row[field]).write_bytes(b"changed")
    dataset = MVTecDataset(output / "manifest.csv", root, split="test", categories=["bottle"])
    index = next(i for i, candidate in enumerate(dataset.rows) if candidate["label"] == "1")
    with pytest.raises(ValueError, match="modifi"):
        dataset[index]


def test_size_mismatch_and_nonbinary_masks_are_not_hidden():
    image = Image.new("RGB", (16, 8))
    with pytest.raises(ValueError, match="Dimensions"):
        letterbox_pair(image, Image.new("L", (8, 8)))
    with pytest.raises(ValueError, match="non binaire"):
        letterbox_pair(image, Image.new("L", image.size, 127))


def test_odd_padding_is_deterministic_and_nearest_preserves_binary_values():
    image, mask = Image.new("RGB", (16, 8), 255), Image.new("L", (16, 8), 255)
    sample = letterbox_pair(image, mask, (7, 7))
    assert sample["resized_size"].tolist() == [4, 7]
    assert sample["padding"].tolist() == [1, 2, 0, 0]
    assert sample["mask"].sum().item() == 28
    assert set(sample["mask"].unique().tolist()) == {0.0, 1.0}
