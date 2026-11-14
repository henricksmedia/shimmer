"""Standard mastering: the chain online mastering services run.

DistroKid's Mixea, LANDR, eMastered, Soundboost and the "assistant" in
mastering software all run much the same chain after a gentle tone EQ:

  1. Multiband compressor. Three bands, split by Linkwitz-Riley crossovers
     at 120 Hz and 4 kHz. Each band is turned down a little while it is
     louder than usual for this song, then given back its usual level, so
     the tone stays put and only the loud moments are held in.
  2. Glue compressor. One gentle compressor on the whole mix (2:1, slow
     attack, medium release), about 1-2 dB on the loud parts.
  3. Saturation. A soft tape-style curve, mixed in at 30 %, run at 2x so it
     folds no off-key tones back into the audible range.
  4. Stereo. Mono bass below 120 Hz, so the low end is solid on any
     system. A narrow mix is widened a little above that (at most +1.5 dB
     of side), a wide one is left alone.

Then render() runs the usual loudness gain, peak shaper and true-peak
limiter (master.limiter).

Every level here is set from this song, not from fixed dB: the compressors'
thresholds sit at the song's own loud level in each band, and the
saturation's drive at its own average level. So the chain does the same
amount of work on a quiet mix and a loud one.

Whole song, then windows. plan() reads the whole song once and works out
every gain the compressors will apply, at a 64-sample step. apply() then
uses those gains for any window, so a preview window gets exactly the
gains the export does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np
from scipy.signal import butter, firwin, oaconvolve, sosfilt

# ── Settings, stated once ───────────────────────────────────────────────

XOVER_LOW_HZ = 120.0           # low band | mid band
XOVER_HIGH_HZ = 4000.0         # mid band | high band
MONO_BASS_HZ = 120.0           # below this the side channel is removed

_STEP = 64                     # gains are worked out every this many samples
_LEVEL_S = 0.010               # the level detector averages over 10 ms
_ACTIVE_RANGE_DB = 40.0        # steps quieter than the loudest by this are silence
_MAX_GR_DB = 6.0               # no compressor ever turns down more than this


@dataclass(frozen=True)
class Comp:
    """One compressor's settings. The threshold is not here: it is set from
    the song, `under_db` under the level the song stays below `pct` % of
    the time."""
    ratio: float
    attack_s: float
    release_s: float
    knee_db: float = 6.0
    pct: float = 90.0
    under_db: float = 2.0


# Low band holds the kick and bass together, mid band is gentle (vocals
# keep their life), high band tames hi-hats and sizzle quickly.
BAND_COMPS: Tuple[Comp, ...] = (
    Comp(ratio=2.0, attack_s=0.030, release_s=0.250),
    Comp(ratio=1.5, attack_s=0.015, release_s=0.150),
    Comp(ratio=2.0, attack_s=0.005, release_s=0.100, under_db=3.0),
)
GLUE = Comp(ratio=2.0, attack_s=0.030, release_s=0.300, pct=95.0, under_db=3.0)

# Saturation: tanh at this many times the song's RMS level, mixed in.
SAT_HEADROOM = 4.0             # the curve bends at about RMS + 12 dB
SAT_MIX = 0.3
_SAT_OVERSAMPLE = 2
# Run in 32-bit: twice as fast, and the change it makes is exact to about
# -150 dB, far under anything audible.
_SAT_FIR = firwin(_SAT_OVERSAMPLE * 64 + 1, 0.9 / _SAT_OVERSAMPLE,
                  window=("kaiser", 10.0)).astype(np.float32)

# Width: a mix whose side is quieter than this, against its mid (above the
# mono-bass point), is narrow and gets some side back, half the gap and at
# most WIDTH_MAX_DB. Released stereo masters sit around -9 to -14 dB.
WIDTH_NARROW_DB = -14.0
WIDTH_MAX_DB = 1.5


@dataclass
class Plan:
    """What apply() needs, worked out once from the whole song."""
    sr: int
    n: int                                   # the song's length in samples
    band_gain_db: Tuple[np.ndarray, ...]     # per band, one value per _STEP
    glue_gain_db: np.ndarray
    sat_scale: float                         # the saturation's bend point, linear
    side_gain_db: float                      # width above MONO_BASS_HZ
    summary: Dict[str, Any] = field(default_factory=dict)


# ── Filters ─────────────────────────────────────────────────────────────

def _lr4(kind: str, hz: float, sr: int) -> np.ndarray:
    """A 4th-order Linkwitz-Riley low or high pass: two 2nd-order
    Butterworths in a row. Its low and high halves add back to an all-pass:
    flat in level, so a band split that changes nothing changes no tone."""
    sos = butter(2, hz, btype=kind, fs=sr, output="sos")
    return np.vstack([sos, sos])


def _filt(sos: np.ndarray, x: np.ndarray) -> np.ndarray:
    return sosfilt(sos, x, axis=0)


def split_bands(x: np.ndarray, sr: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Low, mid and high bands. They add up to the input passed through
    two all-passes: the same level at every frequency. The low band goes
    through the upper crossover's all-pass too, so all three line up."""
    lo1, hi1 = _lr4("lowpass", XOVER_LOW_HZ, sr), _lr4("highpass", XOVER_LOW_HZ, sr)
    lo2, hi2 = _lr4("lowpass", XOVER_HIGH_HZ, sr), _lr4("highpass", XOVER_HIGH_HZ, sr)
    low = _filt(lo1, x)
    low = _filt(lo2, low) + _filt(hi2, low)          # all-pass at the upper crossover
    rest = _filt(hi1, x)
    return low, _filt(lo2, rest), _filt(hi2, rest)


# ── Compressor ──────────────────────────────────────────────────────────

def _levels_db(x: np.ndarray, sr: int) -> np.ndarray:
    """The level of x every _STEP samples, both channels linked: the mean
    power over the last _LEVEL_S, in dB."""
    p = np.mean(np.asarray(x, dtype=np.float64) ** 2, axis=1)
    n_steps = int(np.ceil(p.size / _STEP))
    pad = np.zeros(n_steps * _STEP)
    pad[:p.size] = p
    blocks = pad.reshape(n_steps, _STEP).mean(axis=1)
    k = max(1, int(round(_LEVEL_S * sr / _STEP)))
    c = np.cumsum(np.concatenate([np.zeros(k), blocks]))
    avg = (c[k:] - c[:-k]) / k
    return 10.0 * np.log10(np.maximum(avg, 1e-12))


def _threshold_db(levels: np.ndarray, comp: Comp) -> Optional[float]:
    """Where this compressor starts: under the level the loudest part of the
    song reaches. None for a silent signal."""
    top = float(np.max(levels)) if levels.size else -120.0
    if top <= -100.0:
        return None
    active = levels[levels > top - _ACTIVE_RANGE_DB]
    return float(np.percentile(active, comp.pct)) - comp.under_db


def _static_gr_db(levels: np.ndarray, thr: float, comp: Comp) -> np.ndarray:
    """Gain reduction for each level, with a soft knee (negative dB)."""
    slope = 1.0 - 1.0 / comp.ratio
    over = levels - thr
    k = comp.knee_db
    gr = np.where(over <= -k / 2.0, 0.0,
                  np.where(over >= k / 2.0, slope * over,
                           slope * (over + k / 2.0) ** 2 / (2.0 * k)))
    return -np.minimum(gr, _MAX_GR_DB)


def _smooth_gr(target: np.ndarray, sr: int, comp: Comp) -> np.ndarray:
    """Attack and release: the gain moves toward more reduction at the
    attack speed and back at the release speed."""
    dt = _STEP / sr
    att = float(np.exp(-dt / comp.attack_s))
    rel = float(np.exp(-dt / comp.release_s))
    out = np.empty_like(target)
    g = 0.0
    for i, t in enumerate(target.tolist()):
        c = att if t < g else rel
        g = t + c * (g - t)
        out[i] = g
    return out


def _comp_gain(x: np.ndarray, sr: int, comp: Comp, makeup: bool) -> Tuple[np.ndarray, Dict[str, float]]:
    """A compressor's gain for the whole signal, one value per _STEP, and
    what it did. With makeup, the gain the song usually sits at is given
    back, so the band keeps its usual level and only its loud moments come
    down."""
    levels = _levels_db(x, sr)
    thr = _threshold_db(levels, comp)
    if thr is None:
        return np.zeros_like(levels), {"threshold_db": None, "typical_db": 0.0, "most_db": 0.0}
    gain = _smooth_gr(_static_gr_db(levels, thr, comp), sr, comp)
    active = levels > float(np.max(levels)) - _ACTIVE_RANGE_DB
    typical = float(np.median(gain[active])) if np.any(active) else 0.0
    most = float(np.min(gain))
    if makeup:
        gain = gain - typical
    return gain, {"threshold_db": round(thr, 1), "typical_db": round(typical, 2),
                  "most_db": round(most, 2)}


def _gain_at(gain_db: np.ndarray, start: int, n: int) -> np.ndarray:
    """The gain for samples start..start+n, as linear factors, spread
    smoothly between the step points (each at its step's centre)."""
    pos = np.arange(start, start + n, dtype=np.float64)
    centres = np.arange(gain_db.size, dtype=np.float64) * _STEP + (_STEP - 1) / 2.0
    return 10.0 ** (np.interp(pos, centres, gain_db) / 20.0)


# ── Saturation ──────────────────────────────────────────────────────────

def _up(v: np.ndarray) -> np.ndarray:
    z = np.zeros((v.shape[0] * _SAT_OVERSAMPLE, v.shape[1]), dtype=np.float32)
    z[::_SAT_OVERSAMPLE] = v * _SAT_OVERSAMPLE
    return oaconvolve(z, _SAT_FIR[:, None], mode="same", axes=0)


def _down(v: np.ndarray) -> np.ndarray:
    return oaconvolve(v, _SAT_FIR[:, None], mode="same", axes=0)[::_SAT_OVERSAMPLE]


def saturate(x: np.ndarray, scale: float) -> np.ndarray:
    """The soft tape-style curve, mixed in. Only the change the curve makes
    is filtered back down from 2x, so the music itself is never filtered."""
    if scale <= 0.0 or SAT_MIX <= 0.0:
        return x
    u = _up(x)
    s = np.float32(scale)
    change = s * np.tanh(u / s) - u
    return x + SAT_MIX * _down(change).astype(np.float64)


# ── Stereo ──────────────────────────────────────────────────────────────

def stereo(x: np.ndarray, sr: int, side_gain_db: float) -> np.ndarray:
    """Mono bass below MONO_BASS_HZ, and the side above it at side_gain_db.
    The mid goes through the same crossover's all-pass, so mid and side
    stay lined up in time."""
    if x.shape[1] != 2:
        return x
    lo, hi = _lr4("lowpass", MONO_BASS_HZ, sr), _lr4("highpass", MONO_BASS_HZ, sr)
    mid = (x[:, 0] + x[:, 1]) * 0.5
    side = (x[:, 0] - x[:, 1]) * 0.5
    mid = sosfilt(lo, mid) + sosfilt(hi, mid)
    side = sosfilt(hi, side) * 10.0 ** (side_gain_db / 20.0)
    return np.stack([mid + side, mid - side], axis=1)


def _side_gain_db(x: np.ndarray, sr: int) -> Tuple[float, Optional[float]]:
    """The width move for this song, and its side-to-mid level (dB)."""
    if x.shape[1] != 2:
        return 0.0, None
    hi = _lr4("highpass", MONO_BASS_HZ, sr)
    mid = sosfilt(hi, (x[:, 0] + x[:, 1]) * 0.5)
    side = sosfilt(hi, (x[:, 0] - x[:, 1]) * 0.5)
    pm, ps = float(np.mean(mid ** 2)), float(np.mean(side ** 2))
    if pm < 1e-12:
        return 0.0, None
    ratio = 10.0 * np.log10(max(ps, 1e-12) / pm)
    if ratio >= WIDTH_NARROW_DB or ps < 1e-12:
        return 0.0, ratio
    return float(min(WIDTH_MAX_DB, 0.5 * (WIDTH_NARROW_DB - ratio))), ratio


# ── The chain ───────────────────────────────────────────────────────────

def _compress(bands: Tuple[np.ndarray, ...], gains: Tuple[np.ndarray, ...],
              start: int) -> np.ndarray:
    n = bands[0].shape[0]
    out = np.zeros_like(bands[0])
    for b, g in zip(bands, gains):
        out += b * _gain_at(g, start, n)[:, None]
    return out


def plan(x: np.ndarray, sr: int) -> Plan:
    """Work out every gain from the whole song (after the tone EQ, the user
    EQ and the low-cut, before the loudness gain)."""
    return plan_and_run(x, sr)[0]


def plan_and_run(x: np.ndarray, sr: int) -> Tuple[Plan, np.ndarray]:
    """plan(), and the whole song run through the chain, which the plan
    works out on the way: the loudness gain is measured on it."""
    a = np.asarray(x, dtype=np.float64)
    a = a[:, None] if a.ndim == 1 else a
    bands = split_bands(a, sr)
    band_gains, band_info = [], []
    for b, comp in zip(bands, BAND_COMPS):
        g, info = _comp_gain(b, sr, comp, makeup=True)
        band_gains.append(g)
        band_info.append(info)
    mb = _compress(bands, tuple(band_gains), 0)
    glue_gain, glue_info = _comp_gain(mb, sr, GLUE, makeup=False)
    glued = mb * _gain_at(glue_gain, 0, mb.shape[0])[:, None]
    rms = float(np.sqrt(np.mean(glued ** 2))) if glued.size else 0.0
    sat_scale = SAT_HEADROOM * rms if rms > 1e-6 else 0.0
    saturated = saturate(glued, sat_scale)
    side_db, side_ratio = _side_gain_db(saturated, sr)
    summary = {
        "bands_hz": [XOVER_LOW_HZ, XOVER_HIGH_HZ],
        "band_most_db": [i["most_db"] for i in band_info],
        "glue_typical_db": glue_info["typical_db"],
        "glue_most_db": glue_info["most_db"],
        "saturation_mix": SAT_MIX,
        "mono_bass_hz": MONO_BASS_HZ if a.shape[1] == 2 else None,
        "side_to_mid_db": None if side_ratio is None else round(float(side_ratio), 1),
        "width_db": round(side_db, 2),
    }
    p = Plan(sr, a.shape[0], tuple(band_gains), glue_gain, sat_scale, side_db, summary)
    return p, stereo(saturated, sr, side_db)


def apply(x: np.ndarray, sr: int, p: Plan, offset: int = 0) -> np.ndarray:
    """Run the chain on x, which starts `offset` samples into the song."""
    a = np.asarray(x, dtype=np.float64)
    a = a[:, None] if a.ndim == 1 else a
    if a.shape[0] == 0:
        return a
    y = _compress(split_bands(a, sr), p.band_gain_db, offset)
    y = y * _gain_at(p.glue_gain_db, offset, y.shape[0])[:, None]
    y = saturate(y, p.sat_scale)
    return stereo(y, sr, p.side_gain_db)
