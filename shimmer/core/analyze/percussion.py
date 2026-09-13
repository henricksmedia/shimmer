"""How percussive a song is: the share of its energy in hits (drums,
plucks) rather than held notes. Measures only.

Median-filter harmonic/percussive separation (D. Fitzgerald, "Harmonic/
percussive separation using median filtering", DAFx 2010). In a
spectrogram, a held note is smooth along time and a hit is smooth along
frequency. A median across time keeps the notes, a median across frequency
keeps the hits, and soft masks share each cell between the two.

Reference-track matching uses it: a reference far more or less percussive
than the song skews the match, since drums lift the bass and the top
(docs/MASTERING-SOURCES.md §3 and §4).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import median_filter
from scipy.signal import resample_poly, stft

_SR = 22050           # enough for drums and notes, and quick
_SLICE_S = 10.0       # three slices, at 20, 50 and 80 % of the song
_NFFT = 1024
_HOP = 256
_KERNEL = 17          # frames across time, bins across frequency (the paper's size)


def _slices(mono: np.ndarray, sr: int):
    n = mono.shape[0]
    w = int(_SLICE_S * sr)
    if n <= 3 * w:
        return [mono]
    return [mono[int(n * f) - w // 2:int(n * f) - w // 2 + w] for f in (0.2, 0.5, 0.8)]


def percussive_share(x: np.ndarray, sr: int) -> float:
    """The hits' share of the energy: 0 is all held notes, 1 all hits.
    0.0 for silence."""
    a = np.asarray(x, dtype=np.float64)
    mono = a.mean(axis=1) if a.ndim == 2 else a
    sr = int(sr)
    g = math.gcd(sr, _SR)
    hits = held = 0.0
    for seg in _slices(mono, sr):
        if sr != _SR:
            seg = resample_poly(seg, _SR // g, sr // g)
        if seg.shape[0] < _NFFT:
            continue
        _, _, z = stft(seg, fs=_SR, nperseg=_NFFT, noverlap=_NFFT - _HOP)
        mag = np.abs(z)                                   # (bins, frames)
        held_mag = median_filter(mag, size=(1, _KERNEL))  # smooth along time
        hit_mag = median_filter(mag, size=(_KERNEL, 1))   # smooth along frequency
        h2, p2 = held_mag ** 2, hit_mag ** 2
        share = p2 / (h2 + p2 + 1e-20)
        power = mag ** 2
        hits += float(np.sum(power * share))
        held += float(np.sum(power * (1.0 - share)))
    total = hits + held
    return hits / total if total > 0.0 else 0.0
