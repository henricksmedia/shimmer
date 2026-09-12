"""The peak shaper and the true-peak limiter.

Ported unchanged from shimmer/mastering.py (1.1.1) first, so the copy could
be nulled against the original (docs/ARCHITECTURE.md §19.1 item 1). Fixes
land after this one at a time, each listed with numbers in
docs/SOUND-CHANGES.md.

Chain position: after the static loudness gain. The shaper takes the top
~2 dB, then the limiter trims true peaks to the ceiling in one pass.
"""
from __future__ import annotations

import math
from typing import Dict, Tuple

import numpy as np
from scipy.ndimage import maximum_filter1d
from scipy.signal import resample_poly

_OVERSAMPLE = 4


def _as_2d(x: np.ndarray) -> np.ndarray:
    return x[:, None] if x.ndim == 1 else x


def _db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def _peak_hold_release(x: np.ndarray, coeff: float) -> np.ndarray:
    """Vectorized peak-hold with exponential decay:

        y[i] = max(x[i], y[i-1] * coeff)

    Instant attack (y snaps up to x), exponential release. Computed
    blockwise with the scaled-cummax trick so no per-sample Python loop
    is needed; block size is bounded so coeff**-block stays well inside
    float64 range.
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n == 0 or coeff <= 0.0:
        return x.copy()
    # coeff**-B <= 1e12  =>  B <= 12*ln(10) / -ln(coeff)
    block = int(min(8192.0, max(1.0, 12.0 * math.log(10.0)
                                / max(1e-12, -math.log(min(coeff, 0.9999999))))))
    out = np.empty(n, dtype=np.float64)
    state = 0.0
    for s in range(0, n, block):
        blk = x[s:s + block]
        m = blk.size
        k = np.arange(1, m + 1, dtype=np.float64)
        decay = coeff ** k
        within = np.maximum.accumulate(blk / decay) * decay
        res = np.maximum(within, state * decay)
        out[s:s + m] = res
        state = float(res[-1])
    return out


def soft_peak_shaper(x: np.ndarray, ceiling_dbtp: float = -1.0,
                     knee_db: float = 2.0) -> Tuple[np.ndarray, Dict[str, float]]:
    """Gentle waveshaper catching the top ~`knee_db` dB before the limiter.

    Below the knee the signal is bit-transparent (identity). Inside the
    knee, peaks are smoothly compressed with a rational soft clip that
    approaches (but never quite reaches) ~1 dB above the ceiling, so the
    true-peak limiter that follows only has to shave the last fraction
    of a dB instead of doing all the work.
    """
    x = _as_2d(np.asarray(x, dtype=np.float64))
    ceiling = float(_db_to_lin(ceiling_dbtp))
    knee_start = float(ceiling * _db_to_lin(-abs(knee_db)))
    span = max(1e-9, ceiling * 1.12 - knee_start)

    ax = np.abs(x)
    over = ax > knee_start
    if not np.any(over):
        return x.astype(np.float32), {"shaped_ratio": 0.0}

    t = np.clip((ax[over] - knee_start) / span, 0.0, None)
    shaped = knee_start + span * (t / (1.0 + t))
    y = x.copy()
    y[over] = np.sign(x[over]) * shaped
    return y.astype(np.float32), {"shaped_ratio": float(np.mean(over))}


def true_peak_limiter(x: np.ndarray, sr: int,
                      ceiling_dbtp: float = -1.0,
                      lookahead_ms: float = 2.0,
                      release_ms: float = 50.0) -> Tuple[np.ndarray, Dict[str, float]]:
    """Lookahead brickwall limiter with oversampled true-peak detection."""
    x = _as_2d(np.asarray(x, dtype=np.float64))
    ceiling = float(_db_to_lin(ceiling_dbtp))
    n_samples, n_ch = x.shape
    if n_samples == 0:
        return x.astype(np.float32), {"max_gain_reduction_db": 0.0,
                                      "ceiling_dbtp": float(ceiling_dbtp)}

    if _OVERSAMPLE > 1:
        peak_env = np.zeros(n_samples, dtype=np.float64)
        for ch in range(n_ch):
            up = np.abs(resample_poly(x[:, ch], _OVERSAMPLE, 1))
            need = n_samples * _OVERSAMPLE
            if up.size < need:
                up = np.pad(up, (0, need - up.size))
            grp = up[:need].reshape(n_samples, _OVERSAMPLE).max(axis=1)
            peak_env = np.maximum(peak_env, grp)
    else:
        peak_env = np.max(np.abs(x), axis=1)

    lookahead_n = max(1, int(round(lookahead_ms * 0.001 * sr)))
    if lookahead_n > 1:
        origin = -(lookahead_n // 2)
        env = maximum_filter1d(peak_env, size=lookahead_n, mode="nearest", origin=origin)
    else:
        env = peak_env

    gain = np.minimum(1.0, ceiling / np.maximum(env, 1e-12))

    release_coeff = math.exp(-1.0 / (max(1e-4, release_ms * 0.001) * sr))
    g_smooth = 1.0 - _peak_hold_release(1.0 - gain, release_coeff)

    min_gain = float(np.min(g_smooth))
    max_gr_db = 20.0 * math.log10(max(min_gain, 1e-12)) if min_gain < 1.0 else 0.0

    y = (x * g_smooth[:, None]).astype(np.float32)
    return y, {"max_gain_reduction_db": float(max_gr_db),
               "ceiling_dbtp": float(ceiling_dbtp)}
