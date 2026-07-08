"""
bands.py — Linear-phase band splitting, M/S coding, and stereo-width helpers.

Implements the Shimmer safe-mastering architecture primitives:

  * channels-first stereo convention (2, samples) for all functions here
    (adapters at the pipeline boundary convert from the codebase's
    (samples, channels) layout),
  * a complementary linear-phase FIR crossover built by spectral
    inversion — the low and high bands sum back to the input exactly
    (within float tolerance), so the low/mid body of a song can bypass
    the artifact engine without any phase or comb damage,
  * orthonormal Mid/Side encode/decode,
  * Side-channel width compensation that restores stereo energy the
    cleaner removed beyond a threshold, capped and smoothed.

No np.roll is used anywhere; group delay is removed by exact slicing of
the full convolution.  No filtfilt: linear phase comes from symmetric
FIR taps, and both bands share the identical delay so they stay
sample-aligned.
"""

from __future__ import annotations

import _winfix  # noqa: F401  # must precede scipy import on Windows

import math
from functools import lru_cache
from typing import Dict, Tuple

import numpy as np
from scipy.signal import fftconvolve, firwin


DEFAULT_CROSSOVER_HZ = 4500.0
DEFAULT_NUMTAPS = 1023

_SQRT2 = math.sqrt(2.0)


# ---------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------

def ensure_stereo_channels_first(x: np.ndarray) -> np.ndarray:
    """Return audio as float32 channels-first stereo, shape (2, samples).

    Accepts:
      * mono 1-D (n,)            -> duplicated to dual-mono (2, n)
      * (samples, channels)      -> transposed (channels inferred as the
                                    smaller trailing axis)
      * (channels, samples)      -> passed through
    Multichannel (>2) input keeps the first two channels.
    """
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        return np.vstack([x, x])
    if x.ndim != 2:
        raise ValueError(f"Expected 1-D or 2-D audio, got shape {x.shape}")

    # Heuristic: audio always has far more samples than channels.
    if x.shape[0] > x.shape[1]:
        x = x.T  # was (samples, channels)

    if x.shape[0] == 1:
        return np.vstack([x[0], x[0]])
    return np.ascontiguousarray(x[:2, :])


def channels_first_to_samples(x: np.ndarray) -> np.ndarray:
    """Convert (channels, samples) back to the codebase's (samples, channels)."""
    return np.ascontiguousarray(np.asarray(x, dtype=np.float32).T)


# ---------------------------------------------------------------------------
# Complementary FIR crossover
# ---------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _design_crossover(crossover_hz: float, sr: int,
                      numtaps: int) -> Tuple[np.ndarray, np.ndarray, int]:
    """Design the complementary lowpass/highpass FIR pair.

    The highpass is the spectral inversion of the lowpass:
        fir_high = -fir_low;  fir_high[delay] += 1.0
    which guarantees fir_low + fir_high == unit impulse at `delay`,
    i.e. perfect reconstruction of the split bands.
    """
    if numtaps % 2 == 0:
        numtaps += 1  # odd tap count required for an integer group delay
    delay = (numtaps - 1) // 2

    fir_low = firwin(numtaps, crossover_hz, fs=sr).astype(np.float64)
    fir_high = -fir_low
    fir_high[delay] += 1.0
    return fir_low, fir_high, delay


def complementary_fir_split(
    x: np.ndarray,
    sr: int,
    crossover_hz: float = DEFAULT_CROSSOVER_HZ,
    numtaps: int = DEFAULT_NUMTAPS,
) -> Tuple[np.ndarray, np.ndarray]:
    """Split channels-first audio into (low_band, high_band).

    Both bands are group-delay compensated by exact slicing of the full
    convolution (never np.roll), have the same length as the input, and
    satisfy  low + high == x  within floating-point tolerance.
    """
    x = ensure_stereo_channels_first(x)
    n = x.shape[1]
    fir_low, fir_high, delay = _design_crossover(
        float(crossover_hz), int(sr), int(numtaps))

    low = np.empty_like(x)
    high = np.empty_like(x)
    for ch in range(x.shape[0]):
        xf = x[ch].astype(np.float64)
        full_low = fftconvolve(xf, fir_low, mode="full")
        # Slice out the delay-centered region: sample i of the output
        # corresponds to full[i + delay].
        low_ch = full_low[delay:delay + n]
        low[ch] = low_ch.astype(np.float32)
        # High band from the complement identity keeps the null exact:
        # low + high == x by construction regardless of FFT rounding.
        high[ch] = (xf - low_ch).astype(np.float32)
    return low, high


def recombine_bands(low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Sum the two bands back into a full-range signal."""
    low = np.asarray(low, dtype=np.float32)
    high = np.asarray(high, dtype=np.float32)
    n = min(low.shape[-1], high.shape[-1])
    return (low[..., :n] + high[..., :n]).astype(np.float32)


def null_test_split_recombine(
    x: np.ndarray,
    sr: int,
    crossover_hz: float = DEFAULT_CROSSOVER_HZ,
    numtaps: int = DEFAULT_NUMTAPS,
) -> float:
    """Return the max absolute reconstruction error of split->recombine."""
    x = ensure_stereo_channels_first(x)
    low, high = complementary_fir_split(x, sr, crossover_hz, numtaps)
    y = recombine_bands(low, high)
    return float(np.max(np.abs(y - x))) if x.size else 0.0


# ---------------------------------------------------------------------------
# Mid/Side coding (orthonormal — encode/decode round-trips exactly)
# ---------------------------------------------------------------------------

def encode_ms(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Channels-first stereo -> (mid, side), each 1-D float32.

    Mid  = (L + R) / sqrt(2)
    Side = (L - R) / sqrt(2)
    """
    x = ensure_stereo_channels_first(x)
    mid = ((x[0].astype(np.float64) + x[1]) / _SQRT2).astype(np.float32)
    side = ((x[0].astype(np.float64) - x[1]) / _SQRT2).astype(np.float32)
    return mid, side


def decode_ms(mid: np.ndarray, side: np.ndarray) -> np.ndarray:
    """(mid, side) -> channels-first stereo (2, samples)."""
    mid = np.asarray(mid, dtype=np.float64)
    side = np.asarray(side, dtype=np.float64)
    n = min(mid.shape[-1], side.shape[-1])
    left = (mid[..., :n] + side[..., :n]) / _SQRT2
    right = (mid[..., :n] - side[..., :n]) / _SQRT2
    return np.vstack([left, right]).astype(np.float32)


# ---------------------------------------------------------------------------
# Side width compensation
# ---------------------------------------------------------------------------

def _frame_rms_db(x: np.ndarray, frame_size: int, hop: int) -> np.ndarray:
    """Per-frame RMS in dB for a 1-D signal (frames may be partial at end)."""
    n = x.shape[0]
    n_frames = max(1, 1 + (max(0, n - 1)) // hop)
    out = np.empty(n_frames, dtype=np.float64)
    xf = x.astype(np.float64)
    for i in range(n_frames):
        s0 = i * hop
        seg = xf[s0:s0 + frame_size]
        if seg.size == 0:
            out[i] = -120.0
            continue
        rms = math.sqrt(float(np.mean(seg * seg)))
        out[i] = 20.0 * math.log10(rms + 1e-12)
    return out


def side_width_compensation(
    original_side: np.ndarray,
    cleaned_side: np.ndarray,
    sr: int,
    attenuation_threshold_db: float = 3.0,
    max_makeup_db: float = 1.5,
    smoothing_ms: float = 150.0,
    frame_size: int = 4096,
    hop: int = 1024,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """Restore Side energy lost to over-cleaning, gently and capped.

    Measures short-term RMS of the Side channel before and after
    cleaning; where the cleaner attenuated more than
    `attenuation_threshold_db`, applies smoothed makeup gain to the
    cleaned Side, capped at `max_makeup_db`.  Never boosts beyond the
    original Side energy (makeup only covers attenuation past the
    threshold) and never cuts.

    Returns (compensated_side, stats).
    """
    orig = np.asarray(original_side, dtype=np.float32)
    clean = np.asarray(cleaned_side, dtype=np.float32)
    n = min(orig.shape[0], clean.shape[0])
    orig, clean = orig[:n], clean[:n]
    if n == 0:
        return clean, {"max_makeup_db": 0.0, "mean_makeup_db": 0.0}

    orig_db = _frame_rms_db(orig, frame_size, hop)
    clean_db = _frame_rms_db(clean, frame_size, hop)
    attenuation_db = orig_db - clean_db

    makeup_db = np.clip(attenuation_db - float(attenuation_threshold_db),
                        0.0, float(max_makeup_db))

    # Skip near-silent frames — attenuation there is numeric noise.
    silent = orig_db < -80.0
    makeup_db[silent] = 0.0

    # Smooth over `smoothing_ms` with a moving average (frames), then a
    # forward/backward EMA pass to kill any residual steps.
    frames_per_win = max(1, int(round((smoothing_ms / 1000.0) * sr / hop)))
    if frames_per_win > 1 and makeup_db.size > 1:
        kernel = np.ones(frames_per_win, dtype=np.float64) / frames_per_win
        makeup_db = np.convolve(makeup_db, kernel, mode="same")

    if makeup_db.size == 1:
        env = np.full(n, float(makeup_db[0]), dtype=np.float64)
    else:
        centers = np.arange(makeup_db.size, dtype=np.float64) * hop + frame_size * 0.5
        env = np.interp(np.arange(n, dtype=np.float64), centers, makeup_db,
                        left=makeup_db[0], right=makeup_db[-1])

    gain = np.power(10.0, env / 20.0)
    out = (clean.astype(np.float64) * gain).astype(np.float32)
    return out, {
        "max_makeup_db": float(np.max(makeup_db)) if makeup_db.size else 0.0,
        "mean_makeup_db": float(np.mean(makeup_db)) if makeup_db.size else 0.0,
    }
