"""Self-contained MLflow model from code; normalized FP32 NCHW input, batch one."""
import hashlib
import importlib.util
import json
from pathlib import Path

import mlflow
import numpy as np
import torch
from mlflow.pyfunc import PythonModel


class FrozenTransferModel(PythonModel):
    def load_context(self, context):
        artifacts = context.artifacts
        binding = json.loads(Path(artifacts["binding"]).read_text())
        for name, expected in binding["sha256"].items():
            with Path(artifacts[name]).open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError(f"Registry artifact SHA256 mismatch: {name}")
        spec = importlib.util.spec_from_file_location("ri_frozen_transfer", artifacts["architecture"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        torch.set_num_threads(2)
        torch.use_deterministic_algorithms(True)
        torch.set_float32_matmul_precision("highest")
        self.network = module.load_transfer_checkpoint(Path(artifacts["checkpoint"]), "cpu")
        calibration = json.loads(Path(artifacts["calibration"]).read_text())
        if calibration["checkpoint_sha256"] != binding["sha256"]["checkpoint"]:
            raise ValueError("Calibration/checkpoint binding mismatch")
        self.threshold = calibration["image_threshold"]

    def predict(self, context, model_input, params=None):
        array = np.asarray(model_input)
        if array.dtype != np.float32 or array.shape != (1, 3, 256, 256) or not np.isfinite(array).all():
            raise ValueError("Expected finite ImageNet-normalized float32 [1,3,256,256]")
        with torch.inference_mode():
            score = torch.sigmoid(self.network(torch.from_numpy(array.copy()))).numpy()
        return np.column_stack((score, (score > self.threshold).astype(np.float32)))


mlflow.models.set_model(FrozenTransferModel())
