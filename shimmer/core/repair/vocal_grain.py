"""Voice de-noise: the Vocal grain card's fix.

A grainy hiss that rides on an AI lead vocal, strongest at 4-8 kHz: a
steady floor of hiss, a hiss that rises and falls with the voice, and a
grain of sharp little spikes in time and pitch. It sits in the centre, with
the voice. The Shimmer card's model does not see it (it looks for flicker)
and neither does the de-esser (it waits for a burst). Found by ear on the
author's songs, listening rounds 5-14 (docs/CHAIN-AUDIT.md, §6 item 13).

It works one of two ways (the card's mode, catalog.Card.modes):

- centre: on the centre (mid) of the mix, where the lead vocal sits; the
  sides are untouched. Needs nothing extra.
- vocal: on the vocal alone, split out by the Remix tab's splitter, each
  channel on its own; what it takes from the vocal is taken from the song.
  More precise when cymbals share the centre with the voice. render()
  fetches the vocal (render._vocal_stem); without the splitter it falls
  back to centre and says so.

The same three steps run either way:

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
from typing import Any, Callable, Dict, Optional, Tuple

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
SLOW_PLAN = True               # a 4-minute song: about 10 s on the centre; vocal
                               # mode adds the split (about 70 s the first time
                               # on an RTX 4070, then cached) and 20 s more
STEM_MODES = ("vocal",)        # modes that need the song's vocal (render fetches it)


@dataclass(frozen=True, eq=False)
class Plan:
    """The cut in dB (0 or less) at Amount 100 %, for the bins from
    `first_bin` up, every frame of the song ([bins, frames], float16): one
    for the centre, or one per channel of the vocal. `vocal` is the vocal
    itself in vocal mode (the song's length and rate), else None. `note`
    says why vocal mode fell back to centre."""
    first_bin: int
    cut_db: Tuple[np.ndarray, ...]
    mode: str = "centre"
    vocal: Optional[np.ndarray] = None
    note: str = ""


def _mid(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    a = a[:, None] if a.ndim == 1 else a
    return a.mean(axis=1) if a.shape[1] >= 2 else a[:, 0]


def _stft(m: np.ndarray, sr: int) -> np.ndarray:
    return ss.stft(m, fs=sr, nperseg=NPER, noverlap=NPER - HOP)[2]


def _first_bin(sr: int) -> int:
    return int(np.searchsorted(np.fft.rfftfreq(NPER, 1.0 / sr), FADE_HZ[0]))


def _fade(f: np.ndarray) -> np.ndarray:
    """1 across BAND_HZ, falling to 0 at FADE_HZ."""
    up = np.clip((f - FADE_HZ[0]) / (BAND_HZ[0] - FADE_HZ[0]), 0.0, 1.0)
    down = np.clip((FADE_HZ[1] - f) / (FADE_HZ[1] - BAND_HZ[1]), 0.0, 1.0)
    return np.minimum(up, down)[:, None].astype(np.float32)


def plan(audio: np.ndarray, sr: int,
         step: Optional[Callable[[float], None]] = None,
         vocal: Optional[np.ndarray] = None, note: str = "") -> Plan:
    """Work out the cut for the whole song: on its centre, or with `vocal`
    (the song's vocal, same length and rate) on each of the vocal's
    channels. `note` is kept to say why a vocal-mode plan is on the centre.
    `step(fraction)` hears how far it has got and may raise to stop."""
    first = _first_bin(sr)
    if vocal is None:
        m = _mid(audio)
        if m.size < NPER:
            return Plan(first, (), note=note)
        return Plan(first, (_cut(m, sr, step),), note=note)
    v = np.asarray(vocal, dtype=np.float32)
    v = v[:, None] if v.ndim == 1 else v
    n = v.shape[1]
    if v.shape[0] < NPER:
        return Plan(first, (), "vocal", v)
    cuts = tuple(_cut(v[:, c].astype(np.float64), sr,
                      None if step is None else (lambda fr, c=c: step((c + fr) / n)))
                 for c in range(n))
    return Plan(first, cuts, "vocal", v)


@dataclass(frozen=True, eq=False)
class Steps:
    """The three steps' gains for one signal, from the first bin up: `g1`
    the steady floor ([bins, frames]); `g2` the moving floor and `g3` the
    grain, each already faded, for the bins in `band` (under FADE_HZ's
    top). `f` holds the bins' frequencies and `power` the signal's power
    before any step. The Vocal grain detector reads them apart
    (analyze/detectors.py)."""
    f: np.ndarray
    power: np.ndarray
    band: np.ndarray
    g1: np.ndarray
    g2: np.ndarray
    g3: np.ndarray


def steps(m: np.ndarray, sr: int, step: Optional[Callable[[float], None]] = None) -> Steps:
    """The three steps on one signal (see the module's docstring)."""
    first = _first_bin(sr)
    f = np.fft.rfftfreq(NPER, 1.0 / sr)[first:]
    P0 = (np.abs(_stft(m, sr)[first:]) ** 2 + 1e-20).astype(np.float32)
    P = P0.copy()
    if step is not None:
        step(0.1)

    # 1. The steady floor, above TOP_FROM_HZ.
    floor = np.percentile(P, FLOOR_PCT, axis=1, keepdims=True)
    g1 = nd.uniform_filter(np.maximum(FLOOR_KEEP, 1.0 - FLOOR_OVER * floor / P), size=SMOOTH)
    g1[f < TOP_FROM_HZ] = 1.0
    P *= g1 ** 2
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
    if step is not None:
        step(0.7)

    # 3. The grain: spots standing above their neighbours, pulled back.
    L = 10.0 * np.log10(P[band])
    spike = L - nd.median_filter(L, size=GRAIN_SIZE, mode="nearest")
    g3 = 1.0 - fade * (1.0 - 10.0 ** (-np.maximum(0.0, spike - GRAIN_CAP_DB) / 20.0))
    if step is not None:
        step(1.0)
    return Steps(f, P0, band, g1, g2, g3)


def _cut(m: np.ndarray, sr: int, step: Optional[Callable[[float], None]]) -> np.ndarray:
    """The three steps on one signal: its cut in dB from the first bin up."""
    s = steps(m, sr, step)
    g = s.g1.copy()
    g[s.band] *= s.g2
    g[s.band] *= s.g3
    cut = np.clip(20.0 * np.log10(np.maximum(g, 1e-6)), -_DEEPEST_DB, 0.0)
    return cut.astype(np.float16)


def _taken(sig: np.ndarray, cut_db: np.ndarray, first: int, sr: int, amount: float,
           n: int, pad: int, k0: int) -> np.ndarray:
    """What the cut takes out of `sig` (which starts `pad` samples before
    the window), as n samples. Frames sit on the song's HOP grid."""
    Z = _stft(sig, sr)
    cut = np.zeros((Z.shape[0] - first, Z.shape[1]), dtype=np.float32)
    have = cut_db[:, k0:k0 + Z.shape[1]]
    cut[:, :have.shape[1]] = have
    keep = np.ones(Z.shape, dtype=np.float32)
    keep[first:] = 10.0 ** (float(amount) * cut / 20.0)
    y = ss.istft(Z * (1.0 - keep), fs=sr, nperseg=NPER, noverlap=NPER - HOP)[1][pad:pad + n]
    out = np.zeros(n)
    out[:y.size] = y
    return out


def removed(x: np.ndarray, sr: int, p: Plan, amount: float, offset: int = 0) -> np.ndarray:
    """What the fix takes out of x, as (samples, channels). `offset` is x's
    first sample's place in the song."""
    a = np.asarray(x, dtype=np.float64)
    a = a[:, None] if a.ndim == 1 else a
    n, off = a.shape[0], int(offset)
    pad = off % HOP
    k0 = (off - pad) // HOP
    if p.mode == "vocal" and p.vocal is not None:
        out = np.zeros_like(a)
        for c in range(a.shape[1]):
            vc = p.vocal[:, min(c, p.vocal.shape[1] - 1)]
            seg = np.zeros(pad + n)
            piece = vc[off - pad:off + n].astype(np.float64)
            seg[:piece.size] = piece
            out[:, c] = _taken(seg, p.cut_db[min(c, len(p.cut_db) - 1)], p.first_bin, sr,
                               amount, n, pad, k0)
        return out
    m = a.mean(axis=1)
    seg = np.concatenate([np.zeros(pad), m]) if pad else m
    r = _taken(seg, p.cut_db[0], p.first_bin, sr, amount, n, pad, k0)
    return np.repeat(r[:, None], a.shape[1], axis=1)


def apply(x: np.ndarray, sr: int, p: Plan, amount: float, offset: int = 0) -> np.ndarray:
    """Take the grain and hiss out of x at `amount` (0-1). Returns x itself
    when nothing is cut."""
    if amount <= 0.0 or not p.cut_db or np.asarray(x).shape[0] == 0:
        return x
    a = np.asarray(x, dtype=np.float64)
    r = removed(a, sr, p, amount, offset)
    return a - (r if a.ndim == 2 else r[:, 0])


def summary(p: Plan, amount: float) -> Dict[str, Any]:
    out: Dict[str, Any] = {"tool": "voice_denoise", "band_hz": [BAND_HZ[0], BAND_HZ[1]],
                           "mode": p.mode, "amount": round(float(amount), 2)}
    if p.note:
        out["note"] = p.note
    return out
