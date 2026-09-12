"""Fixed tones and the bandwidth cutoff, found once for the whole song.

Ported unchanged from 1.1.1 (docs/ARCHITECTURE.md §19.1 item 1):

- scan_fixed_lines and its helpers, from shimmer/detect.py: the whole-file
  scan for the generator's fixed tonal lines and comb teeth. The notch
  (shimmer.core.repair.notch) turns them into a plan.
- estimate_cutoff_hz, from shimmer/repair.py: where a render's top end
  stops (many exports end at 12-15 kHz), so nothing boosts the empty band
  above it.

These measure; they never change audio.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import signal
from scipy.ndimage import median_filter
from scipy.signal import welch

_EPS = 1e-12
_DB = 10.0 / math.log(10.0)          # power (natural log) -> dB

VERIFY_N_FFT = 4096


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


def _active_frames(full_db: np.ndarray, floor_db: float = 50.0) -> np.ndarray:
    """Frames that are not digital silence / deep fades."""
    if full_db.size == 0:
        return np.zeros(0, dtype=bool)
    act = full_db > (float(full_db.max()) - floor_db)
    if act.sum() < 8:
        act = np.ones_like(act, dtype=bool)
    return act


@dataclass
class Tone:
    hz: float
    excess_db: float          # 25th-percentile excess over time (persistence)
    duty: float
    kind: str = "line"        # "line" (isolated) | "comb" (evenly spaced tooth)
    excess_hi_db: float = 0.0  # 90th-percentile excess: how strong it gets


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
    teeth (repair.notch.plan_from_lines turns these into static notches).
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


def estimate_cutoff_hz(x: np.ndarray, sr: int, max_s: float = 120.0) -> Dict[str, Any]:
    """Find where the render's top end stops.

    Long-term Welch spectrum on the mono mix; a trend line is fitted on
    4–10 kHz (dB against log-frequency); the cutoff is the lowest
    frequency above 8 kHz where the spectrum sits >= 30 dB under the
    trend and stays there for the rest of the band, with real content
    (within 12 dB of trend) in the octave just below. Returns
    {"cutoff_hz": float or None, "above_db": mean excess above cutoff}.
    """
    x2 = np.asarray(x, dtype=np.float32)
    if x2.ndim == 1:
        x2 = x2[:, None]
    n = min(x2.shape[0], int(max_s * sr))
    if n < 8192:
        return {"cutoff_hz": None, "above_db": None}
    mono = x2[:n].mean(axis=1).astype(np.float64)
    f, P = welch(mono, fs=sr, nperseg=4096, noverlap=2048)
    L = 10.0 * np.log10(P + _EPS)
    fit = (f >= 4000.0) & (f <= 10000.0)
    if fit.sum() < 8:
        return {"cutoff_hz": None, "above_db": None}
    lf = np.log2(np.maximum(f, 1.0))
    slope, icpt = np.polyfit(lf[fit], L[fit], 1)
    trend = slope * lf + icpt
    excess = L - trend
    nyq = 0.5 * sr
    # A roll-off in the last tenth of the band is the normal anti-alias
    # slope of the export, not a cutoff worth acting on.
    cand = np.where((f >= 8000.0) & (f <= 0.9 * nyq))[0]
    for i in cand:
        if excess[i] >= -30.0:
            continue
        rest = excess[i:][f[i:] <= 0.95 * nyq]
        if rest.size and np.mean(rest < -20.0) >= 0.9:
            below = (f >= f[i] * 0.5) & (f < f[i])
            if below.sum() and float(np.mean(excess[below])) > -12.0:
                return {"cutoff_hz": float(f[i]), "above_db": float(np.mean(rest))}
    return {"cutoff_hz": None, "above_db": None}
