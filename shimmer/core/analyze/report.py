"""Whole-file numbers for the report shown after a run.

Ported from shimmer/report.py (1.1.1). One change: the peak-to-loudness
ratio reads true peak from the engine's meter (the louder channel, 8x).
1.1.1 read it from a mono mix at 4x, so it read low whenever the channels
differed (docs/ARCHITECTURE.md §10).

Three things a release check wants that the job metrics did not carry:

* Band spectra of the input, the output and the removed signal on a
  1/6-octave grid, plus a level-matched "after minus before" delta so
  the change in shape reads apart from the change in loudness. The
  level match is the median change in the low mids (100 Hz to 2 kHz).
* Peak-to-loudness ratio (true peak minus integrated loudness), the
  usual quick read on how hard a master is limited.
* Stereo correlation, energy-weighted over the file: +1 is mono, 0 is
  uncorrelated, below 0 is out of phase and will lose level in mono.

Measurement only: nothing here touches the audio.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
from scipy.signal import welch

from ..audio import meters


def as_2d(x: np.ndarray) -> np.ndarray:
    return x[:, None] if x.ndim == 1 else x


BAND_F_LO = 40.0
BAND_F_HI = 20000.0
BANDS_PER_OCTAVE = 6
SPECTRUM_N_FFT = 4096

# The delta must sit this far under zero to count as "cut" for the
# headline, and this far over to count as "added".
CUT_MIN_DB = 1.5
CORR_BLOCK = 4096


def band_centers(sr: int) -> np.ndarray:
    hi = min(BAND_F_HI, 0.47 * sr)
    n = int(np.floor(np.log2(hi / BAND_F_LO) * BANDS_PER_OCTAVE)) + 1
    return BAND_F_LO * 2.0 ** (np.arange(n) / BANDS_PER_OCTAVE)


def band_spectrum_db(x: np.ndarray, sr: int, centers: np.ndarray,
                     n_fft: int = SPECTRUM_N_FFT) -> List[float]:
    """Mean power per band in dB (0 dB = a full-scale square wave; a
    full-scale sine reads -3 dB). Channels are averaged as power, not
    mixed to mono first, so out-of-phase side content still counts."""
    x = as_2d(np.asarray(x, dtype=np.float64))
    n = x.shape[0]
    if n < 64:
        return [-120.0] * int(centers.size)
    seg = min(n_fft, n)
    psd = None
    freqs = None
    for ch in range(x.shape[1]):
        f, p = welch(x[:, ch], fs=sr, nperseg=seg, noverlap=seg // 2,
                     window="hann", scaling="density")
        psd = p if psd is None else psd + p
        freqs = f
    psd = psd / x.shape[1]
    df = float(freqs[1] - freqs[0]) if freqs.size > 1 else 1.0
    half = 2.0 ** (1.0 / (2 * BANDS_PER_OCTAVE))
    out: List[float] = []
    for cf in centers:
        idx = np.where((freqs >= cf / half) & (freqs < cf * half))[0]
        if idx.size == 0:
            idx = np.array([int(np.argmin(np.abs(freqs - cf)))])
        power = float(np.sum(psd[idx]) * df)
        out.append(round(10.0 * np.log10(power + 1e-14), 2))
    return out


# Level matching uses the bands between these two frequencies: the low
# mids carry most of a mix's energy and the cleaning does not act there,
# so their median change is the pass's plain level change (mastering
# gain), not a side effect of a top-end cut.
MATCH_LO_HZ = 100.0
MATCH_HI_HZ = 2000.0


def _level_change_db(before: List[float], after: List[float],
                     centers: np.ndarray) -> float:
    diff = np.asarray(after, dtype=np.float64) - np.asarray(before, dtype=np.float64)
    sel = (centers >= MATCH_LO_HZ) & (centers <= MATCH_HI_HZ)
    if not np.any(sel):
        sel = np.ones_like(diff, dtype=bool)
    return float(np.median(diff[sel]))


def spectra_report(x_in: np.ndarray, y_out: np.ndarray,
                   removed: Optional[np.ndarray], sr: int) -> Dict[str, Any]:
    centers = band_centers(sr)
    before = band_spectrum_db(x_in, sr, centers)
    after = band_spectrum_db(y_out, sr, centers)
    rem = band_spectrum_db(removed, sr, centers) if removed is not None else None
    gain_db = _level_change_db(before, after, centers)
    delta = [round(a - b - gain_db, 2) for a, b in zip(after, before)]

    # Headline numbers: the widest run of bands cut by CUT_MIN_DB or
    # more, the deepest cut inside it, and the largest change under 2 kHz.
    d = np.asarray(delta)
    cut_mask = d <= -CUT_MIN_DB
    best = None
    i = 0
    while i < d.size:
        if not cut_mask[i]:
            i += 1
            continue
        j = i
        while j + 1 < d.size and cut_mask[j + 1]:
            j += 1
        depth = float(d[i:j + 1].min())
        if best is None or (j - i) > (best[1] - best[0]) or \
                ((j - i) == (best[1] - best[0]) and depth < best[2]):
            best = (i, j, depth)
        i = j + 1
    cut = None
    if best is not None:
        i, j, depth = best
        at = int(np.argmin(d[i:j + 1])) + i
        cut = {"lo_hz": round(float(centers[i]), 1),
               "hi_hz": round(float(centers[j]), 1),
               "max_cut_db": round(-depth, 2),
               "at_hz": round(float(centers[at]), 1)}
    low = d[centers < 2000.0]
    low_max_abs = round(float(np.max(np.abs(low))), 2) if low.size else 0.0
    added_max = round(float(np.max(d)), 2) if d.size else 0.0
    return {
        "centers_hz": [round(float(c), 1) for c in centers],
        "before_db": before,
        "after_db": after,
        "removed_db": rem,
        "delta_db": delta,
        "gain_db": round(gain_db, 2),
        "cut": cut,
        "low_max_abs_db": low_max_abs,
        "added_max_db": added_max,
    }


def stereo_correlation(x: np.ndarray, block: int = CORR_BLOCK) -> Optional[float]:
    """Energy-weighted mean of per-block L/R correlation; None for mono."""
    x = as_2d(np.asarray(x, dtype=np.float64))
    if x.shape[1] < 2 or x.shape[0] < 16:
        return None
    left, right = x[:, 0], x[:, 1]
    n = (x.shape[0] // block) * block
    if n == 0:
        n = x.shape[0]
        block = n
    l2 = left[:n].reshape(-1, block)
    r2 = right[:n].reshape(-1, block)
    ll = np.sum(l2 * l2, axis=1)
    rr = np.sum(r2 * r2, axis=1)
    lr = np.sum(l2 * r2, axis=1)
    w = ll + rr
    corr = lr / np.sqrt(np.maximum(ll * rr, 1e-20))
    if float(np.sum(w)) <= 0.0:
        return None
    return round(float(np.sum(w * corr) / np.sum(w)), 3)


def plr_db(x: np.ndarray, sr: int, lufs_i: Optional[float]) -> Optional[float]:
    """Peak-to-loudness ratio: true peak (dBTP) minus integrated LUFS."""
    if lufs_i is None or not np.isfinite(lufs_i):
        return None
    tp = meters.true_peak_db(np.asarray(x, dtype=np.float64), sr)
    if not np.isfinite(tp):
        return None
    return round(float(tp - lufs_i), 2)
