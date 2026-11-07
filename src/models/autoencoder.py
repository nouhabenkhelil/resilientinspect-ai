"""Baseline B0 : reconstruction RGB sans skip connections ni poids preentraines."""

from __future__ import annotations

from collections.abc import Sequence

import torch
from torch import nn


class ConvAutoencoder(nn.Module):
    """CNN compact, entree et reconstruction flottantes [B, 3, 256, 256].

    Chaque bloc encodeur divise la resolution par deux (Conv 3x3, stride 2,
    padding 1, sans biais avant BatchNorm). Le decodeur utilise un upsampling
    nearest x2 suivi d'une Conv 3x3. BatchNorm et ReLU suivent les convolutions
    intermediaires ; la derniere convolution RGB a un biais et une Sigmoid.

    Le modele ne redimensionne ni ne normalise les entrees. Les pixels attendus
    sont dans [0, 1], selon le pretraitement deja fixe. Le placement CPU/CUDA et
    les modes train/eval restent sous le controle de l'appelant.
    """

    def __init__(self, channels: Sequence[int] = (16, 32, 64, 128)) -> None:
        super().__init__()
        self.channels = tuple(channels)
        if len(self.channels) not in (3, 4) or any(
            type(channel) is not int or channel <= 0 for channel in self.channels
        ):
            raise ValueError("channels doit contenir 3 ou 4 entiers strictement positifs.")

        encoder_blocks = []
        previous = 3
        for channel in self.channels:
            encoder_blocks.append(nn.Sequential(
                nn.Conv2d(previous, channel, kernel_size=3, stride=2, padding=1, bias=False),
                nn.BatchNorm2d(channel),
                nn.ReLU(inplace=True),
            ))
            previous = channel
        self.encoder = nn.Sequential(*encoder_blocks)

        decoder_blocks = []
        for channel in reversed(self.channels[:-1]):
            decoder_blocks.append(nn.Sequential(
                nn.Upsample(scale_factor=2, mode="nearest"),
                nn.Conv2d(previous, channel, kernel_size=3, padding=1, bias=False),
                nn.BatchNorm2d(channel),
                nn.ReLU(inplace=True),
            ))
            previous = channel
        decoder_blocks.append(nn.Sequential(
            nn.Upsample(scale_factor=2, mode="nearest"),
            nn.Conv2d(previous, 3, kernel_size=3, padding=1),
            nn.Sigmoid(),
        ))
        self.decoder = nn.Sequential(*decoder_blocks)

    def forward(self, images: torch.Tensor) -> torch.Tensor:
        if images.ndim != 4 or images.shape[0] < 1 or tuple(images.shape[1:]) != (3, 256, 256):
            raise ValueError("Entree attendue : [B, 3, 256, 256], avec B >= 1.")
        return self.decoder(self.encoder(images))
