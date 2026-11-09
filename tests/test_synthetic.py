"""Synthese localisee sur sources temporaires, sans images ni masques officiels."""

from copy import deepcopy
import csv
import json
from pathlib import Path
import random

from PIL import Image
import pytest
import torch
from torch.utils.data import DataLoader
import yaml

from resilientinspect.data import synthetic as syn
from resilientinspect.data.prepare import MANIFEST_FIELDS, prepare_dataset, write_manifests
from test_prepare import make_dataset, snapshot


CONFIG = {"schema_version": 1, "image_size": [256, 256], "copies_per_source": 1,
          "patch_fraction": [0.1, 0.3], "min_effect": 0.15,
          "normalization": {"mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]}}


@pytest.fixture(scope="module", autouse=True)
def restore_rng_and_threads():
    threads, state = torch.get_num_threads(), random.getstate()
    with torch.random.fork_rng(devices=[]):
        torch.set_num_threads(2)
        yield
    torch.set_num_threads(threads)
    random.setstate(state)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    temporary = tmp_path_factory.mktemp("localized_synthetic")
    root = make_dataset(temporary / "raw")
    rows, report = prepare_dataset(root)
    write_manifests(rows, report, temporary / "manifests")
    return root, rows, temporary / "manifests/manifest.csv"


def dataset(prepared, split="train", category="bottle", **kwargs):
    return syn.SyntheticAnomalyDataset(prepared[2], prepared[0], category=category, split=split,
                                       config=deepcopy(CONFIG), **kwargs)


def test_plan_is_metadata_only_and_independent_of_model_rng(prepared, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Une preparation de recettes ne doit ouvrir aucune image")
    monkeypatch.setattr(Image, "open", forbidden)
    first = syn.prepare_synthetic_plan(prepared[2], CONFIG, 42)
    random.seed(100)
    torch.manual_seed(234)
    torch.rand(100)
    second = syn.prepare_synthetic_plan(prepared[2], CONFIG, 42)
    assert first == second
    assert first["generator"] == "localized_self_cutpaste_v1"
    assert first["config"]["normalization"] == CONFIG["normalization"]
    third = syn.prepare_synthetic_plan(prepared[2], CONFIG, 43)
    assert first["recipes"][1]["corruption_seed"] != third["recipes"][1]["corruption_seed"]
    assert first["recipes"][1]["image_path"] == third["recipes"][1]["image_path"]


def test_plan_pairs_are_balanced_and_source_paths_and_hashes_are_disjoint(prepared):
    plan = syn.prepare_synthetic_plan(prepared[2], CONFIG)
    assert len(plan["recipes"]) == 60
    for split in ("train", "val"):
        rows = [row for row in plan["recipes"] if row["split"] == split]
        assert sum(row["label"] == 0 for row in rows) == sum(row["label"] == 1 for row in rows)
        assert all("/train/good/" in row["image_path"] and row["source_split"] == "train" for row in rows)
        for normal, positive in zip(rows[::2], rows[1::2]):
            assert (normal["label"], positive["label"]) == (0, 1)
            assert normal["source_id"] == positive["source_id"]
            assert normal["sample_id"] != positive["sample_id"]
    for key in ("image_path", "source_sha256", "source_id"):
        train = {row[key] for row in plan["recipes"] if row["split"] == "train"}
        val = {row[key] for row in plan["recipes"] if row["split"] == "val"}
        assert not train & val
    assert len({row["sample_id"] for row in plan["recipes"]}) == len(plan["recipes"])


@pytest.mark.parametrize("category", ["bottle", "hazelnut", "leather"])
@pytest.mark.parametrize("split", ["train", "val"])
def test_shapes_labels_normalization_and_exact_localized_support(prepared, category, split):
    ds = dataset(prepared, split, category)
    normal, anomaly = ds[0], ds[1]
    for sample in (normal, anomaly):
        assert sample["image"].shape == sample["raw_image"].shape == (3, 256, 256)
        assert sample["image"].dtype == sample["raw_image"].dtype == torch.float32
        assert sample["synthetic_mask"].shape == sample["valid_mask"].shape == (1, 256, 256)
        assert sample["split"] == split and sample["category"] == category
        assert sample["mask_path"] == ""
        assert torch.isfinite(sample["image"]).all()
        assert sample["raw_image"].min() >= 0 and sample["raw_image"].max() <= 1
        assert torch.allclose(syn.denormalize_image(sample["image"]), sample["raw_image"], atol=1e-7)
    assert normal["label"] == 0 and anomaly["label"] == 1
    assert normal["synthetic_mask"].sum() == 0
    changed = (anomaly["raw_image"] != normal["raw_image"]).any(dim=0, keepdim=True)
    assert torch.equal(changed, anomaly["synthetic_mask"].bool())
    assert changed.any() and not (changed & ~anomaly["valid_mask"].bool()).any()
    assert changed.sum() <= 0.11 * anomaly["valid_mask"].sum()
    assert torch.equal(anomaly["raw_image"][:, :64], normal["raw_image"][:, :64])


def test_data_generation_never_opens_test_or_masks_and_preserves_sources(prepared, monkeypatch):
    root = prepared[0]
    before = snapshot(root), snapshot(prepared[2].parent)
    opened = []
    original = Image.open
    def guarded(path, *args, **kwargs):
        relative = Path(path).relative_to(root).as_posix()
        assert "/train/good/" in relative and "/test/" not in relative and "/ground_truth/" not in relative
        opened.append(relative)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Image, "open", guarded)
    for split in ("train", "val"):
        ds = dataset(prepared, split)
        for index in range(len(ds)):
            ds[index]
    assert len(opened) == 20
    assert before == (snapshot(root), snapshot(prepared[2].parent))


def test_samples_are_fixed_across_access_epochs_models_and_global_rng(prepared):
    plan = syn.prepare_synthetic_plan(prepared[2], CONFIG)
    first = dataset(prepared, plan=plan)
    reference = first[1]
    random.seed(300)
    torch.manual_seed(123)
    torch.randn(400)
    second = dataset(prepared, plan=deepcopy(plan))
    for current in (first[1], second[1]):
        for key in ("image", "raw_image", "synthetic_mask", "valid_mask"):
            assert torch.equal(reference[key], current[key])
        assert reference["sample_id"] == current["sample_id"]
    # A DataLoader consumes the same frozen examples; no epoch callback exists.
    batch = next(iter(DataLoader(first, batch_size=2, shuffle=False, num_workers=0)))
    assert batch["label"].tolist() == [0, 1]
    assert torch.equal(batch["image"][1], reference["image"])


@pytest.mark.parametrize("split", ["test", "all", "", None])
def test_forbidden_splits_fail_before_any_source_access(prepared, monkeypatch, split):
    def forbidden(*args, **kwargs):
        raise AssertionError("Acces source avant refus du split")
    monkeypatch.setattr(syn, "prepare_synthetic_plan", forbidden)
    with pytest.raises(ValueError, match="jamais test"):
        dataset(prepared, split)


@pytest.mark.parametrize("mutation", ["seed", "recipe", "config", "generator", "manifest", "label_type"])
def test_stale_or_tampered_plans_fail_before_image_access(prepared, monkeypatch, mutation):
    plan = syn.prepare_synthetic_plan(prepared[2], CONFIG)
    if mutation == "seed": plan["seed"] = 43
    elif mutation == "recipe": plan["recipes"][0]["image_path"] = "bottle/test/good/000.png"
    elif mutation == "config": plan["config"]["min_effect"] = 0.2
    elif mutation == "generator": plan["generator_code_sha256"] = "wrong"
    elif mutation == "manifest": plan["manifest_sha256"] = "wrong"
    else: plan["recipes"][1]["label"] = True
    def forbidden(*args, **kwargs):
        raise AssertionError("Image ouverte avec un plan incompatible")
    monkeypatch.setattr(Image, "open", forbidden)
    with pytest.raises(ValueError, match="Plan synthetique"):
        dataset(prepared, plan=plan)


@pytest.mark.parametrize("mutation", ["path", "content"])
def test_global_manifest_rejects_cross_split_source_leakage(prepared, tmp_path, monkeypatch, mutation):
    rows = deepcopy(prepared[1])
    train = next(row for row in rows if row["split"] == "train")
    val = next(row for row in rows if row["split"] == "val")
    if mutation == "path": val["image_path"] = train["image_path"]
    else: val["sha256"] = train["sha256"]
    path = tmp_path / "leaked.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    def forbidden(*args, **kwargs):
        raise AssertionError("Image ouverte malgre une fuite du manifeste")
    monkeypatch.setattr(Image, "open", forbidden)
    with pytest.raises(ValueError):
        syn.prepare_synthetic_plan(path, CONFIG)


def test_modified_source_content_is_refused_at_access(prepared, tmp_path):
    import shutil
    root = tmp_path / "raw"
    shutil.copytree(prepared[0], root)
    ds = syn.SyntheticAnomalyDataset(prepared[2], root, category="bottle", split="train", config=CONFIG)
    (root / ds.rows[0]["image_path"]).write_bytes(b"modified source")
    with pytest.raises(ValueError, match="modifiee"):
        ds[0]


def test_plan_serialization_is_immutable_and_config_is_copied(prepared, tmp_path):
    config = deepcopy(CONFIG)
    plan = syn.prepare_synthetic_plan(prepared[2], config)
    config["min_effect"] = 0.25
    assert plan["config"]["min_effect"] == 0.15
    path = tmp_path / "plan.json"
    syn.write_synthetic_plan(plan, path)
    original, mtime = path.read_bytes(), path.stat().st_mtime_ns
    assert json.loads(original) == plan
    syn.write_synthetic_plan(plan, path)
    assert path.stat().st_mtime_ns == mtime
    plan["seed"] = 43
    with pytest.raises(FileExistsError):
        syn.write_synthetic_plan(plan, path)
    assert path.read_bytes() == original


@pytest.mark.parametrize("key,value", [("image_size", [224, 224]), ("copies_per_source", 2),
    ("patch_fraction", [0, 0.3]), ("patch_fraction", [0.3, 0.1]), ("min_effect", 0),
    ("min_effect", float("nan")), ("normalization", {"mean": [0, 0, 0], "std": [1, 1, 1]})])
def test_config_rejects_unsupported_or_invalid_settings(tmp_path, key, value):
    config = deepcopy(CONFIG)
    config[key] = value
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(ValueError):
        syn.load_synthetic_config(path)


def test_config_loading_normalization_and_inverse_are_model_independent(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    assert syn.load_synthetic_config(path) == CONFIG
    image = torch.zeros(2, 3, 5, 8)
    image[:, 1] = 0.5
    image[:, 2] = 1
    normalized = syn.normalize_image(image)
    assert normalized[0, :, 0, 0].tolist() == pytest.approx([
        (0 - 0.485) / 0.229, (0.5 - 0.456) / 0.224, (1 - 0.406) / 0.225])
    assert torch.allclose(syn.denormalize_image(normalized), image, atol=1e-7)
    with pytest.raises(ValueError): syn.normalize_image(torch.zeros(1, 5, 8))
    with pytest.raises(ValueError): syn.normalize_image(torch.full((3, 5, 8), 1.1))


def test_metadata_only_cli_and_protected_outputs(prepared, tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    output = tmp_path / "plan.json"
    def forbidden(*args, **kwargs):
        raise AssertionError("La CLI des recettes ne doit ouvrir aucune image")
    monkeypatch.setattr(Image, "open", forbidden)
    arguments = ["--manifest", str(prepared[2]), "--root", str(prepared[0]), "--config", str(config_path)]
    assert syn.main([*arguments, "--output", str(output)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["recipes"] == 60 and summary["images_opened"] is False
    for target in (prepared[0] / "plan.json", prepared[2].parent / "plan.json",
                   syn.PROJECT / "artifacts/b0_runs/plan.json", syn.PROJECT / "reports/evaluation/a1/plan.json"):
        assert syn.main([*arguments, "--output", str(target)]) == 1
        assert not target.exists()
    capsys.readouterr()
