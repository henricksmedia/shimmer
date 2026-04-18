"""
dsp.py — Pure DSP primitives used across the shimmer pipeline.

No I/O, no parameters dataclass, no processing orchestration.
Just math: conversions, windowing helpers, filter design, spectral utilities.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np
from scipy.signal import butter, sosfiltfilt


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------

def db_to_lin(db) -> np.ndarray:
    return 10.0 ** (np.asarray(db) / 20.0)


def lin_to_db(x, eps: float = 1e-12) -> np.ndarray:
    return 20.0 * np.log10(np.asarray(x) + eps)


def as_2d(x: np.ndarray) -> np.ndarray:
    """Ensure audio is (samples, channels)."""
    return x[:, None] if x.ndim == 1 else x


def band_from_center(center_hz: float, width_cents: float) -> Tuple[float, float]:
    """Convert center frequency + width-in-cents to (lo_hz, hi_hz)."""
    half = width_cents * 0.5
    ratio = 2.0 ** (half / 1200.0)
    return center_hz / ratio, center_hz * ratio


# ---------------------------------------------------------------------------
# Frequency-band helpers
# ---------------------------------------------------------------------------

def freq_bin_indices(freqs: np.ndarray, lo_hz: float, hi_hz: float) -> np.ndarray:
    """Return indices of FFT bins falling within [lo_hz, hi_hz]."""
    nyq = float(freqs[-1])
    lo = float(max(0.0, lo_hz))
    hi = float(min(nyq, hi_hz))
    if hi <= lo:
        return np.array([], dtype=np.int64)
    return np.where((freqs >= lo) & (freqs <= hi))[0]


def edge_taper(freqs: np.ndarray, band_idx: np.ndarray,
               start_hz: float, end_hz: float, edge_hz: float) -> np.ndarray:
    """Cosine taper inside edge_hz of band edges to avoid processing discontinuities."""
    w = np.ones(band_idx.size, dtype=np.float32)
    edge = float(max(0.0, edge_hz))
    if edge <= 0.0 or band_idx.size == 0:
        return w
    fb = freqs[band_idx].astype(np.float32)
    lo, hi = float(start_hz), float(end_hz)

    m_lo = fb < lo + edge
    if np.any(m_lo):
        rel = (fb[m_lo] - lo) / edge
        w[m_lo] = 0.5 - 0.5 * np.cos(np.pi * np.clip(rel, 0, 1))

    m_hi = fb > hi - edge
    if np.any(m_hi):
        rel = (hi - fb[m_hi]) / edge
        w[m_hi] = np.minimum(w[m_hi], 0.5 - 0.5 * np.cos(np.pi * np.clip(rel, 0, 1)))

    return w


# ---------------------------------------------------------------------------
# EMA / smoothing
# ---------------------------------------------------------------------------

def frame_coeff(hop: int, sr: int, ms: float) -> float:
    """Per-frame EMA coefficient for a given time constant in milliseconds."""
    tau = max(1e-4, float(ms) / 1000.0)
    return float(math.exp(-float(hop) / (float(sr) * tau)))


def spectral_flatness(power: np.ndarray, eps: float = 1e-12) -> float:
    """Spectral flatness: geometric mean / arithmetic mean of power spectrum."""
    return float(np.exp(np.mean(np.log(power + eps))) / (np.mean(power) + eps))


# ---------------------------------------------------------------------------
# Time-domain filters
# ---------------------------------------------------------------------------

def apply_high_shelf(x: np.ndarray, sr: int,
                     cutoff_hz: float, gain_db: float) -> np.ndarray:
    """
    Apply a 2nd-order high-shelf filter (zero-phase).

    gain_db < 0 = cut above cutoff, > 0 = boost above cutoff.
    """
    if abs(gain_db) < 0.1 or cutoff_hz <= 0:
        return x
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * cutoff_hz / sr
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    alpha = sin_w0 / 2.0 * np.sqrt(2.0)

    b0 = A * ((A + 1) + (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha)
    b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
    b2 = A * ((A + 1) + (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha)
    a0 = (A + 1) - (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha
    a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
    a2 = (A + 1) - (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha

    sos = np.array([[b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0]], dtype=np.float64)
    return sosfiltfilt(sos, x, axis=0).astype(np.float32)


def apply_highpass(x: np.ndarray, sr: int,
                   cutoff_hz: float, order: int = 2) -> np.ndarray:
    """Apply a Butterworth highpass filter (zero-phase)."""
    if cutoff_hz <= 0:
        return x
    wn = float(np.clip(cutoff_hz / (0.5 * sr), 1e-6, 0.999999))
    sos = butter(order, wn, btype="highpass", output="sos")
    return sosfiltfilt(sos, x, axis=0).astype(np.float32)
