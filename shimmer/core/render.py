"""render(source, settings, window=None): the one sound path.

Every tab calls this: the Master tab's export and its live preview, Batch,
album mode and Remix. The old app had six copies of load, clean, master and
save, and its preview differed from its export in 13 ways
(docs/ARCHITECTURE.md §5). Here the preview is the same render on a window,
so it matches the export by construction.

The order, each stage at its place in the chain:

  1. Output rate. Resample for the chosen format first (the release copy is
     44.1 kHz), so the limiter's ceiling holds at the rate that is written.
  2. Fixes. One tool per card that is on. Built so far: Fixed tones (the
     notch). Step 6 adds the rest.
  2b. With mastering on, the tone curve (1.1.1's, ported bit-exact): worked
     out once from the whole raw song, applied after the notch as 1.1.1 did.
     With a reference track, the curve moves the song toward the reference
     instead (tone.match_curve).
  3. The user EQ.
  4. Level: with mastering on, a 25 Hz low-cut, one static loudness gain,
     the peak shaper and the true-peak limiter; with it off and "preserve
     volume" on, one gain back to the song's own level. Either gain is
     always worked out from the whole song.

A window renders only its span, plus a lead-in and a tail. The filters,
the notches and the limiter then settle exactly as they do in a full
render.
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import catalog
from .analyze.tones import estimate_cutoff_hz, scan_fixed_lines
from .audio import filters, io, meters
from .master import limiter, loudness, tone
from .progress import Progress
from .repair import notch
from .settings import EqBand, Settings

LEAD_IN_S = 1.0            # filters and the limiter's release settle in this
TAIL_S = 0.5               # zero-phase filters and the limiter's lookahead
LOW_CUT_HZ = 25.0
_CACHE_LIMIT = 16

# "Preserve volume" (mastering off), as 1.1.1 did it: match the song's own
# RMS, never louder than a 0.999 peak allows, within 4x either way.
_PRESERVE_PEAK = 0.999
_PRESERVE_MAX_SCALE = 4.0

# Cards whose fix is part of mastering, not a cleaning tool.
_MASTERING_TOOLS = ("tone_target", "loudness_target")

_EQ_KIND = {"bell": "bell", "low_shelf": "low_shelf", "high_shelf": "high_shelf",
            "highpass": "high_pass", "lowpass": "low_pass", "notch": "notch"}
_GAIN_KINDS = {"bell", "low_shelf", "high_shelf"}


@dataclass(eq=False)
class Source:
    """A song, loaded once. It keeps what render() works out about the whole
    song (the audio at other rates, the tones found, the loudness before
    mastering), so a preview window does not redo it."""
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
    removed: Optional[np.ndarray] = None   # what the fixes took out, when asked for


def _stage(progress: Optional[Progress], key: str, label: str, detail: str = "") -> None:
    if progress is not None:
        progress.stage(key, label, detail)


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


def _tones_plan(source: Source, sr: int, s: Settings,
                notches: Optional[Sequence[notch.Notch]]) -> List[notch.Notch]:
    """The notches this render applies. The Fixed tones card's amount scales
    each notch's depth; "auto" applies them at full depth when the card has
    not been set. `notches` overrides the scan (the screen's own list)."""
    amount = s.fixes.get("tones")
    if amount is None and not s.auto:
        return []
    a = 1.0 if amount is None else float(amount)
    if a <= 0.0:
        return []
    if notches is None:
        notches = source._remember(
            ("tones_plan", sr),
            lambda: notch.plan_from_lines(scan_fixed_lines(source.at_rate(sr), sr), sr).notches)
    return [dataclasses.replace(n, depth_db=n.depth_db * a) for n in notches]


def _fix(x: np.ndarray, sr: int, plan: List[notch.Notch]) -> np.ndarray:
    return notch.apply(x, sr, plan) if plan else x


def _reference(reference: Optional[Source]) -> Optional[Tuple[Tuple[float, ...], Optional[float]]]:
    """A reference track's tone shape and bandwidth cutoff, worked out once
    and kept with it. Plain values, so they can be part of a cache key."""
    if reference is None:
        return None

    def make():
        x = reference.audio
        return (tuple(float(v) for v in tone.reference_shape(x, reference.sr)),
                estimate_cutoff_hz(x, reference.sr).get("cutoff_hz"))
    return reference._remember(("reference_shape",), make)


def _tone_key(s: Settings, reference: Optional[Source]) -> Tuple:
    """What the tone curve depends on besides the song."""
    ref = _reference(reference)
    if ref is None:
        return (s.intensity, s.tilt)
    return ("match", s.match_amount, s.tilt, ref)


def _tone_curve(source: Source, sr: int, s: Settings,
                reference: Optional[Source] = None) -> List[float]:
    """The mastering tone curve for this song, from the whole raw song, or
    [] when mastering is off or the curve is flat. With a reference track,
    the curve moves toward it; without one, toward 1.1.1's target."""
    if not s.mastering:
        return []
    ref = _reference(reference)

    def make() -> List[float]:
        x = source.at_rate(sr)
        cutoff = estimate_cutoff_hz(x, sr).get("cutoff_hz")
        if ref is not None:
            return tone.match_curve(x, sr, ref[0], amount=s.match_amount, tilt=s.tilt,
                                    cutoff_hz=cutoff, ref_cutoff_hz=ref[1])
        return tone.compute_tone_curve(
            x, sr, strength=tone.intensity_to_strength(s.intensity), tilt=s.tilt,
            cutoff_hz=cutoff)
    curve = source._remember(("tone_curve", sr) + _tone_key(s, reference), make)
    return curve if max(abs(v) for v in curve) >= 1e-3 else []


def _toned(x: np.ndarray, sr: int, curve: List[float]) -> np.ndarray:
    return tone.apply_tone_curve(x, sr, curve) if curve else x


def _premaster(x: np.ndarray, sr: int, s: Settings) -> np.ndarray:
    """EQ and the mastering low-cut. Returns x itself when nothing applies,
    so a bypass render is bit-exact."""
    stages = _eq_designs(s.eq_bands, sr) if s.eq_enabled else []
    if s.mastering:
        stages.append(filters.design("high_pass", LOW_CUT_HZ, sr))
    if not stages:
        return x
    y = np.asarray(x, dtype=np.float64)
    for d in stages:
        y = filters.apply(y, sr, d)
    return y


def _whole_key(s: Settings, sr: int, plan: List[notch.Notch], what: str,
               reference: Optional[Source] = None) -> Tuple:
    return (what, sr, s.eq_enabled, s.eq_bands, s.mastering) + _tone_key(s, reference) + (
        tuple((n.hz, n.depth_db, n.bw_hz) for n in plan),)


def _whole_premaster(source: Source, sr: int, s: Settings, plan: List[notch.Notch],
                     reference: Optional[Source] = None) -> np.ndarray:
    x = source.at_rate(sr)
    return _premaster(_toned(_fix(x, sr, plan), sr, _tone_curve(source, sr, s, reference)), sr, s)


def _whole_song_gain(source: Source, sr: int, s: Settings, plan: List[notch.Notch],
                     reference: Optional[Source] = None) -> Tuple[float, float]:
    """(loudness before mastering, gain to the target), for the whole song."""
    lufs = source._remember(
        _whole_key(s, sr, plan, "premaster_lufs", reference),
        lambda: meters.loudness(_whole_premaster(source, sr, s, plan, reference), sr))
    target = catalog.loudness_target(s.loudness_target).lufs
    return lufs, loudness.gain_to_target(lufs, target)


def _preserve_gain(source: Source, sr: int, s: Settings, plan: List[notch.Notch]) -> float:
    """The one gain that puts the processed song back at the source's level:
    its RMS, never past a 0.999 peak, within 4x either way (1.1.1's rule,
    worked out from the whole song rather than each preview window). Only
    used with mastering off, so no tone curve and no reference."""
    def make() -> float:
        x = np.asarray(source.at_rate(sr), dtype=np.float64)
        y = np.asarray(_whole_premaster(source, sr, s, plan), dtype=np.float64)
        rin, rout = float(np.sqrt(np.mean(x ** 2))), float(np.sqrt(np.mean(y ** 2)))
        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if rin < 1e-6 or rout < 1e-6 or peak < 1e-6:
            return 1.0
        scale = min(rin / rout, _PRESERVE_PEAK / peak)
        return float(np.clip(scale, 1.0 / _PRESERVE_MAX_SCALE, _PRESERVE_MAX_SCALE))
    return source._remember(_whole_key(s, sr, plan, "preserve_gain"), make)


def premaster_levels(source: Source, settings: Optional[Settings] = None, *,
                     reference: Optional[Source] = None) -> Dict[str, float]:
    """The song's loudness and true peak just before mastering's gain: after
    the fixes, the tone curve, the EQ and the low-cut, at the output rate.
    This is what render() works its gain out from. Album mode picks one gain
    for a whole record from every song's level (master.loudness.album_gains).
    """
    s = settings if settings is not None else Settings()
    sr = int(catalog.output_format(s.format).sr or source.sr)
    plan = _tones_plan(source, sr, s, None)
    y = _whole_premaster(source, sr, s, plan, reference)
    lufs = meters.loudness(y, sr)
    source._remember(_whole_key(s, sr, plan, "premaster_lufs", reference), lambda: lufs)
    return {"lufs_i": lufs, "true_peak_dbtp": meters.true_peak_db(y, sr)}


def render(source: Source, settings: Optional[Settings] = None,
           window: Optional[Tuple[float, float]] = None, *,
           progress: Optional[Progress] = None, with_removed: bool = False,
           notches: Optional[Sequence[notch.Notch]] = None,
           reference: Optional[Source] = None,
           gain_db: Optional[float] = None) -> Rendered:
    """Render the song, or the span `window` = (start_s, end_s) of it.

    A window covers samples round(start_s * sr) up to round(end_s * sr) at
    the output rate, and matches the same span of a full render.

    progress      reports each stage and stops the run if it is cancelled
    with_removed  also return what the fixes took out (Rendered.removed)
    notches       the Fixed tones notches to use instead of scanning
    reference     a reference track: with mastering on, the tone curve moves
                  toward it by Settings.match_amount instead of toward
                  1.1.1's target
    gain_db       album mode: one gain for the whole record (see
                  premaster_levels), in place of this song's own gain to
                  its loudness target. The shaper and limiter still act per
                  song, at the format's ceiling.
    """
    s = settings if settings is not None else Settings()
    fmt = catalog.output_format(s.format)
    sr = int(fmt.sr or source.sr)
    if sr != source.sr:
        _stage(progress, "rate", "Sample rate", f"{source.sr} Hz to {sr} Hz")
    x = source.at_rate(sr)
    n = x.shape[0]
    if window is None:
        start, end = 0, n
    else:
        start = min(n, max(0, int(round(float(window[0]) * sr))))
        end = min(n, max(start, int(round(float(window[1]) * sr))))
    a = max(0, start - int(round(LEAD_IN_S * sr)))
    b = min(n, end + int(round(TAIL_S * sr)))
    seg = x[a:b]

    report: Dict[str, Any] = {
        "sr": sr, "format": fmt.key,
        "window": None if window is None else [start / sr, end / sr],
        "fixes": {},
        "mastering": {"enabled": s.mastering},
    }

    # 2. Fixes.
    plan = _tones_plan(source, sr, s, notches)
    if plan:
        _stage(progress, "fixes", "Fixed tones",
               f"{len(plan)} notch{'es' if len(plan) != 1 else ''}")
    fixed = _fix(seg, sr, plan)
    if plan:
        report["fixes"]["tones"] = {
            "enabled": True, "notches": len(plan),
            "lines": [{"hz": round(p.hz, 1), "depth_db": round(p.depth_db, 1), "kind": p.kind}
                      for p in plan],
            "deepest_db": round(max(p.depth_db for p in plan), 1),
        }
    for key in s.fixes:
        if key == "tones":
            continue
        if catalog.card(key).tool in _MASTERING_TOOLS:
            # Lack of air and Loudness are the tone and loudness targets.
            report["fixes"][key] = "with mastering" if s.mastering else "needs mastering"
        else:
            report["fixes"][key] = "not built yet"

    # 2b. The mastering tone curve.
    curve = _tone_curve(source, sr, s, reference)
    matched = s.mastering and reference is not None
    if s.mastering:
        report["mastering"]["tone_target"] = "reference" if matched else "shimmer"
        if matched:
            report["mastering"]["match_amount"] = s.match_amount
    if curve:
        _stage(progress, "tone", "Tone",
               f"matching the reference, {s.match_amount:.0%}, {s.tilt}" if matched
               else f"{s.intensity}, {s.tilt}")
        report["mastering"]["tone_curve_db"] = [round(v, 2) for v in curve]
    toned = _toned(fixed, sr, curve)

    # 3. The user EQ, and the mastering low-cut.
    if s.eq_enabled and _eq_designs(s.eq_bands, sr):
        _stage(progress, "eq", "EQ")
    y = _premaster(toned, sr, s)

    # 4. Level.
    if s.mastering:
        if gain_db is None:
            before, gain = _whole_song_gain(source, sr, s, plan, reference)
            aim = f"{catalog.loudness_target(s.loudness_target).lufs:g} LUFS"
        else:
            before, gain = None, float(gain_db)
            aim = f"the album's gain, {gain:+.1f} dB"
        _stage(progress, "master", "Loudness and peaks",
               f"{aim}, {fmt.ceiling_dbtp:g} dBTP ceiling")
        y = np.asarray(y, dtype=np.float64) * 10.0 ** (gain / 20.0)
        y, shaper = limiter.soft_peak_shaper(y, fmt.ceiling_dbtp)
        y, lim = limiter.true_peak_limiter(y, sr, fmt.ceiling_dbtp)
        report["mastering"].update({
            "target_lufs": catalog.loudness_target(s.loudness_target).lufs,
            "loudness_before_lufs": before,
            "gain_db": gain,
            "album_gain": gain_db is not None,
            "ceiling_dbtp": fmt.ceiling_dbtp,
            "shaped_ratio": shaper["shaped_ratio"],
            "limiter_gain_reduction_db": lim["max_gain_reduction_db"],
        })
    elif s.preserve_volume and y is not seg:
        g = _preserve_gain(source, sr, s, plan)
        y = np.asarray(y, dtype=np.float64) * g
        report["mastering"]["preserve_volume_gain_db"] = float(20.0 * np.log10(g))

    out = np.asarray(y[start - a:end - a], dtype=np.float32)
    removed = None
    if with_removed:
        removed = (np.asarray(seg[start - a:end - a], dtype=np.float64)
                   - np.asarray(fixed[start - a:end - a], dtype=np.float64)).astype(np.float32)
    return Rendered(out, sr, report, s, source.path, removed)
