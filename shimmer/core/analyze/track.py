"""The whole-song snapshot the screens show after upload: loudness, the
1/3-octave spectrum and the bandwidth cutoff.

analyze_spectrum is ported unchanged from shimmer/mastering.py (1.1.1).
analyze_track reads loudness and true peak from the engine's meters: 1.1.1
read true peak from a mono mix at 4x, so it read low whenever the channels
differed (docs/ARCHITECTURE.md §10).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List

import numpy as np

from ..audio import meters
from .tones import estimate_cutoff_hz

# 1/3-octave centres, the same bands the tone target uses.
REF_FREQS = np.array([
    31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
    800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000,
    10000, 12500, 16000, 20000,
], dtype=np.float64)
_MID_BANDS = (REF_FREQS >= 200.0) & (REF_FREQS <= 2000.0)


def relative_band_levels(band_power_db: np.ndarray) -> np.ndarray:
    """Band power in dB relative to the median of the 200 Hz - 2 kHz bands,
    the same normalisation the reference uses."""
    b = np.asarray(band_power_db, dtype=np.float64)
    return b - float(np.median(b[_MID_BANDS]))


def _mono_mix(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        return x
    return x[:, 0] if x.shape[1] == 1 else np.mean(x, axis=1)


def analyze_spectrum(x: np.ndarray, sr: int, n_fft: int = 8192) -> Dict[str, Any]:
    """Long-term magnitude spectrum on 1/3-octave centers (dB)."""
    mono = _mono_mix(np.asarray(x, dtype=np.float64))
    if mono.size < n_fft:
        n_fft = max(512, 1 << int(math.ceil(math.log2(max(mono.size, 2)))))
    hop = n_fft // 4
    window = np.hanning(n_fft).astype(np.float64)
    n_frames = max(1, 1 + (mono.size - n_fft) // hop)
    acc = np.zeros(n_fft // 2 + 1, dtype=np.float64)
    for i in range(n_frames):
        s0 = i * hop
        frame = mono[s0:s0 + n_fft]
        if frame.size < n_fft:
            break
        spec = np.abs(np.fft.rfft(frame * window)) ** 2
        acc += spec
    acc /= max(1, n_frames)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    # Power in dB is 10 log10 of |X|^2 (20 log10 doubled every difference).
    power_db = 10.0 * np.log10(acc + 1e-20)

    band_db: List[float] = []        # mean per-bin level in the band
    band_power_db: List[float] = []  # total band power (what a 1/3-octave analyzer shows)
    for cf in REF_FREQS:
        lo = cf / (2 ** (1 / 6))
        hi = cf * (2 ** (1 / 6))
        idx = np.where((freqs >= lo) & (freqs <= hi))[0]
        if idx.size == 0:
            band_db.append(-120.0)
            band_power_db.append(-120.0)
        else:
            band_db.append(float(np.mean(power_db[idx])))
            band_power_db.append(float(10.0 * np.log10(np.sum(acc[idx]) + 1e-20)))

    rel = relative_band_levels(np.asarray(band_power_db))
    return {
        "freqs_hz": REF_FREQS.tolist(),
        "band_db": band_db,
        "band_power_db": band_power_db,
        "rel_db": [round(float(v), 2) for v in rel],
    }


def loudness_range(x: np.ndarray, sr: int) -> float:
    """LRA, as 1.1.1 measured it: pyloudnorm's loudness_range when the
    installed version has one, else 0.0."""
    import pyloudnorm as pyln
    try:
        return float(pyln.Meter(int(sr)).loudness_range(np.asarray(x, dtype=np.float64)))
    except Exception:  # noqa: BLE001
        return 0.0


def activity_timeline(x: np.ndarray, sr: int, step_s: float = 1.0,
                      lo_hz: float = 4500.0, hi_hz: float = 12000.0) -> Dict[str, Any]:
    """How busy the top end is, second by second, from 0 to 1.

    The screen parks the preview loop on the busiest stretch, where top-end
    problems (fizz, sibilance, harshness) are most likely to be heard.
    Levels are scaled between the song's own 20th and 95th percentiles, so
    every song uses the full range. Measures only.
    """
    from scipy.signal import butter, sosfilt
    mono = _mono_mix(x)
    hop = max(1, int(round(step_s * sr)))
    hi = min(hi_hz, 0.45 * sr)
    if mono.size < hop or hi <= lo_hz:
        return {"step_s": step_s, "intensity": []}
    y = sosfilt(butter(4, [lo_hz, hi], btype="bandpass", fs=sr, output="sos"), mono)
    n = int(np.ceil(y.size / hop))
    level = np.array([10.0 * np.log10(np.mean(y[i * hop:(i + 1) * hop] ** 2) + 1e-12)
                      for i in range(n)])
    lo_db, hi_db = np.percentile(level, 20), np.percentile(level, 95)
    if hi_db - lo_db < 1.0:
        hi_db = lo_db + 1.0
    intensity = np.clip((level - lo_db) / (hi_db - lo_db), 0.0, 1.0)
    return {"step_s": step_s, "intensity": [round(float(v), 3) for v in intensity]}


def analyze_track(x: np.ndarray, sr: int) -> Dict[str, Any]:
    """Loudness, 1/3-octave spectrum, and the bandwidth cutoff (None = full)."""
    loud = {
        "lufs_i": meters.loudness(x, sr),
        "lra": loudness_range(x, sr),
        "true_peak_dbtp": meters.true_peak_db(x, sr),
    }
    spec = analyze_spectrum(x, sr)
    cut = estimate_cutoff_hz(x, sr)
    return {
        "loudness": loud,
        "spectrum": spec,
        "cutoff_hz": cut.get("cutoff_hz"),
        "above_cutoff_db": cut.get("above_db"),
    }
