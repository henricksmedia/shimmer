"""Level dips: where the level drops well under the rest of the song, then
comes back.

This is a measurement, not advice. A dip can be a section change, a
breakdown, a held note or the spot where a song ran on too long; level alone
cannot tell them apart, and the music is still playing in most of them. The
Trim card shows dips as pins the handles snap to, so a cut lands on the
exact low point. The user decides where the song ends (the cut is apply_trim
in edges.py, the fade is apply_fades). Nothing here edits audio.

How a dip is found, on a 100 ms RMS level:
  1. The song's normal level is the median frame level.
  2. A dip is a stretch at least DIP_DB under that level.
  3. The pin goes on the LAST frame within LAST_DB of the dip's lowest
     frame, right before the level climbs again.
  4. The level has to come back: within RISE_S it climbs at least RISE_DB
     above the pin. A drop the song never returns from is its real ending.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

FRAME_S = 0.1        # RMS frame length
DIP_DB = 8.0         # how far under the song's normal level a dip must go
LAST_DB = 3.0        # "quiet" inside a dip: within this of its quietest frame
RISE_S = 2.5         # how soon the level must come back
RISE_DB = 6.0        # and by how much
MIN_GAP_S = 5.0      # suggestions at least this far apart
EDGE_S = 5.0         # skip the first and last few seconds of the file
START_FRAC = 0.25    # an ending in the first quarter of a song is no ending
MAX_POINTS = 3


def frame_levels(x: np.ndarray, sr: int, frame_s: float = FRAME_S) -> np.ndarray:
    """RMS level in dBFS per frame, all channels together."""
    y = x if x.ndim == 1 else x.mean(axis=1)
    n = int(round(frame_s * sr))
    if n < 1 or y.shape[0] < n:
        return np.zeros(0)
    k = y.shape[0] // n
    frames = y[:k * n].astype(np.float64).reshape(k, n)
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return 20.0 * np.log10(rms + 1e-9)


def level_dips(x: np.ndarray, sr: int, max_points: int = MAX_POINTS) -> List[Dict[str, Any]]:
    """Up to `max_points` level dips, deepest first.

    Each is {"at_s", "level_db", "dip_db", "rise_db"}: where the pin goes,
    the level there, how far under the song's normal level the dip goes, and
    how far the level rises after it.
    """
    db = frame_levels(x, sr)
    if db.size < 10:
        return []
    dur = db.size * FRAME_S
    normal = float(np.median(db))
    quiet = db < normal - DIP_DB
    rise_n = max(1, int(round(RISE_S / FRAME_S)))
    lo = int(max(EDGE_S, START_FRAC * dur) / FRAME_S)
    hi = int((dur - EDGE_S) / FRAME_S)

    found: List[Dict[str, Any]] = []
    i = 0
    while i < db.size:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < db.size and quiet[j]:
            j += 1
        # Dip is frames [i, j). Its quietest frame, then the last frame
        # still within LAST_DB of it.
        seg = db[i:j]
        floor = float(seg.min())
        near = np.nonzero(seg <= floor + LAST_DB)[0]
        k = i + int(near[-1])
        after = db[k + 1:k + 1 + rise_n]
        if lo <= k < hi and after.size:
            rise = float(after.max() - db[k])
            if rise >= RISE_DB:
                found.append({
                    # End of the frame: the cut keeps that frame.
                    "at_s": round((k + 1) * FRAME_S, 2),
                    "level_db": round(float(db[k]), 1),
                    "dip_db": round(normal - floor, 1),
                    "rise_db": round(rise, 1),
                })
        i = j

    found.sort(key=lambda p: -p["dip_db"])
    kept: List[Dict[str, Any]] = []
    for p in found:
        if all(abs(p["at_s"] - q["at_s"]) >= MIN_GAP_S for q in kept):
            kept.append(p)
        if len(kept) >= max_points:
            break
    return kept
