"""De-esser: the Sibilance card's fix.

Sharp, piercing "s", "sh", "t" and "ch" in a bright AI vocal: bursts of
energy in about 5-9 kHz, one per consonant, that the song's loudness
mastering then pushes up further. The fix turns the 4.5-10 kHz band down
while a consonant sticks out, and leaves it alone the rest of the time. It
runs before mastering, so a spike is gone before the loudness gain raises
it.

What the 1.x de-esser got wrong (it measured -2 % on centred sibilance,
docs/ARCHITECTURE.md §8), and what this one does instead:

- It cleaned the centre at 0.2x, the part where the lead vocal is. Here
  the centre gets the full cut and the sides half.
- It saw only the band above its 4.5 kHz crossover, so its 1-4 kHz
  reference was nearly empty. Here the detector reads the whole signal.
- It backed off on hits, and "t" and "ch" are hits. Here nothing is gated.

On a full mix, brightness alone cannot tell an "s" from a hi-hat: on five
real songs, a detector that cut whenever the band rose 3 dB above the
song's usual brightness acted a third of the time and took 0.15 sones of
music (the limit is 0.10). Two things a lead vocal's consonant has that the
song's cymbals mostly do not, measured on those songs:
it jumps above the brightness around it, and it is more centred than the
song's top end usually is. The detector asks for both (docs/STEP6-FIXES.md
has the measurements).

How it works:

  1. Once for the whole song (Plan): its usual brightness on the centre
     (4.5-10 kHz against 500 Hz-4 kHz, dB, median over the moments music
     plays) and how centred its 4.5-10 kHz band usually is (centre against
     sides, dB).
  2. Every 5 ms: how far the brightness jumps above the higher of the
     song's usual and its own median over the surrounding 300 ms, less
     THRESHOLD_DB; weighted 0-1 by how much more centred the band is than
     usual (CENTRE_FROM_DB to CENTRE_FROM_DB + CENTRE_SPAN_DB). A band more
     than 20 dB under the vowel (BRIGHT_FLOOR_DB) never counts.
  3. Cut: Amount x SLOPE dB for every dB of that, at most Amount x
     MAX_CUT_DB. It starts LOOKAHEAD_MS early, so the sharp start of a "t"
     is caught, and lets go at RELEASE_DB_PER_S.
  4. Apply, split-band: the 4.5-10 kHz band is taken out with a zero-phase
     band-pass and turned down by the cut, the sides by SIDE_SHARE of it in
     dB; nothing else is touched. With no cut, the output is the input.

The readings sit on a 5 ms grid counted from the start of the song, and
every state settles within 300 ms, so a preview window matches the same
span of a full render (the render's 1 s lead-in covers it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
from scipy import ndimage
from scipy import signal as ss

BAND_HZ = (4500.0, 10000.0)    # detected and cut: where "s", "t" and "ch" live
REF_HZ = (500.0, 4000.0)       # the vowel and the rest of the mix around it
BAND_ORDER = 3
ENV_MS = 5.0
STEP_MS = 5.0                  # one reading every 5 ms, counted from the song's start
LOCAL_MS = 300.0               # a consonant is judged against the brightness around it
THRESHOLD_DB = 3.0
CENTRE_FROM_DB = 2.0           # more centred than usual by this much: starts to count
CENTRE_SPAN_DB = 12.0          # ... and counts fully this much further
MONO_DB = 20.0                 # sides this far under the centre: the song has no real sides
BRIGHT_FLOOR_DB = -20.0        # a band this far under the vowel is too quiet to matter
# The top of the Amount slider, set from measured cost (GOALS.md rule 2):
# at 0.75 dB per dB and 12 dB deepest, the brightest clean song ("Hey")
# lost 0.148 sones; it stays at the 0.10 limit at 60 % of that, so 100 % on
# the slider was 0.45 dB per dB and 7.2 dB deepest (docs/STEP6-FIXES.md).
# Measured again the way the app runs, planned from the whole song, "Hey"
# lost 0.107 there, so the top is now 90 % of it (0.098 at worst,
# docs/CHAIN-AUDIT.md, plan A item 1).
SLOPE = 0.405                  # dB of cut per dB of excess, at Amount 100 %
MAX_CUT_DB = 6.5               # at Amount 100 %
SIDE_SHARE = 0.5               # the sides get this share of the centre's cut, in dB
LOOKAHEAD_MS = 2.0
RELEASE_DB_PER_S = 200.0       # 10 dB of cut lets go in 50 ms
SMOOTH_MS = 1.0
ACTIVE_DB = 45.0               # quieter than this under the song's loudest: left alone


@dataclass(frozen=True)
class Plan:
    """What the de-esser needs from the whole song."""
    baseline_db: float              # usual brightness: centre 4.5-10 kHz vs 500 Hz-4 kHz
    centred_db: Optional[float]     # usual centre-vs-sides of 4.5-10 kHz; None for mono
    floor_db: float                 # below this level (centre, 500 Hz-10 kHz) nothing is cut


def _sos(band: Tuple[float, float], sr: int) -> np.ndarray:
    lo, hi = band
    return ss.butter(BAND_ORDER, [lo, min(hi, 0.45 * sr)], btype="bandpass", fs=sr, output="sos")


def _mid_side(x: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray], np.ndarray]:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = a[:, None]
    if a.shape[1] >= 2:
        return 0.5 * (a[:, 0] + a[:, 1]), 0.5 * (a[:, 0] - a[:, 1]), a
    return a[:, 0], None, a


def _level_db(y: np.ndarray, sr: int) -> np.ndarray:
    n = max(1, int(round(ENV_MS * 1e-3 * sr)))
    return 10.0 * np.log10(ndimage.uniform_filter1d(y * y, n, mode="nearest") + 1e-20)


def _readings(m: np.ndarray, s: Optional[np.ndarray], sr: int):
    """The centre's 4.5-10 kHz band, and per sample: brightness, centred,
    and the level that decides whether music plays."""
    hi = ss.sosfiltfilt(_sos(BAND_HZ, sr), m)
    lh = _level_db(hi, sr)
    lr = _level_db(ss.sosfiltfilt(_sos(REF_HZ, sr), m), sr)
    centred = None if s is None else lh - _level_db(ss.sosfiltfilt(_sos(BAND_HZ, sr), s), sr)
    return hi, lh - lr, centred, np.maximum(lh, lr)


def plan(audio: np.ndarray, sr: int) -> Plan:
    """The song's usual brightness and centring, and the level below which
    nothing is cut. Measures only."""
    m, s, _ = _mid_side(audio)
    if m.size == 0:
        return Plan(0.0, None, -200.0)
    _, bright, centred, level = _readings(m, s, sr)
    step = max(1, int(round(STEP_MS * 1e-3 * sr)))
    floor = float(level.max()) - ACTIVE_DB
    act = level[::step] > floor
    if not np.any(act):
        return Plan(0.0, None, floor)
    usual_c = None if centred is None else float(np.median(centred[::step][act]))
    return Plan(float(np.median(bright[::step][act])), usual_c, floor)


def _local_median(v: np.ndarray, sr: int, offset: int) -> np.ndarray:
    """v's median over the surrounding LOCAL_MS, read on a grid counted from
    the start of the song (so a window and a full render agree)."""
    step = max(1, int(round(STEP_MS * 1e-3 * sr)))
    first = (-int(offset)) % step
    grid = np.arange(first, v.size, step)
    if grid.size == 0:
        return v.copy()
    med = ndimage.median_filter(v[grid], int(LOCAL_MS / STEP_MS) | 1, mode="nearest")
    return np.interp(np.arange(v.size), grid, med)


def cut_db(m: np.ndarray, s: Optional[np.ndarray], sr: int, p: Plan, amount: float,
           offset: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """The centre's cut in dB, sample by sample (0 or more), and the
    centre's 4.5-10 kHz band it applies to."""
    hi, bright, centred, level = _readings(m, s, sr)
    excess = bright - np.maximum(p.baseline_db, _local_median(bright, sr, offset)) - THRESHOLD_DB
    if centred is not None and p.centred_db is not None and p.centred_db < MONO_DB:
        excess = excess * np.clip((centred - p.centred_db - CENTRE_FROM_DB) / CENTRE_SPAN_DB,
                                  0.0, 1.0)
    excess[(level <= p.floor_db) | (bright < BRIGHT_FLOOR_DB)] = 0.0
    a = float(amount)
    c = np.clip(a * SLOPE * excess, 0.0, a * MAX_CUT_DB)
    # Look ahead and hold, then let go at a steady rate: the cut is the
    # highest of every earlier cut less what has let go since, a running
    # maximum (exact, so a window and a full render agree).
    k = max(1, int(round(LOOKAHEAD_MS * 1e-3 * sr)))
    c = ndimage.maximum_filter1d(c, 2 * k + 1, mode="nearest")
    ramp = np.arange(c.size, dtype=np.float64) * (RELEASE_DB_PER_S / sr)
    c = np.maximum.accumulate(c + ramp) - ramp
    c = ndimage.uniform_filter1d(c, max(1, int(round(SMOOTH_MS * 1e-3 * sr))), mode="nearest")
    return np.maximum(c, 0.0), hi


def apply(x: np.ndarray, sr: int, p: Plan, amount: float, offset: int = 0) -> np.ndarray:
    """De-ess x at `amount` (0-1). `offset` is x's first sample's place in
    the song. Returns x itself when nothing is cut."""
    if amount <= 0.0 or np.asarray(x).shape[0] == 0:
        return x
    m, s, a = _mid_side(x)
    c, m_hi = cut_db(m, s, sr, p, amount, offset)
    if not np.any(c > 1e-3):
        return x
    m2 = m - (1.0 - 10.0 ** (-c / 20.0)) * m_hi
    y = a.copy()
    if s is None:
        y[:, 0] = m2
        return y
    s2 = s - (1.0 - 10.0 ** (-SIDE_SHARE * c / 20.0)) * ss.sosfiltfilt(_sos(BAND_HZ, sr), s)
    y[:, 0] = m2 + s2
    y[:, 1] = m2 - s2
    return y


def summary(p: Plan, amount: float) -> Dict[str, Any]:
    return {"tool": "deesser", "band_hz": list(BAND_HZ),
            "max_cut_db": round(MAX_CUT_DB * float(amount), 1),
            "baseline_db": round(p.baseline_db, 2)}
