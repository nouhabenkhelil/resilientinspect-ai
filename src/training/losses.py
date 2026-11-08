"""L1 et SSIM differentiable, sans dependance supplementaire ni statistiques test."""

from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F


class ReconstructionLoss(nn.Module):
    """SSIM mono-echelle RGB, fenetre gaussienne 11 sigma=1.5, convolution valid.

    Moyenne sur batch/canaux/fenetres, L=1, K1=.01, K2=.03, moments population.
    Variances negatives dues a l'arrondi ramenees a zero, SSIM bornee [-1,1].
    Perte mixte = w_L1 * L1 + w_SSIM * (1-SSIM)/2. Pas de MS-SSIM.
    """

    def __init__(self, name: str = "l1_ssim", l1_weight: float = 0.8, ssim_weight: float = 0.2,
                 window_size: int = 11, sigma: float = 1.5) -> None:
        super().__init__()
        if name not in ("l1", "l1_ssim") or window_size != 11 or sigma != 1.5:
            raise ValueError("Perte attendue : l1 ou l1_ssim, fenetre 11, sigma 1.5.")
        if (any(type(w) not in (int, float) or not math.isfinite(w) or w < 0 for w in (l1_weight, ssim_weight))
                or not math.isclose(l1_weight + ssim_weight, 1.0, abs_tol=1e-9)
                or l1_weight <= 0 or (name == "l1" and (l1_weight != 1 or ssim_weight != 0))
                or (name == "l1_ssim" and ssim_weight <= 0)):
            raise ValueError("Poids positifs de somme 1 ; l1 seule exige 1/0.")
        self.name, self.l1_weight, self.ssim_weight = name, l1_weight, ssim_weight
        # Double pour le test numerique ; conversion au dtype/device d'entree en forward.
        coordinate = torch.arange(window_size, dtype=torch.float64) - window_size // 2
        gaussian = torch.exp(-coordinate.square() / (2 * sigma**2))
        self.register_buffer("gaussian", gaussian / gaussian.sum())

    def components(self, prediction: torch.Tensor, target: torch.Tensor) -> dict[str, torch.Tensor]:
        if (prediction.shape != target.shape or prediction.ndim != 4 or prediction.shape[1] != 3
                or prediction.shape[0] < 1 or min(prediction.shape[-2:]) < 11
                or prediction.dtype not in (torch.float32, torch.float64) or target.dtype != prediction.dtype
                or target.device != prediction.device):
            raise ValueError("Perte : deux RGB BCHW apparies float32/64 d'au moins 11x11 requis.")
        if not all(torch.isfinite(x).all() and x.min() >= 0 and x.max() <= 1 for x in (prediction, target)):
            raise ValueError("Perte : pixels finis dans [0,1] requis.")
        l1 = F.l1_loss(prediction, target)
        if self.name == "l1":
            return {"loss": l1, "l1_loss": l1}
        x, y = prediction, target
        moments = torch.cat((x, y, x.square(), y.square(), x * y), dim=1)
        channels = moments.shape[1]
        gaussian = self.gaussian.to(device=x.device, dtype=x.dtype)
        horizontal = gaussian.reshape(1, 1, 1, -1).expand(channels, 1, 1, -1).contiguous()
        vertical = gaussian.reshape(1, 1, -1, 1).expand(channels, 1, -1, 1).contiguous()
        moments = F.conv2d(F.conv2d(moments, horizontal, groups=channels), vertical, groups=channels)
        mx, my, ex2, ey2, exy = moments.chunk(5, dim=1)
        vx, vy, covariance = (ex2 - mx.square()).clamp_min(0), (ey2 - my.square()).clamp_min(0), exy - mx * my
        ssim = ((2 * mx * my + 0.01**2) * (2 * covariance + 0.03**2)
                / ((mx.square() + my.square() + 0.01**2) * (vx + vy + 0.03**2)))
        ssim_loss = (1 - ssim.clamp(-1, 1).mean()) / 2
        return {"loss": self.l1_weight * l1 + self.ssim_weight * ssim_loss,
                "l1_loss": l1, "ssim_loss": ssim_loss}

    def forward(self, prediction: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        return self.components(prediction, target)["loss"]
