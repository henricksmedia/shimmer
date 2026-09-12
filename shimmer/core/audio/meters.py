"""One loudness meter and one true-peak meter.

The old engine had seven spectrum measures and a true-peak meter that read a
mono mix, so it under-read peaks whenever the channels differed
(docs/ARCHITECTURE.md §10). Everything that reports or limits a level reads
it from here: the limiter, the report and the release check.

- loudness: integrated loudness, ITU-R BS.1770 with its gating, by the
  reference implementation (pyloudnorm).
- true_peak_db: the louder channel, oversampled 8x. BS.1770 asks for at
  least 4x. At 4x the old limiter's -1.0 dBTP read -0.78 at 16x, so this
  meter reads at 8x, within 0.1 dB of 16x.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import resample_poly

OVERSAMPLE = 8
_BLOCK = 1 << 16          # input samples per block, so memory stays small
_PAD = 256                # extra input samples on each side of a block


def _channels(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    return a[:, None] if a.ndim == 1 else a


def loudness(x: np.ndarray, sr: int) -> float:
    """Integrated loudness in LUFS. -inf for silence, or for audio shorter
    than one 400 ms gating block."""
    import pyloudnorm as pyln
    a = _channels(x)
    if a.shape[0] < int(0.4 * sr) or not np.any(a):
        return float("-inf")
    return float(pyln.Meter(int(sr)).integrated_loudness(a))


def _oversampled_peak(ch: np.ndarray, factor: int) -> float:
    """Peak of one channel after oversampling, block by block. Each block is
    upsampled with some context either side, and only its own span is kept,
    so blocks join seamlessly."""
    n = len(ch)
    peak = 0.0
    for s in range(0, n, _BLOCK):
        e = min(n, s + _BLOCK)
        a, b = max(0, s - _PAD), min(n, e + _PAD)
        up = resample_poly(ch[a:b], factor, 1)
        lo = (s - a) * factor
        peak = max(peak, float(np.max(np.abs(up[lo:lo + (e - s) * factor]))))
    return peak


def true_peak_db(x: np.ndarray, sr: int) -> float:
    """True peak of the louder channel, in dBTP. -inf for silence."""
    a = _channels(x)
    if a.shape[0] == 0:
        return float("-inf")
    peak = float(np.max(np.abs(a)))                 # never below the sample peak
    for c in range(a.shape[1]):
        peak = max(peak, _oversampled_peak(a[:, c], OVERSAMPLE))
    return float(20.0 * np.log10(peak)) if peak > 0 else float("-inf")


def sample_peak_db(x: np.ndarray) -> float:
    """Sample peak of the louder channel, in dBFS. -inf for silence."""
    peak = float(np.max(np.abs(_channels(x)))) if np.size(x) else 0.0
    return float(20.0 * np.log10(peak)) if peak > 0 else float("-inf")
