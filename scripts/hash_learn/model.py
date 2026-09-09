"""
hash_learn/model.py — A small mask network for hash removal.

Input: log-magnitude spectrogram of the mixture over the context bins
(2-16 kHz), [batch, 1, bins, frames]. Output: a gain in [0, 1] per bin and
frame for the same bins; outside the hash band the gain is forced to 1 by
the caller. Two-dimensional convolutions over (frequency, time) with a
receptive field of about 1.5 octaves by 300 ms, which is what the hash's
structure spans (coherent across the band, aperiodic over tens of ms to
seconds). Deliberately small: it has to run inside the fine pass on a CPU
if it ships.
"""
from __future__ import annotations

import torch
import torch.nn as nn


class Block(nn.Module):
    def __init__(self, cin, cout, k=(5, 5), d=(1, 1)):
        super().__init__()
        p = ((k[0] - 1) // 2 * d[0], (k[1] - 1) // 2 * d[1])
        self.net = nn.Sequential(
            nn.Conv2d(cin, cout, k, padding=p, dilation=d),
            nn.BatchNorm2d(cout), nn.GELU())

    def forward(self, x):
        return self.net(x)


class MaskNet(nn.Module):
    def __init__(self, width=32):
        super().__init__()
        self.body = nn.Sequential(
            Block(1, width),
            Block(width, width, d=(2, 1)),
            Block(width, width, d=(4, 2)),
            Block(width, width, d=(8, 4)),
            Block(width, width, d=(1, 8)),
            Block(width, width))
        self.head = nn.Conv2d(width, 1, 1)

    def forward(self, x):
        # x: [B, 1, F, T] log-magnitude, normalised per example by the caller
        return torch.sigmoid(self.head(self.body(x)))
