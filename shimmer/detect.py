"""
detect.py — Evidence-based preset recommendation (Analyze / auto-detect).

Why this module exists
----------------------
The previous scorer rated every artifact preset from a handful of
spectral heuristics whose gates (flatness > 0.25, "ratio above 1.3x its
own median", ...) pass on essentially any music.  On a corpus of real
Suno renders the same four presence-band presets won every time, and
cleaning a clip with its own "best match" did not move that preset's
score at all: the features measured the music, not the artifact.

This module replaces it with two stages.  Neither stage changes the
sound path; they only *measure* what the existing pipeline does and
feed the existing preset-strength input.

1. Evidence scan (open loop, whole file, cheap)
   Calibrated measurements in dB or well-defined fractions: steady
   narrow tones and their duty cycle, sub-band amplitude flicker against
   the body, comb spacing, sibilance bursts, top-end tilt, presence-band
   excess, decay-tail residue.  These give each preset a *prior*, a
   human-readable evidence phrase, the per-second intensity timeline,
   and the choice of the hottest window for stage 2.

2. Verification (closed loop, hottest window)
   Every artifact preset is run through the real pipeline
   (crossover -> M/S -> engine -> recombine; no mastering, no EQ) on that
   window.  The processed clip is compared with the input by the
   BS.1387 hearing model (perceptual.py): how much audible content went
   (`missing`, sones) and how far the tone tilted (`lin_dist`).  A
   preset scores by *net audible benefit*: audible removal is credited
   in proportion to the evidence that its artifact is present and
   debited in proportion to the evidence that it is not, tilt damage is
   always a cost, and when the scan found steady tones the share of
   their excess removed counts as benefit directly.  Removal the
   evidence does not support is music, and a preset cannot score by
   removing more of it.  The top picks are re-run across a strength
   grid to find the gentlest strength that reaches the best score, and
   the runner-ups are tried on the winner's output to see whether a
   second pass with a different preset is worthwhile.

   The previous scorer rated removal by `purity`, the share of removed
   energy that fell outside a mask of transients and narrow partials.
   On finished masters that mask covers 84-95 % of all energy above
   2 kHz, so purity sat near 1.0 for any preset confined to the sustained
   top end and correlated -0.003 with measured audible damage
   (docs/BRIGHTNESS-ASSESSMENT.md 2.5). It recommended cleaning finished
   commercial masters at 80 % confidence. It is gone.

Public entry points: `suggest(path, ...)` and `suggest_array(x, sr, ...)`.
`probe.suggest_preset` is a thin wrapper kept for back-compat.
"""

from __future__ import annotations

from . import _winfix  # noqa: F401  # must precede scipy import on Windows

import math
import time
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import signal
from scipy.ndimage import median_filter, uniform_filter1d

from .audio_io import load_audio
from .params import Params, apply_preset_strength
from .budget import MAX_BUDGET_SONES as _MAX_BUDGET_SONES
from .budget import MAX_LIN_DIST as _MAX_LIN_DIST
from .perceptual import measure_damage
from .presets import VISIBLE_PRESETS, get_preset, label_for

_EPS = 1e-12
_DB = 10.0 / math.log(10.0)          # power (natural log) -> dB

# Presets that fix an artifact *shape* and therefore compete in the
# ranking.  The two tonal-balance presets are static EQ fixes; they are
# surfaced through `notes` when the spectral balance calls for them.
NON_ARTIFACT_PRESETS = ("generic", "muddy_boxy", "dark_mix_rescue")

# Verification constants.
VERIFY_N_FFT = 4096
VERIFY_HOP = 1024
PROTECT_BELOW_HZ = 2000.0        # body: never counts as artifact removal
PARTIAL_MAX_HZ = 10000.0         # sustained narrow lines above this are synthetic
PARTIAL_MIN_FRAMES = 4           # ~85 ms at 48 kHz / hop 1024
TRANSIENT_FLUX_DB = 6.0
TRANSIENT_PRE_FRAMES = 1
TRANSIENT_POST_FRAMES = 3        # ~85 ms, the engine's full-protection hold
EDGE_TRIM_S = 0.15               # ignore crossover / STFT edge frames
BODY_WEIGHT = 3.0                # body removal counts triple as collateral
COLLATERAL_LAMBDA = 2.0          # informational net = artifact - lambda * collateral

# Verified score = net audible benefit, 0..1 (see `verified_score`).
#
#   benefit  (2p - 1) x M, where M ramps the audible content removed
#            (`missing`, sones) to 1 at MISSING_FULL_SONES and p is the
#            evidence prior for the preset's artifact. With no evidence the
#            removal is all music and the term goes negative; with full
#            evidence it is all credit.
#   tone     share of measured steady-tone excess removed, carrying up to
#            TONE_WEIGHT_MAX of the benefit when the scan found tones.
#   cost     linear (tilt) distortion `lin_dist`, ramped to 1 at
#            LIN_DIST_FULL. Broadband tilt is never an artifact.
#
# The two full-scale points are the budget's own ceilings (budget.py):
# MAX_BUDGET_SONES is "never remove more audible content than this however
# hashed the track", MAX_LIN_DIST the same for tilt. Both were set from four
# songs judged by one listener and are the anchors used everywhere, not a
# second calibration. The prior is a 0..1 plausibility, not a probability;
# it was ramped on Suno renders only (`priors_from_evidence`), so on clean
# music it can read high for presence-band presets. The cost term is what
# stops those from firing on a finished master.
MISSING_FULL_SONES = _MAX_BUDGET_SONES
LIN_DIST_FULL = _MAX_LIN_DIST
TONE_MIN_EXCESS_DB = 6.0         # steady tones this strong take part in scoring
TONE_WEIGHT_MAX = 0.4            # share of the benefit given to tone kill
MIN_ACTIONABLE_SCORE = 0.05
MIN_ACTIONABLE_ARTIFACT_DB = -48.0

STRENGTH_GRID = (0.5, 1.0, 1.5, 2.0)
STRENGTH_MIN = 0.25
STRENGTH_MAX = 2.0
STRENGTH_STEP = 0.05
STRENGTH_TOLERANCE = 0.04        # gentlest strength within this score of the best wins
STRENGTH_COLLATERAL_GUARD_DB = 3.0

FOLLOW_UP_MIN_RATIO_DB = -4.0    # second pass must remove >= 40% of the winner's residue
FOLLOW_UP_MIN_ARTIFACT_DB = -26.0
# ...and must clear MIN_ACTIONABLE_SCORE on its own, measured against the
# winner's output.


def artifact_preset_names() -> List[str]:
    return [n for n in VISIBLE_PRESETS if n not in NON_ARTIFACT_PRESETS]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _ramp(v: float, lo: float, hi: float) -> float:
    """Linear 0..1 ramp of `v` between `lo` and `hi`."""
    if hi <= lo:
        return 0.0
    return float(np.clip((float(v) - lo) / (hi - lo), 0.0, 1.0))


def _bins(f: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.where((f >= lo) & (f < hi))[0]


def _stft_power(x: np.ndarray, sr: int, n_fft: int, hop: int
                ) -> Tuple[np.ndarray, np.ndarray]:
    """(freqs, power[bins, frames]) summed over channels."""
    x2 = x if x.ndim > 1 else x[:, None]
    P: Optional[np.ndarray] = None
    f = None
    for c in range(x2.shape[1]):
        f, _, Z = signal.stft(
            np.ascontiguousarray(x2[:, c], dtype=np.float32), fs=sr,
            window="hann", nperseg=n_fft, noverlap=n_fft - hop, nfft=n_fft,
            boundary=None, padded=False)
        p = (np.abs(Z) ** 2).astype(np.float32)
        P = p if P is None else P + p
    assert f is not None and P is not None
    return f, P


def _level_db(P: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Per-frame mean power in the band, in dB."""
    if idx.size == 0:
        return np.full(P.shape[1], -120.0, dtype=np.float64)
    return _DB * np.log(P[idx, :].astype(np.float64).mean(axis=0) + _EPS)


def _flatness(P: np.ndarray, idx: np.ndarray, frames: np.ndarray) -> float:
    """Median over `frames` of spectral flatness (geo/arith of power)."""
    if idx.size < 4 or not np.any(frames):
        return 0.0
    B = P[idx][:, frames].astype(np.float64) + _EPS
    geo = np.exp(np.mean(np.log(B), axis=0))
    ari = np.mean(B, axis=0)
    return float(np.median(geo / ari))


def _active_frames(full_db: np.ndarray, floor_db: float = 50.0) -> np.ndarray:
    """Frames that are not digital silence / deep fades."""
    if full_db.size == 0:
        return np.zeros(0, dtype=bool)
    act = full_db > (float(full_db.max()) - floor_db)
    if act.sum() < 8:
        act = np.ones_like(act, dtype=bool)
    return act


def _sustained_runs(mask: np.ndarray, k: int) -> np.ndarray:
    """Cells that belong to a run of >= k consecutive True values along
    axis 1 (time)."""
    n = mask.shape[1]
    out = np.zeros_like(mask, dtype=bool)
    if n < k or k <= 0:
        return out
    m = mask.astype(np.int32)
    cs = np.concatenate(
        [np.zeros((m.shape[0], 1), dtype=np.int32), np.cumsum(m, axis=1)], axis=1)
    win = cs[:, k:] - cs[:, :-k]           # win[:, i] = sum(mask[:, i:i+k])
    start = win >= k                        # a run of k starts at i
    for j in range(k):
        out[:, j:j + start.shape[1]] |= start
    return out


def _transient_frames(full_db: np.ndarray) -> np.ndarray:
    flux = np.diff(full_db, prepend=full_db[:1])
    t = flux > TRANSIENT_FLUX_DB
    if not np.any(t):
        return t
    out = t.copy()
    n = t.size
    for i in np.where(t)[0]:
        out[max(0, i - TRANSIENT_PRE_FRAMES):min(n, i + TRANSIENT_POST_FRAMES + 1)] = True
    return out


# ---------------------------------------------------------------------------
# Stage 1a: whole-file coarse scan (tones, spectral balance, timeline)
# ---------------------------------------------------------------------------

@dataclass
class Tone:
    hz: float
    excess_db: float          # 25th-percentile excess over time (persistence)
    duty: float
    kind: str = "line"        # "line" (isolated) | "comb" (evenly spaced tooth)
    excess_hi_db: float = 0.0  # 90th-percentile excess: how strong it gets


@dataclass
class Evidence:
    # steady narrow tones (whole file)
    tones: List[Tone]
    tone_4_8: Tone
    tone_8_12: Tone
    tone_9_15: Tone
    tone_12_20: Tone
    # spectral balance (whole file, active frames, median)
    top_tilt_db: float      # 12-18 kHz vs 4-12 kHz
    presence_db: float      # 3-8 kHz vs 1-3 kHz
    upper_db: float         # 8-18 kHz vs 1-3 kHz
    umid_db: float          # 4-12 kHz vs 1-3 kHz
    mud_db: float           # 200-500 Hz vs 500-2000 Hz
    dull_db: float          # 4-14 kHz vs 300-3000 Hz
    # window features (hot window, hop 1024)
    flicker_hi_db: float
    flicker_body_db: float
    flicker_excess_db: float
    comb: float
    sib_burst: float
    period_hi: float
    period_body: float
    period_excess: float
    tail_contrast: float
    ring_4_10: float
    echo_corr: float
    flat_3_8: float
    flat_4_12: float
    flat_8_18: float
    # whole-file: where the render's top end stops (0 = full bandwidth)
    cutoff_hz: float = 0.0
    # whole-file: impulsive runs per second on the high band
    click_rate: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if k == "tones":
                d[k] = [{"hz": round(t.hz, 1), "excess_db": round(t.excess_db, 2),
                         "duty": round(t.duty, 3), "kind": t.kind,
                         "excess_hi_db": round(t.excess_hi_db, 2)} for t in v]
            elif isinstance(v, Tone):
                d[k] = {"hz": round(v.hz, 1), "excess_db": round(v.excess_db, 2),
                        "duty": round(v.duty, 3)}
            else:
                d[k] = round(float(v), 4)
        return d


_NO_TONE = Tone(0.0, 0.0, 0.0)


def _coarse_stft(x: np.ndarray, sr: int, n_fft: int, hop: int,
                 chunk_s: float = 60.0
                 ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Chunked non-overlapping STFT of the whole (capped) file, power
    summed over channels (a mono mix would cancel side-only artifacts,
    and most AI shimmer lives in the sides).
    Returns (freqs, power[bins, frames], frame_time_s)."""
    parts: List[np.ndarray] = []
    times: List[np.ndarray] = []
    f = None
    step = int(chunk_s * sr)
    for s0 in range(0, int(x.shape[0]), step):
        seg = x[s0:s0 + step]
        if seg.shape[0] < n_fft:
            break
        f, P = _stft_power(seg, sr, n_fft, hop)
        parts.append(P)
        times.append((s0 + np.arange(P.shape[1]) * hop + n_fft / 2.0) / float(sr))
    if not parts or f is None:
        raise ValueError("Clip too short to analyze")
    return f, np.concatenate(parts, axis=1), np.concatenate(times)


def _tone_map(S: np.ndarray, active: np.ndarray
              ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """(Sa, tm): active-frame spectrogram and the per-bin 25th-percentile
    excess over a 51-bin frequency-median envelope. A line that holds
    its excess at the 25th percentile is present at least three quarters
    of the time, which musical partials (they come and go) never are."""
    Sa = S[:, active] if active.sum() >= 8 else S
    if Sa.shape[1] < 4:
        return None, None
    q25 = np.percentile(Sa, 25, axis=1)
    env = median_filter(q25, size=51, mode="nearest")
    return Sa, q25 - env


def _duty(Sa: np.ndarray, b: int) -> float:
    lo, hi = max(0, b - 25), min(Sa.shape[0], b + 26)
    local_env = np.median(Sa[lo:hi, :], axis=0)
    return float(np.mean((Sa[b, :] - local_env) > 6.0))


def _excess_hi(Sa: np.ndarray, b: int) -> float:
    """90th-percentile excess of bin b over its per-frame local envelope:
    how far the line stands out in the loud parts of the song."""
    lo, hi = max(0, b - 25), min(Sa.shape[0], b + 26)
    local_env = np.median(Sa[lo:hi, :], axis=0)
    return float(np.percentile(Sa[b, :] - local_env, 90))


def _refine_hz(tm: np.ndarray, f: np.ndarray, b: int) -> float:
    """Sub-bin frequency by parabolic interpolation on the excess map."""
    if b <= 0 or b >= tm.size - 1:
        return float(f[b])
    y0, y1, y2 = float(tm[b - 1]), float(tm[b]), float(tm[b + 1])
    den = y0 - 2.0 * y1 + y2
    if abs(den) < 1e-9:
        return float(f[b])
    delta = 0.5 * (y0 - y2) / den
    delta = float(np.clip(delta, -0.5, 0.5))
    return float(f[b] + delta * (f[1] - f[0]))


def _steady_tones(S: np.ndarray, f: np.ndarray, active: np.ndarray,
                  f_min: float = 3500.0, max_peaks: int = 8) -> List[Tone]:
    """Narrow lines that sit above their spectral surroundings for most
    of the track, as the engine's narrow-tone stage would see them."""
    Sa, tm = _tone_map(S, active)
    if Sa is None:
        return []
    cand = np.where((tm > 3.0) & (f >= f_min))[0]
    peaks: List[int] = []
    for b in cand:
        lo, hi = max(0, b - 3), min(tm.size, b + 4)
        if tm[b] >= tm[lo:hi].max():
            peaks.append(int(b))
    peaks.sort(key=lambda b: -tm[b])
    picked: List[int] = []
    for b in peaks:
        if all(abs(b - q) > 5 for q in picked):
            picked.append(b)
        if len(picked) >= max_peaks:
            break
    return [Tone(_refine_hz(tm, f, b), float(tm[b]), _duty(Sa, b),
                 excess_hi_db=_excess_hi(Sa, b)) for b in picked]


def _comb_lines(S: np.ndarray, f: np.ndarray, active: np.ndarray,
                lo_hz: float = 3000.0, hi_hz: float = 16000.0,
                min_spacing_hz: float = 40.0, max_spacing_hz: float = 700.0,
                min_score: float = 0.35) -> List[Tone]:
    """Evenly spaced teeth in the whole-file residual (the deconvolution
    grid). The dominant spacing comes from the frequency-axis
    autocorrelation of the persistent excess; teeth are the persistent
    peaks sitting on multiples of that spacing."""
    Sa, tm = _tone_map(S, active)
    if Sa is None:
        return []
    idx = np.where((f >= lo_hz) & (f <= hi_hz))[0]
    if idx.size < 64:
        return []
    v = np.maximum(tm[idx], 0.0)
    v = v - v.mean()
    norm = float(np.sum(v * v)) + _EPS
    bin_hz = float(f[1] - f[0])
    min_lag = max(2, int(round(min_spacing_hz / bin_hz)))
    max_lag = min(idx.size - 2, int(round(max_spacing_hz / bin_hz)))
    best, best_lag = 0.0, 0
    for lag in range(min_lag, max_lag + 1):
        s = float(np.sum(v[:-lag] * v[lag:]) / norm)
        if s > best:
            best, best_lag = s, lag
    if best < min_score or best_lag == 0:
        return []
    # A tooth is a persistent peak with another persistent peak one
    # spacing away (either side). Testing neighbours instead of multiples
    # of the spacing from 0 Hz keeps a 0.5 % spacing error from
    # accumulating across the comb.
    peaks: List[int] = []
    for b in idx:
        if tm[b] <= 3.0:
            continue
        lo, hi = max(0, b - 2), min(tm.size, b + 3)
        if tm[b] >= tm[lo:hi].max():
            peaks.append(int(b))
    if len(peaks) < 3:
        return []
    peak_set = np.array(peaks)
    tol = 1.5
    out: List[Tone] = []
    for b in peaks:
        d = np.abs(np.abs(peak_set - b) - best_lag)
        if np.any((d <= tol) & (peak_set != b)):
            out.append(Tone(_refine_hz(tm, f, b), float(tm[b]), _duty(Sa, b),
                            kind="comb", excess_hi_db=_excess_hi(Sa, b)))
    return out if len(out) >= 3 else []


def _fixed_lines(S: np.ndarray, f: np.ndarray, active: np.ndarray,
                 f_min: float = 2000.0, max_peaks: int = 24) -> List[Tone]:
    """Isolated steady lines plus comb teeth, deduplicated, strongest first."""
    lines = _steady_tones(S, f, active, f_min=f_min, max_peaks=max_peaks)
    bin_hz = float(f[1] - f[0]) if f.size > 1 else 1.0
    for t in _comb_lines(S, f, active):
        if t.hz < f_min:
            continue
        near = [L for L in lines if abs(L.hz - t.hz) <= 2.0 * bin_hz]
        if near:
            near[0].kind = "comb"
        else:
            lines.append(t)
    lines.sort(key=lambda t: -t.excess_db)
    return lines[:max_peaks]


def scan_fixed_lines(x: np.ndarray, sr: int, max_scan_s: float = 300.0
                     ) -> List[Dict[str, Any]]:
    """Whole-file scan for the generator's fixed tonal lines and comb
    teeth (repair.plan_from_lines turns these into static notches).
    Power is summed over channels so side-only lines cannot cancel."""
    x2 = np.asarray(x, dtype=np.float32)
    if x2.ndim == 1:
        x2 = x2[:, None]
    n_scan = min(x2.shape[0], int(max_scan_s * sr))
    if n_scan < VERIFY_N_FFT:
        return []
    f, P, _ = _coarse_stft(x2[:n_scan], sr, VERIFY_N_FFT, VERIFY_N_FFT)
    S = _DB * np.log(P.astype(np.float64) + _EPS)
    full_db = _DB * np.log(P.sum(axis=0).astype(np.float64) + _EPS)
    active = _active_frames(full_db)
    return [{"hz": round(t.hz, 1), "excess_db": round(t.excess_db, 2),
             "duty": round(t.duty, 3), "kind": t.kind,
             "excess_hi_db": round(t.excess_hi_db, 2)}
            for t in _fixed_lines(S, f, active)]


def _strongest_tone(tones: Sequence[Tone], lo: float, hi: float) -> Tone:
    best = _NO_TONE
    for t in tones:
        if lo <= t.hz < hi and t.excess_db > best.excess_db:
            best = t
    return best


def _timeline_and_window(hot: np.ndarray, active: np.ndarray,
                         t: np.ndarray, duration_s: float,
                         window_s: float) -> Tuple[List[float], float]:
    """Per-second top-end intensity (0..1) and the start of the hottest
    fully-active window of `window_s` seconds."""
    n_sec = max(1, int(math.ceil(duration_s)))
    sec = np.clip(np.floor(t).astype(int), 0, n_sec - 1)
    w = active.astype(np.float64)
    sums = np.bincount(sec, weights=hot * w, minlength=n_sec)
    cnts = np.bincount(sec, weights=w, minlength=n_sec)
    tot = np.bincount(sec, minlength=n_sec)
    with np.errstate(invalid="ignore", divide="ignore"):
        per_sec = np.where(cnts > 0, sums / np.maximum(cnts, 1e-9), np.nan)
    finite = per_sec[np.isfinite(per_sec)]
    if finite.size == 0:
        return [0.0] * n_sec, 0.0
    lo = float(np.percentile(finite, 20))
    hi = float(np.percentile(finite, 95))
    if hi - lo < 1.0:
        hi = lo + 1.0
    intensity = np.clip((per_sec - lo) / (hi - lo), 0.0, 1.0)
    intensity = np.where(np.isfinite(intensity), intensity, 0.0)

    W = max(1, int(round(window_s)))
    sec_active = (cnts >= 0.5 * np.maximum(tot, 1)) & (tot > 0)
    best_start, best_val = None, -1.0
    for s0 in range(0, max(1, n_sec - W + 1)):
        seg = intensity[s0:s0 + W]
        if seg.size < W or not np.all(sec_active[s0:s0 + W]):
            continue
        v = float(seg.mean())
        if v > best_val:
            best_val, best_start = v, s0
    if best_start is None:
        best_start = max(0, int((n_sec - W) // 2))
    return [round(float(v), 3) for v in intensity], float(best_start)


# ---------------------------------------------------------------------------
# Stage 1b: hot-window features (hop 1024)
# ---------------------------------------------------------------------------

FLICKER_N_FFT = 1024
FLICKER_HOP = 256


def _flicker(x_win: np.ndarray, sr: int) -> Tuple[float, float, float]:
    """Sub-band AM depth in the 4.5-12 kHz hash band vs. the 1-3 kHz
    body, on steady frames.

    Uses its own short STFT (1024/256, ~23 ms frames at 44.1 kHz) because
    Suno hash flickers at 10-50 Hz, which averages out inside the 93 ms
    frames used everywhere else.  Spread is the scaled median absolute
    deviation of the detrended envelope (dB), so sparse hits that slip
    past the transient gate do not dominate; hash flicker is continuous
    and survives the median."""
    if x_win.shape[0] < FLICKER_N_FFT * 4:
        return 0.0, 0.0, 0.0
    f, P = _stft_power(x_win, sr, FLICKER_N_FFT, FLICKER_HOP)
    full_db = _DB * np.log(P.sum(axis=0).astype(np.float64) + _EPS)
    active = _active_frames(full_db)
    flux = np.diff(full_db, prepend=full_db[:1])
    hold = max(1, int(round(0.085 * sr / FLICKER_HOP)))
    transient = np.zeros_like(active)
    for i in np.where(flux > TRANSIENT_FLUX_DB)[0]:
        transient[max(0, i - 1):i + hold + 1] = True
    frames = active & ~transient
    if frames.sum() < 16:
        frames = active
    w = max(3, int(round(0.25 * sr / FLICKER_HOP)))

    def am(lo: float, hi: float, nb: int) -> float:
        edges = np.linspace(lo, hi, nb + 1)
        vals = []
        for k in range(nb):
            idx = _bins(f, edges[k], edges[k + 1])
            if idx.size < 2:
                continue
            e = _level_db(P, idx)
            trend = uniform_filter1d(e, size=w, mode="nearest")
            d = (e - trend)[frames]
            if d.size >= 16:
                mad = float(np.median(np.abs(d - np.median(d))))
                vals.append(1.4826 * mad)
        return float(np.median(vals)) if vals else 0.0

    hi = am(4500.0, 12000.0, 6)
    body = am(1000.0, 3000.0, 2)
    return hi, body, hi - body


def _comb_score(S: np.ndarray, f: np.ndarray,
                lo_hz: float = 3000.0, hi_hz: float = 14000.0,
                min_spacing_hz: float = 80.0, max_spacing_hz: float = 600.0
                ) -> float:
    """Mean frequency-axis autocorrelation peak of the narrow residual in
    the deconv-grid spacing range (0..1)."""
    idx = _bins(f, lo_hz, hi_hz)
    if idx.size < 32:
        return 0.0
    L = S[idx, :]
    R = np.maximum(L - median_filter(L, size=(7, 1), mode="nearest"), 0.0)
    bin_hz = float(f[1] - f[0])
    min_lag = max(2, int(round(min_spacing_hz / bin_hz)))
    max_lag = max(min_lag + 1, int(round(max_spacing_hz / bin_hz)))
    n = R.shape[0]
    max_lag = min(max_lag, n - 1)
    R = R - R.mean(axis=0, keepdims=True)
    norm = np.sum(R * R, axis=0) + _EPS
    best = np.zeros(R.shape[1], dtype=np.float64)
    for lag in range(min_lag, max_lag + 1):
        s = np.sum(R[:n - lag, :] * R[lag:, :], axis=0) / norm
        best = np.maximum(best, s)
    return float(np.clip(np.mean(best), 0.0, 1.0))


def _sibilance_burst(M: np.ndarray, f: np.ndarray, active: np.ndarray) -> float:
    """Fraction of vocal-like frames whose 6-10 kHz magnitude spikes far
    above its median relative to the 1-4 kHz mids."""
    sib = _bins(f, 6000.0, 10000.0)
    mid = _bins(f, 1000.0, 4000.0)
    if sib.size < 4 or mid.size < 4 or not np.any(active):
        return 0.0
    e_sib = M[sib, :].sum(axis=0)
    e_mid = M[mid, :].sum(axis=0)
    ratio = e_sib / (e_mid + _EPS)
    med_ratio = float(np.median(ratio[active]))
    if med_ratio <= 0.0:
        return 0.0
    mid_active = e_mid > (0.3 * float(np.median(e_mid[active])) + _EPS)
    bursts = (ratio > 1.8 * med_ratio) & mid_active & active
    return float(np.sum(bursts) / max(1, np.sum(active)))


def _periodicity(M: np.ndarray, f: np.ndarray, lo: float, hi: float,
                 sr: int, hop: int, lag_ms=(30.0, 200.0)) -> float:
    idx = _bins(f, lo, hi)
    if idx.size < 4:
        return 0.0
    e = M[idx, :].sum(axis=0).astype(np.float64)
    e = e - e.mean()
    norm = float(np.sum(e * e)) + _EPS
    dt = hop / float(sr)
    min_lag = max(1, int(round(lag_ms[0] / 1000.0 / dt)))
    max_lag = max(min_lag + 1, int(round(lag_ms[1] / 1000.0 / dt)))
    n = e.shape[0]
    max_lag = min(max_lag, n - 1)
    if max_lag <= min_lag:
        return 0.0
    best = 0.0
    for lag in range(min_lag, max_lag + 1):
        s = float(np.sum(e[:n - lag] * e[lag:]) / norm)
        best = max(best, s)
    return float(np.clip(best, 0.0, 1.0))


def _tail_contrast(R: np.ndarray, f: np.ndarray, full_db: np.ndarray,
                   active: np.ndarray) -> float:
    """Narrow-residue density in 8-16 kHz on decaying frames minus the
    same on rising frames.  Positive = residue that lingers in tails."""
    idx = _bins(f, 8000.0, 16000.0)
    if idx.size < 8:
        return 0.0
    flux = np.diff(full_db, prepend=full_db[:1])
    decay = (flux <= 0.0) & active
    rise = (flux > 0.0) & active
    if decay.sum() < 4 or rise.sum() < 4:
        return 0.0
    hot = R[idx, :] > 6.0
    return float(hot[:, decay].mean() - hot[:, rise].mean())


def _ring_fraction(R: np.ndarray, f: np.ndarray, active: np.ndarray) -> float:
    """Fraction of 4-10 kHz bins that peak intermittently (10-60% of
    active frames): the metallic 'ring' texture."""
    idx = _bins(f, 4000.0, 10000.0)
    if idx.size < 8 or not np.any(active):
        return 0.0
    frac = (R[idx][:, active] > 6.0).mean(axis=1)
    return float(np.mean((frac > 0.10) & (frac < 0.60)))


def _echo_corr(P: np.ndarray, f: np.ndarray, active: np.ndarray) -> float:
    pres = _bins(f, 3000.0, 10000.0)
    body = _bins(f, 100.0, 3000.0)
    if pres.size < 4 or body.size < 4 or active.sum() < 8:
        return 0.0
    a = P[pres][:, active].mean(axis=0).astype(np.float64)
    b = P[body][:, active].mean(axis=0).astype(np.float64)
    a -= a.mean()
    b -= b.mean()
    den = float(np.sqrt(np.sum(a * a) * np.sum(b * b)))
    if den < _EPS:
        return 0.0
    return float(np.sum(a * b) / den)


def _window_features(x_win: np.ndarray, sr: int) -> Dict[str, float]:
    f, P = _stft_power(x_win, sr, VERIFY_N_FFT, VERIFY_HOP)
    S = _DB * np.log(P.astype(np.float64) + _EPS)
    M = np.sqrt(P.astype(np.float64))
    full_db = _DB * np.log(P.sum(axis=0).astype(np.float64) + _EPS)
    active = _active_frames(full_db)
    transient = _transient_frames(full_db)
    steady = active & ~transient
    if steady.sum() < 8:
        steady = active

    R = S - median_filter(S, size=(31, 1), mode="nearest")
    fl_hi, fl_body, fl_ex = _flicker(np.asarray(x_win, dtype=np.float32), sr)
    per_hi = _periodicity(M, f, 8000.0, 16000.0, sr, VERIFY_HOP)
    per_body = _periodicity(M, f, 100.0, 3000.0, sr, VERIFY_HOP)
    return {
        "flicker_hi_db": fl_hi,
        "flicker_body_db": fl_body,
        "flicker_excess_db": fl_ex,
        "comb": _comb_score(S, f),
        "sib_burst": _sibilance_burst(M, f, active),
        "period_hi": per_hi,
        "period_body": per_body,
        "period_excess": max(0.0, per_hi - per_body),
        "tail_contrast": _tail_contrast(R, f, full_db, active),
        "ring_4_10": _ring_fraction(R, f, active),
        "echo_corr": _echo_corr(P, f, active),
        "flat_3_8": _flatness(P, _bins(f, 3000.0, 8000.0), active),
        "flat_4_12": _flatness(P, _bins(f, 4000.0, 12000.0), active),
        "flat_8_18": _flatness(P, _bins(f, 8000.0, 18000.0), active),
    }


# ---------------------------------------------------------------------------
# Stage 1: evidence scan
# ---------------------------------------------------------------------------

@dataclass
class Scan:
    evidence: Evidence
    timeline: List[float]
    window_start_s: float
    duration_s: float
    scanned_s: float


def evidence_scan(x: np.ndarray, sr: int, window_s: float = 5.0,
                  max_scan_s: float = 300.0) -> Scan:
    x2 = np.asarray(x, dtype=np.float32)
    if x2.ndim == 1:
        x2 = x2[:, None]
    duration_s = float(x2.shape[0]) / float(sr)
    n_scan = min(x2.shape[0], int(max_scan_s * sr))
    scan = x2[:n_scan]
    if scan.shape[0] < VERIFY_N_FFT:
        raise ValueError(
            f"Clip too short ({scan.shape[0]} samples) for n_fft={VERIFY_N_FFT}")

    f, P, t = _coarse_stft(scan, sr, VERIFY_N_FFT, VERIFY_N_FFT)
    S = _DB * np.log(P.astype(np.float64) + _EPS)
    full_db = _DB * np.log(P.sum(axis=0).astype(np.float64) + _EPS)
    active = _active_frames(full_db)

    body = _level_db(P, _bins(f, 200.0, 2500.0))
    hi = _level_db(P, _bins(f, 3000.0, 16000.0))
    hot = hi - body
    timeline, win_start = _timeline_and_window(
        hot, active, t, min(duration_s, max_scan_s), window_s)

    def bal(lo1, hi1, lo2, hi2) -> float:
        a = _level_db(P, _bins(f, lo1, hi1))[active]
        b = _level_db(P, _bins(f, lo2, hi2))[active]
        return float(np.median(a - b)) if a.size else 0.0

    tones = _fixed_lines(S, f, active)

    # Whole-file: bandwidth cutoff and impulsive-noise rate.
    from .repair import click_rate, estimate_cutoff_hz
    cut = estimate_cutoff_hz(x2, sr)
    clicks = click_rate(x2[:n_scan], sr)

    # Hot-window features at fine hop.
    w0 = int(win_start * sr)
    w1 = min(x2.shape[0], w0 + int(window_s * sr))
    if w1 - w0 < VERIFY_N_FFT * 2:
        w0, w1 = 0, min(x2.shape[0], int(window_s * sr))
    wf = _window_features(x2[w0:w1], sr)

    ev = Evidence(
        tones=tones,
        tone_4_8=_strongest_tone(tones, 4000.0, 8000.0),
        tone_8_12=_strongest_tone(tones, 8000.0, 12000.0),
        tone_9_15=_strongest_tone(tones, 9000.0, 15000.0),
        tone_12_20=_strongest_tone(tones, 12000.0, 20000.0),
        top_tilt_db=bal(12000.0, 18000.0, 4000.0, 12000.0),
        presence_db=bal(3000.0, 8000.0, 1000.0, 3000.0),
        upper_db=bal(8000.0, 18000.0, 1000.0, 3000.0),
        umid_db=bal(4000.0, 12000.0, 1000.0, 3000.0),
        mud_db=bal(200.0, 500.0, 500.0, 2000.0),
        dull_db=bal(4000.0, 14000.0, 300.0, 3000.0),
        cutoff_hz=float(cut.get("cutoff_hz") or 0.0),
        click_rate=float(clicks),
        **wf,
    )
    return Scan(evidence=ev, timeline=timeline, window_start_s=float(w0) / sr,
                duration_s=duration_s, scanned_s=float(n_scan) / sr)


# ---------------------------------------------------------------------------
# Priors and evidence phrases
# ---------------------------------------------------------------------------

def priors_from_evidence(ev: Evidence) -> Dict[str, float]:
    """0..1 plausibility per artifact preset from the evidence scan.

    A prior gates how much of a trial clean's audible removal counts as
    benefit rather than cost (see `verified_score`), so it has to be able
    to say "nothing is wrong".  The ramp edges below were derived on
    2026-09-08 by one rule (`scripts/prior_calibration.py`):

      lo  the 84th percentile of the feature on 9 finished masters
          (4 service masters + reference "Hey" + 4 more service masters
          that carry hash, excluded for the flicker feature only), so
          run-of-the-mill clean music reads 0;
      hi  the median reading on clean hosts with the matching modelled
          artifact injected at 2.0 sones (shimmer/artifacts.py; "plainly
          there"), so a clearly present artifact reads 1.  Features with no
          model (ring, periodicity, tail contrast, top tilt, upper level,
          click rate) keep their old ramp width above the new lo.

    The tone bands are the exception: the whole-file scan finds no line on
    most masters (clean reads exactly 0) and the injected model is a pure
    sine (46-64 dB excess), so neither end of the rule is informative there.
    They keep their old edges, with lo raised to the clean 84th percentile
    where that is higher.  Fixed lines are the static repair's job anyway.

    Before this the edges were the ~20th and ~85th percentiles of 26 Suno
    renders with no clean control, and on finished masters the presence-band
    presets read 0.7-1.0.  Nine masters is a small clean sample; the 84th
    percentile of nine is the second-highest file.  Widen it before
    tightening any edge.
    """
    t8, t9 = ev.tone_8_12, ev.tone_9_15
    t_hi = ev.tone_9_15 if ev.tone_9_15.excess_db >= ev.tone_12_20.excess_db else ev.tone_12_20
    pr: Dict[str, float] = {}
    pr["cymbal_sheen"] = _ramp(t8.excess_db, 3.0, 12.0) * (1.0 if t8.duty >= 0.5 else 0.5)
    pr["laser_whistle"] = _ramp(t_hi.excess_db, 3.5, 12.0) * (1.0 if t_hi.duty < 0.85 else 0.7)
    pr["air_brittle"] = max(_ramp(ev.top_tilt_db, -10.2, -1.2),
                            0.8 * _ramp(ev.tone_12_20.excess_db, 6.0, 12.0))
    # Sibilance Rattle also carries the de-clicker, so crackle counts here.
    # Dense hi-hats register a few blips a second too, so the ramp starts
    # high.
    pr["sibilance_rattle"] = max(_ramp(ev.sib_burst, 0.12, 0.23),
                                 0.8 * _ramp(ev.click_rate, 10.0, 40.0))
    pr["cymbal_chatter"] = (0.6 * _ramp(ev.period_excess, 0.10, 0.35)
                            + 0.4 * _ramp(ev.comb, 0.14, 0.72))
    pr["broadband_fizz"] = (0.5 * _ramp(ev.flat_8_18, 0.21, 0.76)
                            + 0.5 * _ramp(ev.upper_db, -10.3, 3.7))
    pr["checkerboard_grid"] = _ramp(ev.comb, 0.14, 0.72)
    pr["reverb_flutter"] = _ramp(ev.tail_contrast, 0.01, 0.04)
    pr["suno_hash"] = _ramp(ev.flicker_excess_db, 0.32, 2.30)
    pr["vocal_glaze"] = _ramp(ev.presence_db, -2.6, 9.3) * _ramp(ev.flat_3_8, 0.53, 0.76)
    pr["vocal_glaze_plus"] = math.sqrt(
        pr["vocal_glaze"] * max(pr["suno_hash"], pr["broadband_fizz"]))
    pr["echo_sheen"] = _ramp(ev.echo_corr, 0.17, 0.67) * _ramp(ev.flat_3_8, 0.53, 0.76)
    pr["presence_haze"] = _ramp(ev.presence_db, -2.6, 9.3) * _ramp(ev.flat_3_8, 0.53, 0.76)
    pr["phantom_cymbal"] = _ramp(ev.presence_db, -2.6, 9.3) * _ramp(ev.ring_4_10, 0.27, 0.57)
    pr["harsh_veil"] = _ramp(ev.umid_db, -4.6, 8.2) * _ramp(ev.flat_4_12, 0.51, 0.60)
    vals = sorted(pr.values())
    n_strong = sum(1 for v in pr.values() if v > 0.4)
    pr["deep_scrub"] = float(np.mean(vals[-3:])) * _ramp(n_strong, 2.0, 4.0)
    return {k: float(np.clip(v, 0.0, 1.0)) for k, v in pr.items()
            if k in artifact_preset_names()}


def _khz(hz: float) -> str:
    return f"{hz / 1000.0:.1f} kHz"


def evidence_phrase(name: str, ev: Evidence, pr: Dict[str, float]) -> str:
    t8, t9 = ev.tone_8_12, ev.tone_9_15
    if name == "cymbal_sheen":
        if t8.excess_db >= 3.0:
            return (f"A steady tone at {_khz(t8.hz)} stays {t8.excess_db:.0f} dB "
                    f"above the sound around it for {t8.duty:.0%} of the song.")
        return "No steady 8–12 kHz tone found."
    if name == "laser_whistle":
        t_hi = t9 if t9.excess_db >= ev.tone_12_20.excess_db else ev.tone_12_20
        if t_hi.excess_db >= 3.0:
            kind = "An on-and-off" if t_hi.duty < 0.85 else "A constant"
            return (f"{kind} narrow tone at {_khz(t_hi.hz)}, "
                    f"{t_hi.excess_db:.0f} dB above the sound around it "
                    f"(there {t_hi.duty:.0%} of the time).")
        return "No narrow tone above 9 kHz found."
    if name == "air_brittle":
        s = (f"The air band above 12 kHz is {ev.top_tilt_db:+.0f} dB compared "
             f"with 4–12 kHz.")
        t = ev.tone_12_20
        if t.excess_db >= 4.0:
            s += f" Fixed tone at {_khz(t.hz)} ({t.excess_db:.0f} dB)."
        return s
    if name == "sibilance_rattle":
        return f"Sharp sibilance bursts on {ev.sib_burst:.0%} of the frames."
    if name == "cymbal_chatter":
        return (f"Repeating high-end pattern beyond the beat: {ev.period_excess:+.2f}; "
                f"comb pattern {ev.comb:.2f}.")
    if name == "broadband_fizz":
        return (f"8–18 kHz is {ev.flat_8_18:.0%} hiss-like and "
                f"{ev.upper_db:+.0f} dB compared with 1–3 kHz.")
    if name == "checkerboard_grid":
        return f"Comb pattern score {ev.comb:.2f} (0.15 is normal)."
    if name == "reverb_flutter":
        return (f"Decays carry {ev.tail_contrast:+.3f} more narrow peaks "
                f"than attacks.")
    if name == "suno_hash":
        return (f"Fast flicker of {ev.flicker_hi_db:.1f} dB in 4.5–12 kHz, "
                f"against {ev.flicker_body_db:.1f} dB in the mids "
                f"({ev.flicker_excess_db:+.1f} dB more).")
    if name in ("vocal_glaze", "presence_haze"):
        return (f"The presence band (3–8 kHz) is {ev.presence_db:+.0f} dB compared "
                f"with 1–3 kHz and {ev.flat_3_8:.0%} hiss-like.")
    if name == "vocal_glaze_plus":
        return (f"Presence {ev.presence_db:+.0f} dB and {ev.flat_3_8:.0%} hiss-like, "
                f"plus {ev.flicker_excess_db:+.1f} dB of flicker in 4.5–12 kHz.")
    if name == "echo_sheen":
        return (f"3–10 kHz follows the mids (match {ev.echo_corr:.2f}) and is "
                f"{ev.flat_3_8:.0%} hiss-like.")
    if name == "phantom_cymbal":
        return (f"{ev.ring_4_10:.0%} of the 4–10 kHz bins ring on and off; "
                f"presence {ev.presence_db:+.0f} dB.")
    if name == "harsh_veil":
        return (f"4–12 kHz is {ev.umid_db:+.0f} dB compared with 1–3 kHz and "
                f"{ev.flat_4_12:.0%} hiss-like.")
    if name == "deep_scrub":
        n = sum(1 for k, v in pr.items() if k != "deep_scrub" and v > 0.4)
        return f"{n} kinds of noise found at once."
    return ""


def balance_notes(ev: Evidence) -> List[str]:
    notes: List[str] = []
    # Dense mixes normally carry +4..+9 dB here; flag the real outliers.
    if ev.mud_db > 10.0:
        notes.append(
            f"The low-mids (200–500 Hz) are {ev.mud_db:.0f} dB louder than "
            f"500–2000 Hz. Try the Muddy / Boxy preset or a low-mid cut.")
    if ev.dull_db < -26.0:
        notes.append(
            f"The top end (4–14 kHz) is {-ev.dull_db:.0f} dB below the mids "
            f"(300–3000 Hz). Try Dark Mix Rescue after cleaning.")
    if ev.cutoff_hz > 0:
        notes.append(
            f"This render's top end stops at {_khz(ev.cutoff_hz)}. EQ boosts "
            f"will not go above that point.")
    if ev.click_rate >= 10.0:
        notes.append(
            f"Possible crackle: about {ev.click_rate:.0f} clicks per second in "
            f"the high end. Try De-click (on in Sibilance Rattle and Deep "
            f"Scrub; also in Advanced). Busy hi-hats can show up here too, so "
            f"trust your ears.")
    return notes


# ---------------------------------------------------------------------------
# Stage 2: verification through the real pipeline
# ---------------------------------------------------------------------------

@dataclass
class Masks:
    f: np.ndarray
    eligible: np.ndarray       # bool [bins, frames]
    protected_hi: np.ndarray   # bool [bins, frames]
    body: np.ndarray           # bool [bins, frames]
    e_hi: float                # input energy >= 2 kHz over valid frames
    active: np.ndarray         # bool [frames]
    tone_bins: np.ndarray      # int [n_tones] bins of steady tones in this clip
    tone_in_db: np.ndarray     # float [n_tones] input q25 level at those bins
    tone_excess: np.ndarray    # float [n_tones] excess above the local envelope
    tone_centered: np.ndarray  # bool [n_tones] tone sits in Mid (>6 dB over Side)
    x: Optional[np.ndarray] = None   # the clip itself, the damage reference


@dataclass
class Measure:
    """One trial clean, measured.

    `artifact_db`, `collateral_db` and `net_db` are energy measures of the
    removed signal (re. the input's top end) and are informational: they
    say where the preset worked, not whether that was audible. The score
    comes from the hearing-model fields: `missing` (audible content gone,
    sones), `lin_dist` (tilt, sones) and `added` (content introduced).
    """
    artifact_db: float
    collateral_db: float
    net_db: float
    missing: float = 0.0
    lin_dist: float = 0.0
    added: float = 0.0
    tone_removed: float = -1.0   # 0..1 share of tone excess removed; -1 = no tones

    def as_dict(self) -> Dict[str, float]:
        d = {"artifact_db": round(self.artifact_db, 2),
             "collateral_db": round(self.collateral_db, 2),
             "net_db": round(self.net_db, 2),
             "missing": round(self.missing, 4),
             "lin_dist": round(self.lin_dist, 3),
             "added": round(self.added, 4)}
        if self.tone_removed >= 0.0:
            d["tone_removed"] = round(self.tone_removed, 3)
        return d


_NULL_MEASURE = Measure(-120.0, -120.0, -120.0)


def _q25_active(S: np.ndarray, active: np.ndarray) -> np.ndarray:
    Sa = S[:, active] if active.sum() >= 8 else S
    return np.percentile(Sa, 25, axis=1)


def build_masks(clip: np.ndarray, sr: int,
                tones: Optional[Sequence[Tone]] = None) -> Masks:
    """Split the clip's STFT cells into artifact-eligible and protected
    regions, and locate the scan's steady tones inside this clip."""
    f, P = _stft_power(clip, sr, VERIFY_N_FFT, VERIFY_HOP)
    S = _DB * np.log(P.astype(np.float64) + _EPS)
    full_db = _DB * np.log(P.sum(axis=0).astype(np.float64) + _EPS)
    n = P.shape[1]
    active = _active_frames(full_db)
    transient = _transient_frames(full_db)

    R = S - median_filter(S, size=(31, 1), mode="nearest")
    Ra = R[:, active] if active.sum() >= 8 else R
    q25 = np.percentile(Ra, 25, axis=1)
    q50 = np.percentile(Ra, 50, axis=1)
    steady = (q25 > 3.0) | (q50 > 6.0)

    peaky = R > 6.0
    # Sustained runs of >= PARTIAL_MIN_FRAMES at the same bin.
    run = _sustained_runs(peaky, PARTIAL_MIN_FRAMES)
    in_partial_band = ((f >= PROTECT_BELOW_HZ) & (f < PARTIAL_MAX_HZ))[:, None]
    partial = peaky & run & in_partial_band & ~steady[:, None]

    edge = int(math.ceil(EDGE_TRIM_S * sr / VERIFY_HOP))
    valid = np.zeros(n, dtype=bool)
    if n > 2 * edge + 2:
        valid[edge:n - edge] = True
    else:
        valid[:] = True

    body = (f < PROTECT_BELOW_HZ)[:, None] & valid[None, :]
    hi = (f >= PROTECT_BELOW_HZ)[:, None] & valid[None, :]
    protected_hi = hi & (transient[None, :] | partial)
    eligible = hi & ~protected_hi
    e_hi = float(P[hi].sum())

    # Steady tones from the whole-file scan, re-measured inside the clip
    # (an intermittent whistle may be absent from this window).
    tone_bins: List[int] = []
    tone_in: List[float] = []
    tone_ex: List[float] = []
    if tones:
        q25_s = _q25_active(S, active)
        bin_hz = float(f[1] - f[0])
        for t in tones:
            if t.excess_db < TONE_MIN_EXCESS_DB:
                continue
            b = int(round(t.hz / bin_hz))
            if b < 2 or b >= f.size - 2:
                continue
            lo, hi_b = max(0, b - 25), min(f.size, b + 26)
            local = float(np.median(q25_s[lo:hi_b]))
            # Peak may sit one bin off after the coarse scan; take the best.
            bb = b + int(np.argmax(q25_s[b - 1:b + 2])) - 1
            ex = float(q25_s[bb] - local)
            if ex >= 4.0:
                tone_bins.append(bb)
                tone_in.append(float(q25_s[bb]))
                tone_ex.append(ex)

    # Is each tone centered?  The pipeline cleans Mid at 20% strength, so
    # a centered tone is far less reachable than one in the sides.
    centered = np.zeros(len(tone_bins), dtype=bool)
    if tone_bins and clip.ndim > 1 and clip.shape[1] >= 2:
        mid = 0.5 * (clip[:, 0] + clip[:, 1])
        side = 0.5 * (clip[:, 0] - clip[:, 1])
        _, Pm = _stft_power(mid, sr, VERIFY_N_FFT, VERIFY_HOP)
        _, Ps = _stft_power(side, sr, VERIFY_N_FFT, VERIFY_HOP)
        bins = np.array(tone_bins, dtype=int)
        qm = _q25_active(_DB * np.log(Pm[bins].astype(np.float64) + _EPS), active)
        qs = _q25_active(_DB * np.log(Ps[bins].astype(np.float64) + _EPS), active)
        centered = (qm - qs) > 6.0

    return Masks(f=f, eligible=eligible, protected_hi=protected_hi,
                 body=body, e_hi=max(e_hi, _EPS), active=active,
                 tone_bins=np.array(tone_bins, dtype=int),
                 tone_in_db=np.array(tone_in, dtype=np.float64),
                 tone_excess=np.array(tone_ex, dtype=np.float64),
                 tone_centered=centered, x=clip)


def measure_removed(removed: np.ndarray, sr: int, m: Masks,
                    processed: Optional[np.ndarray] = None,
                    reference: Optional[np.ndarray] = None) -> Measure:
    """Measure one pipeline run: where the removed energy sat (informational),
    what the change cost a listener (the hearing model, when `processed` is
    given), and, when tones are in play, how far the processed output
    dropped at the tone bins.

    The damage reference is the clip the masks were built from, unless
    `reference` names another signal (a second pass is measured against the
    first pass's output, not the original)."""
    _, Pr = _stft_power(removed, sr, VERIFY_N_FFT, VERIFY_HOP)
    if Pr.shape != m.eligible.shape:
        return _NULL_MEASURE
    G = float(Pr[m.eligible].sum())
    Bh = float(Pr[m.protected_hi].sum())
    Bb = float(Pr[m.body].sum())
    B = Bh + BODY_WEIGHT * Bb
    artifact_db = _DB * math.log(G / m.e_hi + _EPS)
    collateral_db = _DB * math.log(B / m.e_hi + _EPS)
    net = (G - COLLATERAL_LAMBDA * B) / m.e_hi
    net_db = _DB * math.log(max(net, 1e-12))

    missing = lin_dist = added = 0.0
    ref = m.x if reference is None else reference
    if processed is not None and ref is not None:
        d = measure_damage(ref, processed, sr)
        missing, lin_dist, added = d.missing, d.lin_dist, d.added

    tone_removed = -1.0
    if m.tone_bins.size and processed is not None:
        _, Py = _stft_power(processed, sr, VERIFY_N_FFT, VERIFY_HOP)
        if Py.shape == m.eligible.shape:
            Sy = _DB * np.log(Py.astype(np.float64) + _EPS)
            q25_y = _q25_active(Sy, m.active)
            drop = m.tone_in_db - q25_y[m.tone_bins]
            frac = np.clip(drop / np.maximum(m.tone_excess, 1e-6), 0.0, 1.0)
            tone_removed = float(np.mean(frac))
    return Measure(artifact_db, collateral_db, net_db,
                   missing, lin_dist, added, tone_removed)


def audible_cost(meas: Measure) -> float:
    """0..1 share of the tilt ceiling this run used up."""
    return _ramp(meas.lin_dist, 0.0, LIN_DIST_FULL)


def verified_score(meas: Measure, prior: float, tone_weight: float = 0.0) -> float:
    """Net audible benefit of one pipeline run, 0..1.

    `prior` is the evidence that this preset's artifact is present (0..1,
    from `priors_from_evidence`).  `tone_weight` (0..TONE_WEIGHT_MAX) is how
    much of the benefit the tone-kill term carries; it is 0 when the scan
    found no steady tones.

    Audible removal is credited by the evidence for the artifact and
    debited by the evidence against it, so a preset with no evidence gets
    nothing for removing a lot, and one with strong evidence gets more for
    removing more only until tilt damage takes it back.  Nothing here is
    normalised by where the removal happened.
    """
    p = float(np.clip(prior, 0.0, 1.0))
    m = _ramp(meas.missing, 0.0, MISSING_FULL_SONES)
    energy = (2.0 * p - 1.0) * m
    if tone_weight > 0.0 and meas.tone_removed >= 0.0:
        benefit = (1.0 - tone_weight) * energy + tone_weight * meas.tone_removed
    else:
        benefit = energy
    return float(max(0.0, benefit - audible_cost(meas)))


def eligible_tones(tones: Sequence[Tone]) -> List[Tone]:
    """Lines that count as generator artifacts for scoring and static
    repair: the same rules repair.plan_from_lines applies (>= 6 dB
    persistent excess; below 3 kHz also >= 10 dB and >= 90 % duty), so a
    partial shared by every chord never scores as a tone."""
    from .repair import (LOW_LINE_HZ, LOW_LINE_MIN_DUTY, LOW_LINE_MIN_EXCESS_DB,
                         MIN_LINE_EXCESS_DB, MIN_NOTCH_HZ)
    out: List[Tone] = []
    for t in tones:
        if t.hz < MIN_NOTCH_HZ or t.excess_db < MIN_LINE_EXCESS_DB:
            continue
        if t.hz < LOW_LINE_HZ and (t.excess_db < LOW_LINE_MIN_EXCESS_DB
                                   or t.duty < LOW_LINE_MIN_DUTY):
            continue
        out.append(t)
    return out


def tone_weight_for(tones: Sequence[Tone]) -> float:
    tones = eligible_tones(tones)
    if not tones:
        return 0.0
    strongest = max(t.excess_db for t in tones)
    return TONE_WEIGHT_MAX * _ramp(strongest, TONE_MIN_EXCESS_DB, 12.0)


def _run_preset(clip: np.ndarray, sr: int, name: str, strength: float
                ) -> Tuple[np.ndarray, np.ndarray]:
    """Run the real cleaning pipeline (no mastering / EQ). Returns
    (processed, removed)."""
    from .pipeline import clean_and_master
    p = get_preset(name)
    if abs(strength - 1.0) > 1e-6:
        apply_preset_strength(p, float(strength))
    y, removed, _ = clean_and_master(clip, sr, p, master_params=None)
    return y, removed


def _quantize_strength(s: float) -> float:
    s = float(np.clip(s, STRENGTH_MIN, STRENGTH_MAX))
    return round(round(s / STRENGTH_STEP) * STRENGTH_STEP, 2)


def _pick_strength(results: Dict[float, Measure], base: Measure,
                   prior: float, tone_weight: float = 0.0) -> float:
    """Gentlest strength whose verified score is within tolerance of the
    best, subject to a collateral guard relative to 100%.  Damage needs no
    separate guard: it is already inside the score."""
    ok: Dict[float, float] = {}
    for s, mres in results.items():
        if mres.collateral_db > base.collateral_db + STRENGTH_COLLATERAL_GUARD_DB:
            continue
        ok[s] = verified_score(mres, prior, tone_weight)
    if not ok:
        return 1.0
    best = max(ok.values())
    for s in sorted(ok.keys()):
        if ok[s] >= best - STRENGTH_TOLERANCE:
            return float(s)
    return 1.0


def tune_strength(clip: np.ndarray, sr: int, name: str, masks: Masks,
                  base: Measure, prior: float, tone_weight: float = 0.0,
                  refine: bool = True
                  ) -> Tuple[float, Dict[float, Measure], int]:
    """Sweep the strength grid (then +/-0.25 around the pick) and return
    (strength, sweep results, runs)."""
    results: Dict[float, Measure] = {1.0: base}
    runs = 0
    for s in STRENGTH_GRID:
        if s in results:
            continue
        y, removed = _run_preset(clip, sr, name, s)
        results[s] = measure_removed(removed, sr, masks, y)
        runs += 1
    pick = _pick_strength(results, base, prior, tone_weight)
    if refine:
        for s in (pick - 0.25, pick + 0.25):
            s = round(s, 2)
            if s < STRENGTH_MIN or s > STRENGTH_MAX or s in results:
                continue
            y, removed = _run_preset(clip, sr, name, s)
            results[s] = measure_removed(removed, sr, masks, y)
            runs += 1
        pick = _pick_strength(results, base, prior, tone_weight)
    return _quantize_strength(pick), results, runs


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------

def _verify_sentence(meas: Measure, strength: float) -> str:
    s = (f"Test clean cut noise {-meas.artifact_db:.0f} dB below the top end. "
         f"Audible loss {meas.missing:.3f} sones "
         f"({_ramp(meas.missing, 0.0, MISSING_FULL_SONES):.0%} of the limit), "
         f"tone shift {meas.lin_dist:.2f} ({audible_cost(meas):.0%} of the limit)")
    if meas.tone_removed >= 0.0:
        s += f"; steady tones cut by {meas.tone_removed:.0%}"
    if abs(strength - 1.0) > 1e-6:
        s += f"; best at {strength:.0%} strength"
    return s + "."


def _generic_result(timeline: List[float], metrics: Dict[str, Any],
                    evidence: Dict[str, Any], notes: List[str],
                    reason: str,
                    repair_plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "preset": "generic",
        "strength": 1.0,
        "repair_plan": repair_plan or {"enabled": True, "notches": []},
        "ranked": [{
            "name": "generic",
            "label": label_for("generic"),
            "score": 0.0,
            "confidence": 0.0,
            "strength": 1.0,
            "reason": reason,
        }],
        "follow_up": None,
        "notes": notes,
        "timeline": {"step_s": 1.0, "intensity": timeline},
        "scores": {},
        "checkerboard_score": float(evidence.get("comb", 0.0) or 0.0),
        "evidence": evidence,
        "metrics": metrics,
    }


def suggest_array(x: np.ndarray, sr: int,
                  verify: bool = True,
                  window_s: float = 5.0,
                  max_scan_s: float = 300.0,
                  candidates: Optional[Sequence[str]] = None,
                  tune_top: int = 2,
                  follow_up: bool = False,
                  max_ranked: int = 6) -> Dict[str, Any]:
    """Analyse audio in memory and return the recommendation dict.

    Keys: preset, strength, ranked[], follow_up, notes[], timeline,
    scores, checkerboard_score, evidence, metrics.

    `follow_up` is off by default: the automated flow is one pass. Measured
    on three multi-artifact tracks, cleaning revealed no new artifact but
    raised other presets' priors (they are relative measures, so removing
    energy in one band inflates the rest), so the second pass was partly
    answering a number the first pass created; and under the net-benefit
    score no runner-up cleared the actionable threshold on the winner's
    output on any corpus file. Iteration a preset genuinely needs belongs
    inside it (`Params.iterations`), where one damage measurement covers
    it. Pass `follow_up=True` to ask for the check anyway.
    """
    t0 = time.time()
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    scan = evidence_scan(x, sr, window_s=window_s, max_scan_s=max_scan_s)
    ev = scan.evidence
    pr = priors_from_evidence(ev)
    names = list(candidates) if candidates else artifact_preset_names()
    names = [n for n in names if n in pr]
    notes = balance_notes(ev)

    # Static repair runs first in the real chain, so the trial cleans are
    # judged on the repaired signal and the plan is reported with the pick.
    from .repair import apply_static_repair, plan_from_lines
    from dataclasses import asdict as _asdict
    plan = plan_from_lines([_asdict(t) for t in ev.tones], sr)
    if plan.notches:
        top = max(plan.notches, key=lambda n: n.depth_db)
        notes.insert(0, (
            f"Static Notches will cut {len(plan.notches)} fixed "
            f"tone{'s' if len(plan.notches) != 1 else ''} first "
            f"(deepest {top.depth_db:.0f} dB at {_khz(top.hz)}). Untick any "
            f"you want to keep."))

    metrics: Dict[str, Any] = {
        "sample_rate": int(sr),
        "analyzed_seconds": round(scan.scanned_s, 2),
        "duration_seconds": round(scan.duration_s, 2),
        "window_start_s": round(scan.window_start_s, 2),
        "window_s": float(window_s),
        "verified": False,
        "verify_runs": 0,
    }

    w0 = int(scan.window_start_s * sr)
    w1 = min(x.shape[0], w0 + int(window_s * sr))
    clip = np.ascontiguousarray(x[w0:w1])
    if plan.notches and clip.shape[0] > 0:
        clip, _ = apply_static_repair(clip, sr, plan)
        clip = np.ascontiguousarray(clip)
    metrics["repair_notches"] = len(plan.notches)
    can_verify = verify and clip.shape[0] >= int(1.5 * sr)

    measures: Dict[str, Measure] = {}
    runs = 0
    masks: Optional[Masks] = None
    tone_w = 0.0
    if can_verify:
        masks = build_masks(clip, sr, eligible_tones(ev.tones))
        tone_w = tone_weight_for(ev.tones) if masks.tone_bins.size else 0.0
        metrics["tone_weight"] = round(tone_w, 3)
        for n in names:
            try:
                y, removed = _run_preset(clip, sr, n, 1.0)
                measures[n] = measure_removed(removed, sr, masks, y)
            except Exception:
                measures[n] = _NULL_MEASURE
            runs += 1
        metrics["verified"] = True

    # Final score.  Verified, the prior is inside the score; unverified,
    # the prior is all there is.
    finals: Dict[str, float] = {}
    for n in names:
        if can_verify:
            finals[n] = verified_score(measures[n], pr[n], tone_w)
        else:
            finals[n] = pr[n]
    order = sorted(names, key=lambda n: -finals[n])
    best = order[0]
    best_score = finals[best]

    actionable = best_score >= MIN_ACTIONABLE_SCORE
    if can_verify and measures[best].artifact_db < MIN_ACTIONABLE_ARTIFACT_DB:
        actionable = False
    if not actionable:
        metrics["verify_runs"] = runs
        metrics["elapsed_ms"] = int((time.time() - t0) * 1000)
        return _generic_result(
            scan.timeline, metrics, ev.as_dict(), notes,
            "Nothing notable to remove; safe defaults will do.",
            repair_plan=plan.as_dict())

    # Strength for the top picks.
    strengths: Dict[str, float] = {n: 1.0 for n in names}
    sweeps: Dict[str, Dict[float, Measure]] = {}
    if can_verify and masks is not None:
        for i, n in enumerate(order[:max(0, tune_top)]):
            s, sweep, r = tune_strength(
                clip, sr, n, masks, measures[n], pr[n], tone_weight=tone_w,
                refine=(i == 0))
            strengths[n] = s
            sweeps[n] = sweep
            runs += r

    # Steady tones the cleaning chain cannot reach are worth saying out
    # loud: a manual notch is the surer fix.
    if can_verify and masks is not None and masks.tone_bins.size:
        best_meas = sweeps.get(best, {}).get(strengths[best], measures[best])
        if 0.0 <= best_meas.tone_removed < 0.5:
            k = int(np.argmax(masks.tone_excess))
            hz = float(masks.f[masks.tone_bins[k]])
            where = ("It is in the center of the mix, where cleaning runs at 20%."
                     if bool(masks.tone_centered[k]) else "")
            notes.append(
                f"A steady tone at {hz / 1000.0:.2f} kHz is still there after the "
                f"test clean (cut by {best_meas.tone_removed:.0%}). {where} A narrow "
                f"notch in the Parametric EQ at {hz / 1000.0:.2f} kHz is the surer fix."
                .replace("  ", " "))

    # Confidence: absolute score blended with margin over the runner-up.
    second = finals[order[1]] if len(order) > 1 else 0.0
    margin = max(0.0, 1.0 - second / best_score) if best_score > 1e-6 else 0.0
    conf_top = float(np.clip(best_score * (0.5 + 0.5 * margin) * 1.5, 0.0, 0.98))

    ranked: List[Dict[str, Any]] = []
    for i, n in enumerate(order[:max_ranked]):
        sc = finals[n]
        if sc <= 0.0:
            continue
        conf = conf_top if i == 0 else conf_top * float(np.clip(sc / best_score, 0.0, 1.0))
        s = strengths[n]
        reason = evidence_phrase(n, ev, pr)
        entry: Dict[str, Any] = {
            "name": n,
            "label": label_for(n),
            "score": round(float(sc), 3),
            "confidence": round(conf, 3),
            "strength": float(s),
            "prior": round(pr[n], 3),
            "reason": reason,
        }
        if can_verify:
            meas = sweeps.get(n, {}).get(s, measures[n])
            entry.update(meas.as_dict())
            entry["reason"] = (reason + " " + _verify_sentence(meas, s)).strip()
            if n in sweeps:
                entry["strength_sweep"] = {
                    f"{k:.2f}": v.as_dict() for k, v in sorted(sweeps[n].items())}
        ranked.append(entry)

    # Second pass: would a different preset still find residue after the
    # winner has done its work?
    follow: Optional[Dict[str, Any]] = None
    if can_verify and follow_up and masks is not None:
        y_best, _ = _run_preset(clip, sr, best, strengths[best])
        runs += 1
        best_meas = sweeps.get(best, {}).get(strengths[best], measures[best])
        cands = [n for n in order[1:4]]
        best_follow: Optional[Tuple[str, Measure, float]] = None
        for n in cands:
            try:
                y2, removed2 = _run_preset(y_best, sr, n, 1.0)
            except Exception:
                continue
            runs += 1
            m2 = measure_removed(removed2, sr, masks, y2, reference=y_best)
            s2 = verified_score(m2, pr[n], tone_w)
            if (m2.artifact_db >= best_meas.artifact_db + FOLLOW_UP_MIN_RATIO_DB
                    and m2.artifact_db >= FOLLOW_UP_MIN_ARTIFACT_DB
                    and s2 >= MIN_ACTIONABLE_SCORE
                    and (best_follow is None or s2 > best_follow[2])):
                best_follow = (n, m2, s2)
        if best_follow is not None:
            n, m2, s2 = best_follow
            follow = {
                "name": n,
                "label": label_for(n),
                "strength": 1.0,
                "score": round(float(s2), 3),
                "reason": (f"Run on the cleaned result, {label_for(n)} still "
                           f"cuts noise {-m2.artifact_db:.0f} dB below the top end "
                           f"for a net audible gain of {s2:.2f}. Worth a second pass."),
                **m2.as_dict(),
            }

    metrics["verify_runs"] = runs
    metrics["elapsed_ms"] = int((time.time() - t0) * 1000)
    return {
        "preset": best,
        "strength": float(strengths[best]),
        "repair_plan": plan.as_dict(),
        "ranked": ranked,
        "follow_up": follow,
        "notes": notes,
        "timeline": {"step_s": 1.0, "intensity": scan.timeline},
        "scores": {n: round(float(v), 3) for n, v in finals.items()},
        "priors": {n: round(float(v), 3) for n, v in pr.items()},
        "verification": {n: m.as_dict() for n, m in measures.items()},
        "checkerboard_score": round(float(ev.comb), 3),
        "evidence": ev.as_dict(),
        "metrics": metrics,
    }


def suggest(input_path: str, **kwargs: Any) -> Dict[str, Any]:
    """Analyse a file on disk. See `suggest_array` for options."""
    x, sr = load_audio(input_path)
    return suggest_array(x, sr, **kwargs)
