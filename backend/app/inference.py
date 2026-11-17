"""Inference FP32 CPU avec les calculs scientifiques du projet."""

from time import perf_counter
from uuid import UUID

import numpy as np
import torch

from resilientinspect.data.synthetic import normalize_image
from resilientinspect.evaluation import evaluate_ae
from resilientinspect.evaluation.gradcam import gradcam

from .imaging import render_visualization
from .models import LoadedModel
from .schemas import Prediction, VisualizedPrediction


def predict(loaded: LoadedModel, sample: dict, request_id: UUID, *, visualize: bool = False) -> Prediction:
    is_transfer = loaded.metadata.model in ("T0", "T1", "T2")
    images = sample["image"].unsqueeze(0)
    inputs = normalize_image(images) if is_transfer else images
    # Grad-CAM installe un hook temporaire. Le verrou protege aussi les forwards ordinaires.
    with loaded.lock, torch.autocast(device_type="cpu", enabled=False):
        started = perf_counter()
        with torch.inference_mode():
            output = loaded.network(inputs)
            if is_transfer:
                if output.shape != (1,) or not torch.isfinite(output).all():
                    raise ValueError("Un logit fini par image requis.")
                score = float(output.sigmoid()[0])
            else:
                error = evaluate_ae.anomaly_maps(images, output)[0].numpy()
                score = evaluate_ae.image_score(error, sample["valid_mask"][0].numpy(), top_fraction=0.01)
        values = None
        if visualize:
            values = gradcam(loaded.network, inputs)[0, 0].cpu().numpy() if is_transfer else error
        elapsed = (perf_counter() - started) * 1000
    if not np.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Score d'anomalie invalide.")
    result = Prediction(category=loaded.metadata.category, model=loaded.metadata.model, version=loaded.metadata.version,
                        anomaly_score=score, threshold=loaded.metadata.threshold,
                        decision="anomaly" if score > loaded.metadata.threshold else "normal",
                        inference_time_ms=elapsed, request_id=request_id)
    if visualize:
        return VisualizedPrediction(**result.model_dump(), visualization=render_visualization(sample, values, transfer=is_transfer))
    return result
