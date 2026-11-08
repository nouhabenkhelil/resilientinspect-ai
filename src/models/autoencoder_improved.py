"""A1 : residus, skips bornes uniquement a basse resolution, reconstruction RGB."""

from __future__ import annotations

from collections.abc import Sequence
import math

import torch
from torch import nn


class ResidualBlock(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        self.body = nn.Sequential(
            nn.Conv2d(channels, channels, 3, padding=1, bias=False), nn.BatchNorm2d(channels), nn.ReLU(),
            nn.Conv2d(channels, channels, 3, padding=1, bias=False), nn.BatchNorm2d(channels),
        )

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        return torch.relu(images + self.body(images))


class ControlledSkip(nn.Module):
    """La branche ajoute au plus +/-scale par activation ; aucun chemin RGB direct."""

    def __init__(self, channels: int, scale: float) -> None:
        super().__init__()
        self.project = nn.Conv2d(channels, channels, 1, bias=False)
        self.register_buffer("scale", torch.tensor(scale, dtype=torch.float32))

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.scale * torch.tanh(self.project(features))


class ImprovedAutoencoder(nn.Module):
    """Quatre reductions 256->128->64->32->16, decodeur nearest/Conv symetrique.

    Les skips utilisent seulement les features encodeur 32x32 et 64x64, apres
    projection 1x1 et tanh. Les branches 128x128 et RGB 256x256 sont absentes.
    residual_blocks et skip_connections sont deux ablations independantes.
    """

    def __init__(self, channels: Sequence[int] = (32, 64, 128, 256), *,
                 residual_blocks: bool = True, skip_connections: bool = True,
                 skip_scale: float = 0.1) -> None:
        super().__init__()
        self.channels = tuple(channels)
        if len(self.channels) != 4 or any(type(c) is not int or c < 1 for c in self.channels):
            raise ValueError("A1 exige quatre largeurs de canaux strictement positives.")
        if type(residual_blocks) is not bool or type(skip_connections) is not bool:
            raise ValueError("Les options de residus/skips sont booleennes.")
        if type(skip_scale) not in (int, float) or not math.isfinite(skip_scale) or not 0 < skip_scale <= 0.25:
            raise ValueError("skip_scale doit etre dans ]0,0.25].")
        self.encoder = nn.ModuleList()
        previous = 3
        for channel in self.channels:
            self.encoder.append(nn.Sequential(
                nn.Conv2d(previous, channel, 3, stride=2, padding=1, bias=False),
                nn.BatchNorm2d(channel), nn.ReLU(),
                ResidualBlock(channel) if residual_blocks else nn.Identity(),
            ))
            previous = channel
        self.decoder = nn.ModuleList()
        self.decoder_residuals = nn.ModuleList()
        self.skips = nn.ModuleDict()
        for index, channel in enumerate(reversed(self.channels[:-1])):
            self.decoder.append(nn.Sequential(
                nn.Upsample(scale_factor=2, mode="nearest"),
                nn.Conv2d(previous, channel, 3, padding=1, bias=False), nn.BatchNorm2d(channel), nn.ReLU(),
            ))
            self.decoder_residuals.append(ResidualBlock(channel) if residual_blocks else nn.Identity())
            if skip_connections and index < 2:
                self.skips[str(index)] = ControlledSkip(channel, float(skip_scale))
            previous = channel
        self.output = nn.Sequential(nn.Upsample(scale_factor=2, mode="nearest"), nn.Conv2d(previous, 3, 3, padding=1), nn.Sigmoid())

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        if images.ndim != 4 or images.shape[0] < 1 or tuple(images.shape[1:]) != (3, 256, 256):
            raise ValueError("Entree A1 attendue : [B,3,256,256], B>=1.")
        features = []
        x = images
        for encoder in self.encoder:
            x = encoder(x)
            features.append(x)
        for index, (decoder, residual) in enumerate(zip(self.decoder, self.decoder_residuals)):
            x = decoder(x)
            if str(index) in self.skips:
                x = x + self.skips[str(index)](features[-2 - index])
            x = residual(x)
        return self.output(x)
