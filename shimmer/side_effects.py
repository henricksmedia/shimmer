"""
side_effects.py — What a cleaning tool does to music it should leave alone,
in numbers (docs/GOALS.md, "Never damage the music", item 3).

Each measure compares a clean host H with the tool's output on it, K (the
efficacy harness's control: the tool run on music with nothing to fix). The
hearing model in perceptual.py already reports music removed (`missing`)
and anything added (`added`; musical noise, the twinkling a bad noise
reducer leaves, shows up there). These cover the rest of item 3:

  width_db     side-to-mid energy of K against H. Negative = narrower.
  attack_db    how much the peak just after each hit changes, net of the
               level change around it. Negative = softened attacks.
  pumping_db   how far the level of K against H swings over time in the
               octave bands outside the tool's own band (the 5th to 95th
               percentile spread of the 50 ms level ratio, worst band). A
               static filter reads about 0; a tool that ducks the mix with
               the music reads high.

Pre-echo is checked on a synthetic drum hit in the contract tests
(tests/core/test_core_filters.py), where the hit's time is known exactly.

These are testing tools. Nothing in the app imports this module.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
from scipy import signal as ss

OCTAVES_HZ = (63.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0)
FRAME_S = 0.05
FLOOR_DB = 40.0          # frames this far under the band's loudest are ignored


def _2d(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    return a[:, None] if a.ndim == 1 else a


def width_db(h: np.ndarray, k: np.ndarray) -> float:
    """Side-to-mid energy of k against h, in dB. 0 for mono input."""
    def ratio(x):
        x = _2d(x)
        if x.shape[1] < 2:
            return None
        m = 0.5 * (x[:, 0] + x[:, 1])
        s = 0.5 * (x[:, 0] - x[:, 1])
        return float(np.sum(s ** 2)) / max(float(np.sum(m ** 2)), 1e-20)
    rh, rk = ratio(h), ratio(k)
    if rh is None or rk is None or rh < 1e-8:
        return 0.0
    return float(10.0 * np.log10(max(rk, 1e-20) / rh))


def _rms_db(x: np.ndarray, n: int) -> np.ndarray:
    """RMS in dB over consecutive n-sample frames (mono power)."""
    p = np.mean(_2d(x) ** 2, axis=1)
    m = len(p) // n
    if m == 0:
        return np.zeros(0)
    return 10.0 * np.log10(np.maximum(p[:m * n].reshape(m, n).mean(axis=1), 1e-20))


def onsets(x: np.ndarray, sr: int, rise_db: float = 6.0,
           floor_db: float = 30.0, spacing_s: float = 0.05) -> np.ndarray:
    """Sample positions of hits: a 2 ms envelope that jumps at least
    `rise_db` above its level 10 ms earlier, within `floor_db` of the loudest
    point, at least `spacing_s` apart."""
    n2 = max(1, int(0.002 * sr))
    env = _rms_db(x, n2)
    if env.size < 8:
        return np.zeros(0, dtype=int)
    lag = max(1, int(round(0.010 / 0.002)))
    rise = env[lag:] - env[:-lag]
    loud = env[lag:] > env.max() - floor_db
    cand = np.where((rise >= rise_db) & loud)[0] + lag
    out, last = [], -10 ** 9
    gap = int(spacing_s / 0.002)
    for c in cand:
        if c - last >= gap:
            out.append(c)
            last = c
    return (np.asarray(out, dtype=int) - 1).clip(0) * n2


def attack_db(h: np.ndarray, k: np.ndarray, sr: int) -> float:
    """Median change of the peak in the 10 ms after each hit in h, net of the
    level change over the 50 ms around it. 0 when h has no hits."""
    h2, k2 = _2d(h), _2d(k)
    pos = onsets(h2, sr)
    w, ctx = int(0.010 * sr), int(0.025 * sr)
    d = []
    for p in pos:
        a, b = p, min(len(h2), p + w)
        if b - a < 4:
            continue
        ph = float(np.max(np.abs(h2[a:b])))
        pk = float(np.max(np.abs(k2[a:b])))
        c0, c1 = max(0, p - ctx), min(len(h2), p + ctx)
        rh = float(np.sqrt(np.mean(h2[c0:c1] ** 2)))
        rk = float(np.sqrt(np.mean(k2[c0:c1] ** 2)))
        if ph < 1e-6 or rh < 1e-6 or pk < 1e-9 or rk < 1e-9:
            continue
        d.append(20.0 * np.log10(pk / ph) - 20.0 * np.log10(rk / rh))
    return float(np.median(d)) if d else 0.0


def _octave(x: np.ndarray, sr: int, fc: float) -> np.ndarray:
    lo, hi = fc / np.sqrt(2.0), min(fc * np.sqrt(2.0), 0.49 * sr)
    sos = ss.butter(2, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return ss.sosfiltfilt(sos, _2d(x), axis=0)


def pumping_db(h: np.ndarray, k: np.ndarray, sr: int,
               band: Optional[Tuple[float, Optional[float]]] = None) -> float:
    """Worst spread of the 50 ms level ratio k/h over the octave bands that
    lie a full octave outside `band` (the tool's own band; None = all)."""
    n = max(1, int(FRAME_S * sr))
    worst = 0.0
    for fc in OCTAVES_HZ:
        if fc * np.sqrt(2.0) >= 0.49 * sr:
            continue
        if band is not None:
            lo = band[0] / 2.0
            hi = (band[1] if band[1] is not None else 0.5 * sr) * 2.0
            if lo <= fc <= hi:
                continue
        eh, ek = _rms_db(_octave(h, sr, fc), n), _rms_db(_octave(k, sr, fc), n)
        keep = eh > eh.max() - FLOOR_DB if eh.size else eh
        if int(np.sum(keep)) < 8:
            continue
        r = ek[keep] - eh[keep]
        worst = max(worst, float(np.percentile(r, 95) - np.percentile(r, 5)))
    return worst


def measure(h: np.ndarray, k: np.ndarray, sr: int,
            band: Optional[Tuple[float, Optional[float]]] = None) -> Dict[str, float]:
    n = min(len(h), len(k))
    h, k = np.asarray(h)[:n], np.asarray(k)[:n]
    return {"width_db": round(width_db(h, k), 3),
            "attack_db": round(attack_db(h, k, sr), 3),
            "pumping_db": round(pumping_db(h, k, sr, band), 3)}
