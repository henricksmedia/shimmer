"""Loudness gains: one track, or a whole record.

The gain that reaches a Loudness target is worked out once, from the whole
track, and applied as one static gain. The limiter then only trims peaks.
A preview window uses the whole track's gain too, so it plays at the level
the export will have.
"""
from __future__ import annotations

import math
from typing import Iterable, List


def gain_to_target(lufs: float, target_lufs: float) -> float:
    """The gain in dB that moves `lufs` to `target_lufs`. 0 for silence."""
    if not math.isfinite(lufs) or lufs < -70.0:
        return 0.0
    return float(target_lufs - lufs)


def album_gains(lufs_per_track: Iterable[float], target_lufs: float) -> List[float]:
    """One gain for the whole record: the loudest track lands on the target,
    and every track keeps its distance from it. Silent tracks are ignored
    when finding the loudest."""
    levels = [float(v) for v in lufs_per_track]
    audible = [v for v in levels if math.isfinite(v) and v >= -70.0]
    gain = float(target_lufs - max(audible)) if audible else 0.0
    return [gain] * len(levels)
