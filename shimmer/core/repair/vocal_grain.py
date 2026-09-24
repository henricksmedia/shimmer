"""Voice de-noise: the Vocal grain card's fix.

A grainy hiss that rides on an AI lead vocal, strongest at 4-8 kHz: a
steady floor of hiss, a hiss that rises and falls with the voice, and a
grain of sharp little spikes in time and pitch. It sits in the centre, with
the voice. The Shimmer card's model does not see it (it looks for flicker)
and neither does the de-esser (it waits for a burst). Found by ear on the
author's songs, listening rounds 5-14 (docs/CHAIN-AUDIT.md, §6 item 13).

How it works, on the centre (mid) of the mix only; the sides are untouched:

  1. Steady floor (round 5, "C"). Above 3.5 kHz, each pitch's quietest
     level over the whole song (its 10th percentile) is the floor; the fix
     takes FLOOR_OVER times it out, keeping at least FLOOR_KEEP.
  2. Moving floor (round 8, "V4"). In 4-8 kHz, the floor is worked out
     again every MOVING_S seconds (a running 20th percentile), so it follows
     the voice; MOVING_OVER times it comes out, keeping at least MOVING_KEEP.
  3. Grain (round 8, "V3"). In 4-8 kHz, each spot is compared with its
     neighbours (7 bins by 9 frames); a spot more than GRAIN_CAP_DB above
     them is pulled back to it.

Steps 2 and 3 fade in from 3 kHz and out by 10 kHz. At Amount 100 % the
fix uses the author's "extra strong" setting (round 13); a lower Amount
takes that cut in dB times the Amount, so 50 % is half the cut in dB.

All three steps read the whole song, so plan() works out the cut for every
frame once and keeps it. A preview window then only redoes the cheap last
step, and gets the same cut as the full render: frames sit on a HOP grid
counted from the start of the song.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import numpy as np
from scipy import ndimage as nd
from scipy import signal as ss

NPER = 2048
HOP = 512
TOP_FROM_HZ = 3500.0           # step 1 acts above this
BAND_HZ = (4000.0, 8000.0)     # steps 2 and 3 act fully here
FADE_HZ = (3000.0, 10000.0)    # ... and fade out by these
FLOOR_PCT, FLOOR_OVER, FLOOR_KEEP = 10.0, 2.0, 0.15
MOVING_S, MOVING_PCT, MOVING_OVER, MOVING_KEEP = 2.0, 20.0, 4.0, 0.06
GRAIN_SIZE, GRAIN_CAP_DB = (7, 9), 0.75
SMOOTH = (3, 5)                # bins x frames, so the gains do not warble
_DEEPEST_DB = 40.0             # no spot is cut further than this
SLOW_PLAN = True               # about 20-40 s for a 4-minute song


@dataclass(frozen=True, eq=False)
class Plan:
    """The cut in dB (0 or less) at Amount 100 %, for the centre's bins from
    `first_bin` up, every frame of the song ([bins, frames], float16)."""
    first_bin: int
    cut_db: Optional[np.ndarray]


def _mid(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    a = a[:, None] if a.ndim == 1 else a
    return a.mean(axis=1) if a.shape[1] >= 2 else a[:, 0]


def _stft(m: np.ndarray, sr: int) -> np.ndarray:
    return ss.stft(m, fs=sr, nperseg=NPER, noverlap=NPER - HOP)[2]


def _fade(f: np.ndarray) -> np.ndarray:
    """1 across BAND_HZ, falling to 0 at FADE_HZ."""
    up = np.clip((f - FADE_HZ[0]) / (BAND_HZ[0] - FADE_HZ[0]), 0.0, 1.0)
    down = np.clip((FADE_HZ[1] - f) / (FADE_HZ[1] - BAND_HZ[1]), 0.0, 1.0)
    return np.minimum(up, down)[:, None].astype(np.float32)


def plan(audio: np.ndarray, sr: int,
         step: Optional[Callable[[float], None]] = None) -> Plan:
    """Work out the cut for the whole song. `step(fraction)` hears how far
    it has got and may raise to stop the work."""
    m = _mid(audio)
    f = np.fft.rfftfreq(NPER, 1.0 / sr)
    first = int(np.searchsorted(f, FADE_HZ[0]))
    if m.size < NPER or first >= f.size:
        return Plan(first, None)
    f = f[first:]
    P = (np.abs(_stft(m, sr)[first:]) ** 2 + 1e-20).astype(np.float32)
    if step is not None:
        step(0.1)

    # 1. The steady floor, above TOP_FROM_HZ.
    floor = np.percentile(P, FLOOR_PCT, axis=1, keepdims=True)
    g = nd.uniform_filter(np.maximum(FLOOR_KEEP, 1.0 - FLOOR_OVER * floor / P), size=SMOOTH)
    g[f < TOP_FROM_HZ] = 1.0
    P *= g ** 2
    if step is not None:
        step(0.3)

    # 2. The moving floor, faded in across FADE_HZ.
    band = f < FADE_HZ[1]
    fade = _fade(f[band])
    frames = max(3, int(round(MOVING_S * sr / HOP)))
    moving = nd.percentile_filter(P[band], MOVING_PCT, size=(1, frames), mode="nearest")
    g2 = nd.uniform_filter(np.maximum(MOVING_KEEP, 1.0 - MOVING_OVER * moving / P[band]),
                           size=SMOOTH)
    g2 = 1.0 - fade * (1.0 - g2)
    P[band] *= g2 ** 2
    g[band] *= g2
    if step is not None:
        step(0.7)

    # 3. The grain: spots standing above their neighbours, pulled back.
    L = 10.0 * np.log10(P[band])
    spike = L - nd.median_filter(L, size=GRAIN_SIZE, mode="nearest")
    g3 = 10.0 ** (-np.maximum(0.0, spike - GRAIN_CAP_DB) / 20.0)
    g[band] *= 1.0 - fade * (1.0 - g3)
    if step is not None:
        step(1.0)

    cut = np.clip(20.0 * np.log10(np.maximum(g, 1e-6)), -_DEEPEST_DB, 0.0)
    return Plan(first, cut.astype(np.float16))


def removed(x: np.ndarray, sr: int, p: Plan, amount: float, offset: int = 0) -> np.ndarray:
    """What the fix takes out of the centre of x, as a mono signal the length
    of x. `offset` is x's first sample's place in the song."""
    m = _mid(x)
    n = m.size
    pad = int(offset) % HOP
    k0 = (int(offset) - pad) // HOP
    seg = np.concatenate([np.zeros(pad), m]) if pad else m
    Z = _stft(seg, sr)
    cut = np.zeros((Z.shape[0] - p.first_bin, Z.shape[1]), dtype=np.float32)
    have = p.cut_db[:, k0:k0 + Z.shape[1]]
    cut[:, :have.shape[1]] = have
    keep = np.ones(Z.shape, dtype=np.float32)
    keep[p.first_bin:] = 10.0 ** (float(amount) * cut / 20.0)
    y = ss.istft(Z * (1.0 - keep), fs=sr, nperseg=NPER, noverlap=NPER - HOP)[1]
    out = np.zeros(n)
    y = y[pad:pad + n]
    out[:y.size] = y
    return out


def apply(x: np.ndarray, sr: int, p: Plan, amount: float, offset: int = 0) -> np.ndarray:
    """Take the grain and hiss out of the centre of x at `amount` (0-1).
    Returns x itself when nothing is cut."""
    if amount <= 0.0 or p.cut_db is None or np.asarray(x).shape[0] == 0:
        return x
    r = removed(x, sr, p, amount, offset)
    a = np.asarray(x, dtype=np.float64)
    return a - (r[:, None] if a.ndim == 2 else r)


def summary(p: Plan, amount: float) -> Dict[str, Any]:
    return {"tool": "voice_denoise", "band_hz": [BAND_HZ[0], BAND_HZ[1]],
            "mode": "centre", "amount": round(float(amount), 2)}
