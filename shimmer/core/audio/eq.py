"""The user EQ: a list of bands, as filters.

render() runs it as its EQ stage, and the Suggested EQ planner checks its
own moves through it, so the check hears exactly the EQ that will apply
them. Every band is one filters.design(): bells and shelves land on their
setting, passes run one way (filters.py).
"""
from __future__ import annotations

from typing import Iterable, List

import numpy as np

from . import filters

# The screens' band types, and the filter each one is.
KINDS = {"bell": "bell", "low_shelf": "low_shelf", "high_shelf": "high_shelf",
         "highpass": "high_pass", "lowpass": "low_pass", "notch": "notch"}
_GAIN_KINDS = {"bell", "low_shelf", "high_shelf"}


def designs(bands: Iterable, sr: int) -> List[filters.Design]:
    """The filters for the enabled bands that change anything. A band needs
    type, freq_hz, gain_db, q and enabled (settings.EqBand)."""
    out = []
    for b in bands:
        if not b.enabled or b.freq_hz >= 0.49 * sr:
            continue
        kind = KINDS[b.type]
        if kind in _GAIN_KINDS:
            if abs(b.gain_db) < 0.05:
                continue
            gain = b.gain_db
        else:
            gain = float("-inf") if kind == "notch" else 0.0
        out.append(filters.design(kind, b.freq_hz, sr, gain_db=gain, q=b.q))
    return out


def apply(x: np.ndarray, sr: int, bands: Iterable) -> np.ndarray:
    """Run the bands over audio of shape (n,) or (n, channels). float64."""
    y = np.asarray(x, dtype=np.float64)
    for d in designs(bands, sr):
        y = filters.apply(y, sr, d)
    return y
