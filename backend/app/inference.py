"""Inference FP32 CPU avec les calculs scientifiques du projet."""

from time import perf_counter
from uuid import UUID

import numpy as np
import torch

from resilientinspect.data.synthetic import normalize_image
from resilientinspect.evaluation import evaluate_ae
from resilientinspect.evaluation.gradcam import gradcam
from resilientinspect.export.onnx_runtime import inputs as prepare_inputs, score_output, score_parity

from .imaging import render_visualization
from .models import LoadedModel
from .schemas import Prediction, VisualizedPrediction
from .errors import APIError


def predict(loaded: LoadedModel, sample: dict, request_id: UUID, *, visualize: bool = False, engine: str = "pytorch") -> Prediction:
    is_transfer = loaded.metadata.model in ("T0", "T1", "T2")
    images = sample["image"].unsqueeze(0)
    inputs = prepare_inputs(sample, loaded.metadata.model)
    # Grad-CAM installe un hook temporaire. Le verrou protege aussi les forwards ordinaires.
    with loaded.lock, torch.autocast(device_type="cpu", enabled=False):
        started = perf_counter()
        with torch.inference_mode():
            if engine == "onnxruntime":
                if loaded.onnx_path is None or loaded.onnx_cache is None:
                    raise APIError(503, "onnx_unavailable", "ONNX non admis ; aucun repli automatique.")
                output = loaded.onnx_cache.get(loaded.onnx_path).run(None, {"images": inputs.numpy()})[0]
            elif engine == "pytorch":
                output = loaded.network(inputs)
            else:
                raise APIError(422, "invalid_engine", "Moteur inconnu.")
            score, error = score_output(output, sample, loaded.metadata.model)
        values = None
        explanation_score, coherence, decision_changed, explanation_ms = None, None, None, None
        if visualize:
            explanation_started = perf_counter()
            if is_transfer and engine == "onnxruntime":
                with torch.inference_mode():
                    explanation_score, _ = score_output(loaded.network(inputs), sample, loaded.metadata.model)
                parity = score_parity(explanation_score, score, loaded.metadata.threshold)
                coherence = parity["score_passed"] and parity["decision_passed"]
                decision_changed = parity["decision_changed"]
                if not coherence:
                    raise APIError(409, "explanation_divergence", "Divergence ONNX/PyTorch : explication refusee.")
            values = gradcam(loaded.network, inputs)[0, 0].cpu().numpy() if is_transfer else error
            explanation_ms = (perf_counter()-explanation_started)*1000
        elapsed = (perf_counter() - started) * 1000
    if not np.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Score d'anomalie invalide.")
    result = Prediction(engine=engine, explanation_engine=("pytorch" if is_transfer else engine) if visualize else None,
                        explanation_reference_score=explanation_score, explanation_score_coherent=coherence,
                        explanation_decision_changed=decision_changed, explanation_time_ms=explanation_ms,
                        category=loaded.metadata.category, model=loaded.metadata.model, version=loaded.metadata.version,
                        anomaly_score=score, threshold=loaded.metadata.threshold,
                        decision="anomaly" if score > loaded.metadata.threshold else "normal",
                        inference_time_ms=elapsed, request_id=request_id)
    if visualize:
        return VisualizedPrediction(**result.model_dump(), visualization=render_visualization(sample, values, transfer=is_transfer))
    return result
