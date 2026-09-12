"""render(source, settings, window=None): the one sound path.

Every tab calls this: the Master tab's export and its live preview, Batch,
album mode and Remix. The old app had six copies of load, clean, master and
save, and its preview differed from its export in 13 ways
(docs/ARCHITECTURE.md §5). Here the preview is the same render on a window,
so it matches the export by construction.

The order, each stage at its place in the chain:

  1. Output rate. Resample for the chosen format first (the release copy is
     44.1 kHz), so the limiter's ceiling holds at the rate that is written.
  2. Fixes. One tool per card that is on (Step 6 adds them).
  3. The user EQ.
  4. Mastering: a 25 Hz low-cut, one static loudness gain (always from the
     whole song), the peak shaper and the true-peak limiter.

A window renders only its span, plus a lead-in and a tail. The one-way
filters, the zero-phase filters and the limiter then settle exactly as they
do in a full render.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

from . import catalog
from .audio import filters, io, meters
from .master import limiter, loudness
from .settings import EqBand, Settings

LEAD_IN_S = 1.0            # filters and the limiter's release settle in this
TAIL_S = 0.5               # zero-phase filters and the limiter's lookahead
LOW_CUT_HZ = 25.0
_CACHE_LIMIT = 16

_EQ_KIND = {"bell": "bell", "low_shelf": "low_shelf", "high_shelf": "high_shelf",
            "highpass": "high_pass", "lowpass": "low_pass", "notch": "notch"}
_GAIN_KINDS = {"bell", "low_shelf", "high_shelf"}


@dataclass(eq=False)
class Source:
    """A song, loaded once. It keeps what render() works out about the whole
    song (the audio at other rates, the loudness before mastering), so a
    preview window does not redo it."""
    audio: np.ndarray                      # float32, (samples, channels)
    sr: int
    path: Optional[str] = None
    _cache: Dict[Any, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_array(cls, x: np.ndarray, sr: int, path: Optional[str] = None) -> "Source":
        a = np.asarray(x, dtype=np.float32)
        if a.ndim == 1:
            a = a[:, None]
        return cls(a, int(sr), os.path.abspath(os.fspath(path)) if path else None)

    @classmethod
    def load(cls, path) -> "Source":
        x, sr = io.load(path)
        return cls(x, sr, os.path.abspath(os.fspath(path)))

    @property
    def duration_s(self) -> float:
        return self.audio.shape[0] / self.sr

    def at_rate(self, sr: int) -> np.ndarray:
        if int(sr) == self.sr:
            return self.audio
        return self._remember(("rate", int(sr)),
                              lambda: io.resample(self.audio, self.sr, sr)[0].astype(np.float32))

    def _remember(self, key: Any, make) -> Any:
        if key not in self._cache:
            if len(self._cache) >= _CACHE_LIMIT:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = make()
        return self._cache[key]


@dataclass
class Rendered:
    audio: np.ndarray                      # float32, (samples, channels)
    sr: int
    report: Dict[str, Any]
    settings: Settings
    source_path: Optional[str] = None      # export() refuses to write over it


def _eq_designs(bands: Tuple[EqBand, ...], sr: int):
    out = []
    for b in bands:
        if not b.enabled or b.freq_hz >= 0.49 * sr:
            continue
        kind = _EQ_KIND[b.type]
        if kind in _GAIN_KINDS:
            if abs(b.gain_db) < 0.05:
                continue
            gain = b.gain_db
        else:
            gain = float("-inf") if kind == "notch" else 0.0
        out.append(filters.design(kind, b.freq_hz, sr, gain_db=gain, q=b.q))
    return out


def _premaster(x: np.ndarray, sr: int, s: Settings) -> np.ndarray:
    """Everything before the loudness gain. Returns x itself when nothing
    applies, so a bypass render is bit-exact."""
    stages = _eq_designs(s.eq_bands, sr) if s.eq_enabled else []
    if s.mastering:
        stages.append(filters.design("high_pass", LOW_CUT_HZ, sr))
    if not stages:
        return x
    y = np.asarray(x, dtype=np.float64)
    for d in stages:
        y = filters.apply(y, sr, d)
    return y


def _premaster_key(s: Settings, sr: int) -> Tuple:
    return ("premaster_lufs", sr, s.eq_enabled, s.eq_bands, s.mastering,
            tuple(sorted(s.fixes.items())), s.auto)


def _whole_song_gain(source: Source, sr: int, s: Settings) -> Tuple[float, float]:
    """(loudness before mastering, gain to the target), for the whole song."""
    lufs = source._remember(_premaster_key(s, sr),
                            lambda: meters.loudness(_premaster(source.at_rate(sr), sr, s), sr))
    target = catalog.loudness_target(s.loudness_target).lufs
    return lufs, loudness.gain_to_target(lufs, target)


def render(source: Source, settings: Optional[Settings] = None,
           window: Optional[Tuple[float, float]] = None) -> Rendered:
    """Render the song, or the span `window` = (start_s, end_s) of it.

    A window covers samples round(start_s * sr) up to round(end_s * sr) at
    the output rate, and matches the same span of a full render.
    """
    s = settings if settings is not None else Settings()
    fmt = catalog.output_format(s.format)
    sr = int(fmt.sr or source.sr)
    x = source.at_rate(sr)
    n = x.shape[0]
    if window is None:
        start, end = 0, n
    else:
        start = min(n, max(0, int(round(float(window[0]) * sr))))
        end = min(n, max(start, int(round(float(window[1]) * sr))))
    a = max(0, start - int(round(LEAD_IN_S * sr)))
    b = min(n, end + int(round(TAIL_S * sr)))

    report: Dict[str, Any] = {
        "sr": sr, "format": fmt.key,
        "window": None if window is None else [start / sr, end / sr],
        # Step 6 adds the tools. Until one is built, a card that is on says so.
        "fixes": {k: "not built yet" for k in s.fixes},
        "mastering": {"enabled": s.mastering},
    }

    y = _premaster(x[a:b], sr, s)
    if s.mastering:
        before, gain_db = _whole_song_gain(source, sr, s)
        y = np.asarray(y, dtype=np.float64) * 10.0 ** (gain_db / 20.0)
        y, shaper = limiter.soft_peak_shaper(y, fmt.ceiling_dbtp)
        y, lim = limiter.true_peak_limiter(y, sr, fmt.ceiling_dbtp)
        report["mastering"].update({
            "target_lufs": catalog.loudness_target(s.loudness_target).lufs,
            "loudness_before_lufs": before,
            "gain_db": gain_db,
            "ceiling_dbtp": fmt.ceiling_dbtp,
            "shaped_ratio": shaper["shaped_ratio"],
            "limiter_gain_reduction_db": lim["max_gain_reduction_db"],
        })

    out = np.asarray(y[start - a:end - a], dtype=np.float32)
    return Rendered(out, sr, report, s, source.path)
