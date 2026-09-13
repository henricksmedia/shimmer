"""Dynamic EQ: the Harshness and Low-mid build-up cards' fix.

A resonance that comes and goes with the music: a narrow band in 2-5 kHz
that rings out above its neighbours on loud notes (harshness), or a broad
one in 200-500 Hz that swells when the low mids stack up (mud). A static EQ
cut would thin the song all the time; this cuts the band only while it
sticks out.

How it works:

  1. Find, once for the whole song, on the centre: in the card's range, the
     1/6-octave band that most often sits above the line through its
     neighbours (the 90th percentile of its excess over the loud moments),
     then up to `count` such bands at least half an octave apart. A band
     that never sticks out by MIN_FIND_DB is not a resonance, and nothing is
     cut.
  2. Detect, over 20 ms on the centre (Config.detect): as shipped, a band
     compressor, how much louder the found band is than its own
     `compress_pct` percentile level in this song. Both channels get the
     same cut, so the stereo image stays put.
  3. Cut: Amount x `slope` dB for every dB above `threshold_db`, at most
     `max_cut_db` x Amount. It starts LOOKAHEAD_MS early and lets go at
     `release_db_per_s`.
  4. Apply, split-band: the band is taken out with a zero-phase peak filter
     and turned down by the cut; nothing else is touched. With no cut, the
     output is the input.

Every state settles within a few tens of milliseconds, so a preview window
matches the same span of a full render.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage
from scipy import signal as ss

FRAME_S = 0.02
LOUD_PERCENTILE = 30.0          # the finder looks at moments louder than this share
MIN_FIND_DB = 6.0
MIN_APART_OCT = 0.5
SLOPE = 0.75
LOOKAHEAD_MS = 5.0
SMOOTH_MS = 5.0
ACTIVE_DB = 45.0                # quieter than this under the song's loudest: left alone


@dataclass(frozen=True)
class Config:
    key: str
    lo: float
    hi: float
    count: int
    q: float
    spread_oct: float
    threshold_db: float
    max_cut_db: float           # at Amount 100 %
    n_fft: int
    release_db_per_s: float
    # How a moment is judged (step 2):
    #   "neighbours"  the band's excess over its neighbours, less threshold_db
    #   "relative"    that excess over its usual value in this song, less threshold_db
    #   "compress"    the band's level over its compress_pct percentile in this
    #                 song, less threshold_db (a band compressor)
    #   "both"        the smaller of "compress" and "relative": the band is
    #                 loud for this song AND sticks out more than usual
    #   "weighted"    "compress", weighted 0-1 by how far the band sticks
    #                 out over its usual (0 at usual, 1 at weight_db above)
    detect: str = "neighbours"
    compress_pct: float = 70.0
    weight_db: float = 4.0
    # How the finder ranks bands (step 1): "p90" how high a band gets over
    # its neighbours; "swing" how far it rises above its own usual (p90 - p50).
    # "every" skips the finder: every band band_step_oct apart across the
    # range is watched and cut on its own when it sticks out.
    finder: str = "p90"
    slope: float = SLOPE
    band_step_oct: float = 1.0 / 3.0


@dataclass(frozen=True)
class Plan:
    centres_hz: Tuple[float, ...]
    floor_db: float
    typical_db: Tuple[float, ...] = ()   # per centre: usual excess over the neighbours
    loud_db: Tuple[float, ...] = ()      # per centre: compress_pct percentile of its level


def _bands(lo: float, hi: float, sr: int) -> np.ndarray:
    cs = lo / 2.0 * 2.0 ** (np.arange(0, 1 + 6 * np.log2(4 * hi / lo)) / 6.0)
    return cs[cs < 0.45 * sr]


def _band_levels(m: np.ndarray, sr: int, cs: np.ndarray, n_fft: int) -> np.ndarray:
    """1/6-octave band levels in dB, [frames, bands], a batch of frames at a
    time so a long song needs little memory."""
    hop = max(1, int(FRAME_S * sr))
    if m.size < n_fft:
        m = np.pad(m, (0, n_fft - m.size))
    win = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    member = np.zeros((freqs.size, cs.size))
    for i, c in enumerate(cs):
        member[(freqs >= c / 2 ** (1 / 12)) & (freqs < c * 2 ** (1 / 12)), i] = 1.0
    starts = np.arange(0, m.size - n_fft + 1, hop)
    out = np.empty((starts.size, cs.size))
    for k in range(0, starts.size, 256):
        idx = starts[k:k + 256]
        frames = np.stack([m[s:s + n_fft] for s in idx]) * win
        power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
        out[k:k + idx.size] = 10.0 * np.log10(power @ member + 1e-20)
    return out


def _excess(cs: np.ndarray, levels: np.ndarray, lo: float, hi: float) -> Dict[float, np.ndarray]:
    """Each band in [lo, hi]: its level above a line (dB over log frequency)
    through the bands a third to one octave away on both sides."""
    lc = np.log2(cs)
    out = {}
    for i, c in enumerate(cs):
        if not (lo <= c <= hi):
            continue
        d = np.abs(lc - lc[i])
        nb = (d >= 1 / 3) & (d <= 1.0)
        if nb.sum() < 2:
            continue
        design = np.stack([np.ones(int(nb.sum())), lc[nb]], axis=1)
        coef, *_ = np.linalg.lstsq(design, levels[:, nb].T, rcond=None)
        out[float(c)] = levels[:, i] - (coef[0] + coef[1] * lc[i])
    return out


def _mid(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        return a
    return a[:, :2].mean(axis=1) if a.shape[1] >= 2 else a[:, 0]


def _peak(x: np.ndarray, sr: int, f: float, q: float) -> np.ndarray:
    """x through a zero-phase peak filter at f (0 dB at f)."""
    b, a = ss.iirpeak(min(f, 0.45 * sr), q, fs=sr)
    return ss.sosfiltfilt(ss.tf2sos(b, a), x, axis=0)


def _level_db(y: np.ndarray, sr: int) -> np.ndarray:
    n = max(1, int(round(FRAME_S * sr)))
    return 10.0 * np.log10(ndimage.uniform_filter1d(y * y, n, mode="nearest") + 1e-20)


class DynamicEQ:
    """One card's dynamic EQ: plan(), apply() and summary(), as render()'s
    fix tools have."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def with_(self, **changes: Any) -> "DynamicEQ":
        return DynamicEQ(dataclasses.replace(self.cfg, **changes))

    def plan(self, audio: np.ndarray, sr: int) -> Plan:
        """The resonances in the card's range, from the whole song."""
        c = self.cfg
        m = _mid(audio)
        if m.size == 0:
            return Plan((), -200.0)
        cs = _bands(c.lo, c.hi, sr)
        levels = _band_levels(m, sr, cs, c.n_fft)
        total = levels.max(axis=1)
        loud = total > np.percentile(total, LOUD_PERCENTILE)
        ex = _excess(cs, levels, c.lo, c.hi)
        scores: Dict[float, float] = {}
        if loud.any():
            for f, v in ex.items():
                p90 = float(np.percentile(v[loud], 90))
                if p90 >= MIN_FIND_DB:
                    scores[f] = p90 if c.finder == "p90" else p90 - float(np.percentile(v[loud], 50))
        chosen: List[float] = []
        if c.finder == "every":
            k = np.arange(0, int(np.floor(np.log2(c.hi / c.lo) / c.band_step_oct + 1e-9)) + 1)
            chosen = [float(c.lo * 2.0 ** (i * c.band_step_oct)) for i in k]
        for f in sorted(scores, key=scores.get, reverse=True):
            if c.finder == "every" or len(chosen) >= c.count:
                break
            if all(abs(np.log2(f / g)) >= MIN_APART_OCT for g in chosen):
                chosen.append(f)
        level = _level_db(m, sr)
        floor = float(level.max()) - ACTIVE_DB
        step = max(1, int(FRAME_S * sr / 4))
        act = level[::step] > floor
        typical, loudest = [], []
        for f in sorted(chosen):
            lc, ex_t = self._readings(m, sr, f)
            typical.append(float(np.median(ex_t[::step][act])) if act.any() else 0.0)
            loudest.append(float(np.percentile(lc[::step][act], c.compress_pct))
                           if act.any() else 0.0)
        return Plan(tuple(sorted(chosen)), floor, tuple(typical), tuple(loudest))

    def _readings(self, m: np.ndarray, sr: int, f: float) -> Tuple[np.ndarray, np.ndarray]:
        """The band's level at f, and its excess over the average of its two
        neighbours, sample by sample, in dB."""
        c = self.cfg
        lc = _level_db(_peak(m, sr, f, c.q), sr)
        lo = _level_db(_peak(m, sr, f * 2.0 ** -c.spread_oct, c.q), sr)
        hi = _level_db(_peak(m, sr, f * 2.0 ** c.spread_oct, c.q), sr)
        return lc, lc - 0.5 * (lo + hi)

    def cut_db(self, m: np.ndarray, sr: int, p: Plan, f: float, amount: float) -> np.ndarray:
        """The cut in dB at centre f, sample by sample (0 or more)."""
        c = self.cfg
        lc, ex = self._readings(m, sr, f)
        i = p.centres_hz.index(f)
        if c.detect == "relative":
            ex = ex - p.typical_db[i]
        elif c.detect == "compress":
            ex = lc - p.loud_db[i]
        elif c.detect == "both":
            ex = np.minimum(lc - p.loud_db[i], ex - p.typical_db[i])
        elif c.detect == "weighted":
            ex = (lc - p.loud_db[i]) * np.clip((ex - p.typical_db[i]) / c.weight_db, 0.0, 1.0)
        ex = ex - c.threshold_db
        ex[_level_db(m, sr) <= p.floor_db] = 0.0
        a = float(amount)
        cut = np.clip(a * c.slope * ex, 0.0, c.max_cut_db * a)
        k = max(1, int(round(LOOKAHEAD_MS * 1e-3 * sr)))
        cut = ndimage.maximum_filter1d(cut, 2 * k + 1, mode="nearest")
        ramp = np.arange(cut.size, dtype=np.float64) * (c.release_db_per_s / sr)
        cut = np.maximum.accumulate(cut + ramp) - ramp
        cut = ndimage.uniform_filter1d(cut, max(1, int(round(SMOOTH_MS * 1e-3 * sr))), mode="nearest")
        return np.maximum(cut, 0.0)

    def apply(self, x: np.ndarray, sr: int, p: Plan, amount: float, offset: int = 0) -> np.ndarray:
        """Cut each found band while it sticks out. Returns x itself when
        nothing is cut."""
        if amount <= 0.0 or not p.centres_hz or np.asarray(x).shape[0] == 0:
            return x
        a = np.asarray(x, dtype=np.float64)
        two_d = a.ndim == 2
        y = a if two_d else a[:, None]
        m = _mid(y)
        changed = False
        for f in p.centres_hz:
            cut = self.cut_db(m, sr, p, f, amount)
            if not np.any(cut > 1e-3):
                continue
            g = 10.0 ** (-cut / 20.0)
            y = y - (1.0 - g)[:, None] * _peak(y, sr, f, self.cfg.q)
            changed = True
        if not changed:
            return x
        return y if two_d else y[:, 0]

    def summary(self, p: Plan, amount: float) -> Dict[str, Any]:
        return {"tool": "dynamic_eq", "centres_hz": [round(f, 1) for f in p.centres_hz],
                "max_cut_db": round(self.cfg.max_cut_db * float(amount), 1)}


# Chosen on five real songs (docs/STEP6-FIXES.md): the finder picks the band
# that sticks out highest, and a band compressor cuts it by every dB it gets
# louder than its own 70th-percentile level in this song, times `slope`.
# Judging by a fixed excess over the neighbours, or by the band's usual
# excess, removed less; watching every band cost far more music.
#
# The top of the Amount slider, set from measured cost (GOALS.md rule 2):
# tested at 0.5 dB per dB (9 dB deepest for Harshness, 6 dB for Low-mid
# build-up), the worst clean song reached the 0.10-sone limit at 56 % of
# that for Harshness and 66 % for Low-mid build-up, so 100 % on the slider
# is 0.28 dB per dB and 5.1 dB deepest, and 0.33 dB per dB and 4.0 dB
# deepest.
HARSHNESS = DynamicEQ(Config("harshness", 2000.0, 5000.0, count=2, q=3.0, spread_oct=0.75,
                             threshold_db=0.0, max_cut_db=5.1, n_fft=2048,
                             release_db_per_s=100.0, detect="compress", compress_pct=70.0,
                             slope=0.28))
MUD = DynamicEQ(Config("mud", 200.0, 500.0, count=1, q=1.4, spread_oct=1.0,
                       threshold_db=0.0, max_cut_db=4.0, n_fft=8192, release_db_per_s=60.0,
                       detect="compress", compress_pct=70.0, slope=0.33))
