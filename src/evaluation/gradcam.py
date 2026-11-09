"""Grad-CAM du logit binaire : attribution grossiere, aucune segmentation pixel."""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from resilientinspect.models.transfer import GRADCAM_TARGET, TransferClassifier


def gradcam(model: TransferClassifier, images: torch.Tensor, *, target_class: int = 1) -> torch.Tensor:
    """Explique +logit (anomalie=1) ou -logit (normal=0) via features[8][0].

    Cette derniere convolution 1x1 produit 1280 canaux a resolution 8x8 pour
    une entree 256x256. La carte relue en 256x256 n'est pas un masque de defaut.
    Les poids, buffers BN, gradients existants et modes du modele sont preserves.
    """
    if type(target_class) is not int or target_class not in (0, 1):
        raise ValueError("Classe cible binaire 0 ou 1 requise.")
    if (images.ndim != 4 or images.shape[0] < 1 or images.shape[1] != 3
            or not images.is_floating_point() or not torch.isfinite(images).all()):
        raise ValueError("Batch RGB flottant fini requis pour Grad-CAM.")
    target = model.get_submodule(GRADCAM_TARGET)
    if not isinstance(target, nn.Conv2d):
        raise ValueError("Couche cible Grad-CAM convolutionnelle introuvable.")
    modes = {module: module.training for module in model.modules()}
    activations = []
    handle = target.register_forward_hook(lambda module, inputs, output: activations.append(output))
    try:
        model.eval()
        with torch.inference_mode(False), torch.enable_grad():
            inputs = images.detach().clone().requires_grad_(True)
            logits = model(inputs)
            if len(activations) != 1 or not torch.isfinite(logits).all():
                raise ValueError("Activation Grad-CAM unique et logits finis requis.")
            activation = activations[0]
            score = logits.sum() if target_class == 1 else -logits.sum()
            gradients, = torch.autograd.grad(score, activation)
            cam = torch.relu((gradients.mean(dim=(2, 3), keepdim=True) * activation).sum(dim=1, keepdim=True))
            cam = F.interpolate(cam, size=images.shape[-2:], mode="bilinear", align_corners=False)
            minimum = cam.amin(dim=(2, 3), keepdim=True)
            span = cam.amax(dim=(2, 3), keepdim=True) - minimum
            cam = torch.where(span > 0, (cam - minimum) / span.clamp_min(torch.finfo(cam.dtype).eps), torch.zeros_like(cam))
            if not torch.isfinite(cam).all():
                raise ValueError("Grad-CAM non finie.")
            return cam.detach()
    finally:
        handle.remove()
        for module, training in modes.items():
            module.training = training
