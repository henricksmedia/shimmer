"""The tone curve: how far to move each band toward a tone target.

The target is an input, never a constant here. The old one changed four
times on belief (docs/ARCHITECTURE.md §3); Step 5 decides where targets come
from (reference tracks, genre targets) and passes them in.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def tone_curve(measured_db, target_db, freqs_hz, strength: float = 1.0,
               max_boost_db: float = 2.0, max_cut_db: float = 3.0,
               cutoff_hz: Optional[float] = None, deadband_db: float = 0.0) -> np.ndarray:
    """Per-band correction in dB, applied as EQ.

    measured_db   the song's level in each band, relative
    target_db     the target's level in each band, on the same scale
    freqs_hz      each band's centre
    strength      0 = flat, 1 = the full move (within the limits)
    max_boost_db  no band is raised more than this
    max_cut_db    no band is lowered more than this
    cutoff_hz     the song's bandwidth cutoff: nothing at or above 90 % of
                  it is boosted, because there is nothing there but noise
    deadband_db   differences smaller than this are left alone
    """
    measured = np.asarray(measured_db, dtype=np.float64)
    target = np.asarray(target_db, dtype=np.float64)
    freqs = np.asarray(freqs_hz, dtype=np.float64)
    diff = target - measured
    if deadband_db > 0.0:
        diff = np.sign(diff) * np.maximum(0.0, np.abs(diff) - deadband_db)
    curve = np.clip(float(strength) * diff, -abs(max_cut_db), abs(max_boost_db))
    if cutoff_hz:
        above = freqs >= 0.9 * float(cutoff_hz)
        curve[above] = np.minimum(curve[above], 0.0)
    return curve
