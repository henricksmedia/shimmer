"""The peak shaper and the true-peak limiter.

Ported unchanged from shimmer/mastering.py (1.1.1) first, so the copy could
be nulled against the original (docs/ARCHITECTURE.md §19.1 item 1). Fixes
land after this one at a time, each listed with numbers in
docs/SOUND-CHANGES.md.

Chain position: after the static loudness gain. The shaper (a soft clipper,
at 4x) takes the peaks, then the limiter trims true peaks to the ceiling in
one pass.
"""
from __future__ import annotations

import math
from typing import Dict, Tuple

import numpy as np
from scipy.ndimage import minimum_filter1d
from scipy.signal import firwin, oaconvolve, resample_poly

# Peaks are found at 8x, the rate the meter reads (shimmer.core.audio.meters).
# 1.1.1 found them at 4x, and its -1.0 dBTP read -0.78 at 16x.
_OVERSAMPLE = 8
_BLOCK = 1 << 16          # input samples per block, so memory stays small
_PAD = 256                # context on each side of a block


def _true_peak_envelope(ch: np.ndarray, factor: int) -> np.ndarray:
    """For each input sample, the largest oversampled value in its span.
    Computed block by block with context on each side, so the blocks join
    seamlessly and a long song never needs the whole oversampled signal in
    memory at once."""
    n = len(ch)
    env = np.empty(n, dtype=np.float64)
    for s in range(0, n, _BLOCK):
        e = min(n, s + _BLOCK)
        a, b = max(0, s - _PAD), min(n, e + _PAD)
        up = np.abs(resample_poly(ch[a:b], factor, 1))
        lo = (s - a) * factor
        env[s:e] = up[lo:lo + (e - s) * factor].reshape(e - s, factor).max(axis=1)
    return env


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


# The shaper works at 4x, as Ozone and FabFilter clip: a curve at the base
# rate folds its new harmonics back below Nyquist as off-key tones (at -9
# LUFS they reached -25 to -44 dB against the top end, docs/CHAIN-AUDIT.md
# section 4). At 4x they land above the audible range and the filter back
# down takes them out.
_SHAPER_OVERSAMPLE = 4
# The filter up and back down: steep (Kaiser, beta 10), passing up to 90 % of
# the base rate's Nyquist, run by FFT. It only ever filters the shaper's
# change, never the music, so its early roll-off costs nothing. scipy's
# default resampling filter left the fold-back of a 9 kHz tone at -49 dB;
# this one leaves -64 dB, which is what 4x itself allows (a far harmonic
# folds at 4x), in a third of the time of a longer one.
_SHAPER_FIR = firwin(_SHAPER_OVERSAMPLE * 64 + 1, 0.9 / _SHAPER_OVERSAMPLE,
                     window=("kaiser", 10.0))


def _up(v: np.ndarray, factor: int) -> np.ndarray:
    z = np.zeros((v.shape[0] * factor, v.shape[1]))
    z[::factor] = v * factor
    return oaconvolve(z, _SHAPER_FIR[:, None], mode="same", axes=0)


def _down(v: np.ndarray, factor: int) -> np.ndarray:
    return oaconvolve(v, _SHAPER_FIR[:, None], mode="same", axes=0)[::factor]


def _shape(m: np.ndarray, knee_start: float, span: float) -> np.ndarray:
    """The rational soft clip, on magnitudes above the knee."""
    t = np.clip((m - knee_start) / span, 0.0, None)
    return knee_start + span * (t / (1.0 + t))


# Only stretches near a peak are worked on: a sample within 3 dB of the knee
# marks one (a peak between samples rarely stands 3 dB above them), widened
# by _SHAPER_REACH samples each side, which covers the filter's reach
# (32 samples each way at the base rate) with room to spare.
_SHAPER_NEAR_DB = 3.0
_SHAPER_REACH = 256


def soft_peak_shaper(x: np.ndarray, ceiling_dbtp: float = -1.0,
                     knee_db: float = 2.0) -> Tuple[np.ndarray, Dict[str, float]]:
    """A soft clipper before the limiter.

    Peaks above the knee (knee_db under the ceiling) are rounded off by a
    rational soft clip that approaches, but never quite reaches, about 1 dB
    above the ceiling; the true-peak limiter after it trims the rest. How
    much it takes depends on the loudness target: at -9 LUFS it cut peaks
    by up to 7.7 dB on real songs (docs/CHAIN-AUDIT.md section 4), so it is
    the main peak stage, not a trim of the top 2 dB as 1.1.1 said.

    It works at _SHAPER_OVERSAMPLE times the rate, and both channels get the
    same gain (the louder one decides), so the stereo image stays put. Only
    the change is filtered back down and added to the input, and only near
    peaks: elsewhere the output is the input, sample for sample. Each
    stretch is worked out from the samples around it alone, so a preview
    window matches the same span of a full render.
    """
    x = _as_2d(np.asarray(x, dtype=np.float64))
    ceiling = float(_db_to_lin(ceiling_dbtp))
    knee_start = float(ceiling * _db_to_lin(-abs(knee_db)))
    span = max(1e-9, ceiling * 1.12 - knee_start)
    F = _SHAPER_OVERSAMPLE
    n = x.shape[0]
    y = x.copy()
    if n == 0:
        return y.astype(np.float32), {"shaped_ratio": 0.0}
    near = np.max(np.abs(x), axis=1) > knee_start * _db_to_lin(-_SHAPER_NEAR_DB)
    if not np.any(near):
        return y.astype(np.float32), {"shaped_ratio": 0.0}
    # Stretches: the near samples, widened by _SHAPER_REACH each side.
    idx = np.flatnonzero(near)
    gaps = np.flatnonzero(np.diff(idx) > 2 * _SHAPER_REACH)
    starts = np.concatenate([[idx[0]], idx[gaps + 1]])
    ends = np.concatenate([idx[gaps], [idx[-1]]])
    shaped = 0
    for s0, e0 in zip(starts, ends):
        s = max(0, int(s0) - _SHAPER_REACH)
        e = min(n, int(e0) + 1 + _SHAPER_REACH)
        a, b = max(0, s - _SHAPER_REACH), min(n, e + _SHAPER_REACH)
        up = _up(x[a:b], F)
        m = np.max(np.abs(up), axis=1)
        over = m > knee_start
        if not np.any(over):
            continue
        g = np.ones_like(m)
        g[over] = _shape(m[over], knee_start, span) / m[over]
        back = _down(up * (g - 1.0)[:, None], F)
        lo = s - a
        y[s:e] += back[lo:lo + (e - s)]
        mid = over[lo * F:(lo + e - s) * F]
        shaped += int(np.count_nonzero(mid.reshape(-1, F).any(axis=1)))
    return y.astype(np.float32), {"shaped_ratio": float(shaped / n)}


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

    peak_env = np.max(np.abs(x), axis=1)
    for ch in range(n_ch):
        peak_env = np.maximum(peak_env, _true_peak_envelope(x[:, ch], _OVERSAMPLE))

    # The gain each sample needs so its true peak lands on the ceiling. The
    # aim sits just under it: between two 8x readings a peak can hide by at
    # most cos(pi/16), 0.17 dB, and 1.1.1 aimed at the ceiling itself, so
    # its output read above it at 16x.
    aim = ceiling * math.cos(math.pi / (2 * _OVERSAMPLE))
    need = np.minimum(1.0, aim / np.maximum(peak_env, 1e-12))

    # The gain ramps down across the lookahead instead of stepping. 1.1.1
    # dropped it within one sample at each peak (up to 3.8 dB in a single
    # sample on the sparse test mix), and a step like that is a click.
    # Each sample takes the lowest gain needed in the next L samples, then an
    # L-sample moving average smooths that. At any peak p, the average covers
    # samples whose look-ahead windows all include p. Each of those values is
    # at most p's need, so their average is too: the ceiling still holds.
    L = max(1, int(round(lookahead_ms * 0.001 * sr)))
    if L > 1:
        ahead = minimum_filter1d(need, size=L, mode="nearest", origin=-(L // 2))  # [i, i+L-1]
        csum = np.concatenate([[0.0], np.cumsum(ahead)])
        idx = np.arange(n_samples)
        lo = np.maximum(0, idx - L + 1)
        gain = (csum[idx + 1] - csum[lo]) / (idx + 1 - lo)
    else:
        gain = need

    release_coeff = math.exp(-1.0 / (max(1e-4, release_ms * 0.001) * sr))
    g_smooth = 1.0 - _peak_hold_release(1.0 - gain, release_coeff)

    min_gain = float(np.min(g_smooth))
    max_gr_db = 20.0 * math.log10(max(min_gain, 1e-12)) if min_gain < 1.0 else 0.0

    y = (x * g_smooth[:, None]).astype(np.float32)
    return y, {"max_gain_reduction_db": float(max_gr_db),
               "ceiling_dbtp": float(ceiling_dbtp)}
