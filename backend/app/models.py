"""Chargement des seuls runs full et de leurs calibrations figees."""

from dataclasses import asdict, dataclass, field
import json
import logging
from pathlib import Path
from threading import Lock

import torch

from resilientinspect.data.audit import _sha256
from resilientinspect.evaluation import a1_checkpoints, evaluate_ae, evaluate_a1, evaluate_transfer
from resilientinspect.models import transfer
from resilientinspect.training.train_ae import seed_everything

from .config import Settings
from .schemas import CATEGORIES, MODELS, ModelMetadata


logger = logging.getLogger(__name__)
CPU = torch.device("cpu")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class LoadedModel:
    network: torch.nn.Module
    metadata: ModelMetadata
    lock: Lock = field(default_factory=Lock)


class ModelStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.models: dict[tuple[str, str], LoadedModel] = {}
        self.unavailable: dict[tuple[str, str], str] = {}

    def load(self) -> None:
        """Execute une seule fois au demarrage. Aucune lecture d'image MVTec."""
        seed_everything(42, 2)
        try:
            digest = evaluate_ae.manifest_digest(self.settings.manifest)
        except (OSError, ValueError, KeyError, TypeError):
            logger.exception("Manifeste indisponible ou invalide")
            self.unavailable = {(model, category): "Manifeste absent ou invalide."
                                for model in MODELS for category in CATEGORIES}
            return
        for variant in ("B0", "A1"):
            module = evaluate_ae if variant == "B0" else a1_checkpoints
            try:
                selected, _ = module.discover_checkpoints(self.settings.project_root / f"artifacts/{variant.lower()}_runs")
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                logger.exception("Selection des checkpoints %s impossible", variant)
                self.unavailable.update({(variant, category): "Checkpoint full absent, ambigu ou invalide."
                                         for category in CATEGORIES})
                continue
            for category in CATEGORIES:
                self._load_one(variant, category, lambda cp=selected[category], v=variant: self._load_ae(v, cp, digest))
        for variant in ("T0", "T1", "T2"):
            for category in CATEGORIES:
                self._load_one(variant, category, lambda v=variant, c=category: self._load_transfer(v, c))

    def _load_one(self, variant: str, category: str, loader) -> None:
        try:
            self.models[variant, category] = loader()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError):
            logger.exception("Chargement refuse pour %s/%s", variant, category)
            self.unavailable[variant, category] = "Checkpoint, calibration ou validation CPU absent ou invalide."

    def _load_ae(self, variant: str, checkpoint: evaluate_ae.Checkpoint, digest: str) -> LoadedModel:
        root = self.settings.project_root
        protocol_path = root / "configs/evaluate_ae_b0.yaml"
        module = evaluate_ae if variant == "B0" else evaluate_a1
        protocol = module.load_protocol(protocol_path)
        directory = root / f"reports/evaluation/{variant.lower()}" / _sha256(protocol_path)[:12] / checkpoint.category
        expected = module.binding(protocol_path, checkpoint, digest)
        if variant == "A1":
            calibration = evaluate_a1._load_calibration(directory, checkpoint, protocol, expected, CPU)
            network = a1_checkpoints.load_model(checkpoint, CPU, digest)
        else:
            path = directory / "calibration.json"
            if path.with_suffix(".sha256").read_text(encoding="ascii").strip() != _sha256(path):
                raise ValueError("Empreinte calibration B0 invalide.")
            calibration = read_json(path)
            if (any(calibration.get(key) != value for key, value in expected.items())
                    or calibration.get("checkpoint") != asdict(checkpoint)
                    or calibration.get("category") != checkpoint.category
                    or calibration.get("calibration_split") != "val" or calibration.get("normal_only") is not True
                    or calibration.get("environment") != evaluate_ae._environment(CPU)):
                raise ValueError("Calibration B0 incompatible.")
            network = evaluate_ae.load_model(checkpoint, CPU, digest)
        threshold, _ = evaluate_ae._thresholds(calibration)
        environment_path = Path(checkpoint.path).with_name("environment.json")
        metadata = ModelMetadata(model=variant, category=checkpoint.category, version=checkpoint.sha256,
                                 checkpoint_sha256=checkpoint.sha256, calibration_sha256=_sha256(directory / "calibration.json"),
                                 threshold=threshold, normalization="RGB [0,1]",
                                 score="rgb_mean_absolute_error_top_1_percent_valid_pixels",
                                 explanation="reconstruction_error", serving_environment=evaluate_transfer._environment(),
                                 training_environment=read_json(environment_path) if environment_path.exists() else None)
        return LoadedModel(network, metadata)

    def _load_transfer(self, variant: str, category: str) -> LoadedModel:
        root = self.settings.project_root
        runs = list((root / f"artifacts/transfer_runs/{variant}/{category}/seed42").glob("full_*"))
        if len(runs) != 1 or not runs[0].is_dir():
            raise ValueError("Un unique run full seed42 requis.")
        run = runs[0]
        inspected = evaluate_transfer.inspect_run(run, self.settings.manifest)
        if (inspected["variant"], inspected["category"], inspected["seed"]) != (variant, category, 42):
            raise ValueError("Identite du run incompatible.")
        protocol_path = root / "configs/evaluate_transfer.yaml"
        evaluate_transfer.load_protocol(protocol_path)
        protocol_sha = _sha256(protocol_path)
        base = root / "reports/transfer/portability"
        report_path = (base / variant / category / "seed42" / inspected["checkpoint_sha256"][:12]
                       / protocol_sha[:12] / "compatibility.json")
        report_sha = _sha256(report_path)
        summary = read_json(base / "validation_summary.json")
        if report_sha not in {row["sha256"] for row in summary["runs"]}:
            raise ValueError("Empreinte du rapport de compatibilite invalide.")
        report = read_json(report_path)
        bound = ("variant", "category", "seed", "checkpoint_sha256", "manifest_sha256", "calibration_sha256",
                 "synthetic_plan_sha256", "effective_config_sha256", "source_sha256", "image_threshold", "training_environment")
        if (any(report.get(key) != inspected[key] for key in bound)
                or report.get("status") != "passed" or report.get("compatibility_validated") is not True
                or report.get("test_executed") is not False or report.get("split") != "val_synthetic"
                or report.get("parity_policy") != evaluate_transfer.PARITY_POLICY
                or report.get("protocol_sha256") != protocol_sha
                or report.get("evaluation_code_sha256") != _sha256(Path(evaluate_transfer.__file__))
                or report.get("evaluation_environment") != evaluate_transfer._environment()
                or report.get("score_tolerance_failures") != 0 or report.get("unjustified_decision_changes") != 0):
            raise ValueError("Validation CPU perimee ou incompatible.")
        network = transfer.load_transfer_checkpoint(run / "best.pt", CPU)
        metadata = ModelMetadata(model=variant, category=category, version=inspected["checkpoint_sha256"],
                                 checkpoint_sha256=inspected["checkpoint_sha256"],
                                 calibration_sha256=inspected["calibration_sha256"], threshold=inspected["image_threshold"],
                                 seed=42, normalization="ImageNet mean=[0.485,0.456,0.406] std=[0.229,0.224,0.225]",
                                 score="sigmoid_anomaly_logit", explanation="gradcam",
                                 training_environment=inspected["training_environment"],
                                 serving_environment=evaluate_transfer._environment(), compatibility_report_sha256=report_sha)
        return LoadedModel(network, metadata)
