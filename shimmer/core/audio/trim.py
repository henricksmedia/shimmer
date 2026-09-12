"""Cutting silence from the start and end of a song.

Ported unchanged from shimmer/dsp.py (1.1.1): find_audible_bounds and
trim_silence (docs/ARCHITECTURE.md §19.1 item 1).
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


def _as_2d(x: np.ndarray) -> np.ndarray:
    return x[:, None] if x.ndim == 1 else x


def find_audible_bounds(x: np.ndarray, sr: int,
                        threshold_db: float = -60.0,
                        window_ms: float = 20.0) -> Optional[Tuple[int, int]]:
    """Return (start, end) sample indices of audible content, or None if
    the whole file is below the threshold. Detection uses a windowed RMS
    so a low-level noise floor doesn't count as audio."""
    x = _as_2d(np.asarray(x, dtype=np.float32))
    mono = np.max(np.abs(x), axis=1)
    win = max(1, int(sr * window_ms / 1000.0))
    sq = np.concatenate(([0.0], np.cumsum(mono.astype(np.float64) ** 2)))
    if sq.shape[0] <= win:
        return None
    rms = np.sqrt((sq[win:] - sq[:-win]) / win)
    threshold = 10.0 ** (threshold_db / 20.0)
    audible = np.flatnonzero(rms > threshold)
    if audible.size == 0:
        return None
    # rms[i] covers samples [i, i+win); map back to sample positions.
    return int(audible[0]), int(min(audible[-1] + win, x.shape[0]))


def trim_silence(x: np.ndarray, sr: int,
                 threshold_db: float = -60.0,
                 head_pad_ms: float = 50.0,
                 tail_pad_ms: float = 250.0,
                 fade_ms: float = 10.0) -> Tuple[np.ndarray, float, float]:
    """Clip silence from the start/end of (samples, channels) audio.

    Keeps head_pad_ms / tail_pad_ms of breathing room around the audible
    region and applies short edge fades so a mid-waveform cut can't click.
    Returns (audio, seconds_cut_head, seconds_cut_tail).
    """
    x = _as_2d(np.asarray(x, dtype=np.float32))
    bounds = find_audible_bounds(x, sr, threshold_db)
    if bounds is None:
        return x, 0.0, 0.0

    start, end = bounds
    start = max(0, start - int(sr * head_pad_ms / 1000.0))
    end = min(x.shape[0], end + int(sr * tail_pad_ms / 1000.0))
    if start == 0 and end == x.shape[0]:
        return x, 0.0, 0.0
    y = x[start:end].copy()

    fade = min(int(sr * fade_ms / 1000.0), y.shape[0] // 2)
    if fade > 1:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
        y[:fade] *= ramp
        y[-fade:] *= ramp[::-1]

    return y, start / sr, (x.shape[0] - end) / sr
