"""render(source, settings, window=None): the one sound path.

Every tab calls this: the Master tab's export and its live preview, Batch,
album mode and Remix. The old app had six copies of load, clean, master and
save, and its preview differed from its export in 13 ways
(docs/ARCHITECTURE.md §5). Here the preview is the same render on a window,
so it matches the export by construction.

The order, each stage at its place in the chain:

  1. Output rate. Resample for the chosen format first (the release copy is
     44.1 kHz), so the limiter's ceiling holds at the rate that is written.
  2. Fixes. One tool per card that is on (_FIX_TOOLS): the de-click first,
     since a click would ring on through a notch; then the Fixed tones
     notch; then the spectral de-noise, the voice de-noise, the de-esser
     and the dynamic EQ.
     A tool whose plan reads the whole song slowly (SLOW_PLAN) says how far
     it has got, once per song; prepare() does that work ahead of a preview.
  2b. With mastering on, the tone curve (1.1.1's, ported bit-exact): worked
     out once from the whole raw song, applied after the notch as 1.1.1 did.
     With a reference track, the curve moves the song toward the reference
     instead (tone.match_curve).
  3. The user EQ.
  4. Level: with mastering on, a 25 Hz low-cut, one static loudness gain,
     the peak shaper and the true-peak limiter; with it off and "preserve
     volume" on, one gain back to the song's own level. Either gain is
     always worked out from the whole song.

Around render(), the Master tab's export (shimmer/api/render.py) cuts the
edges you placed in Trim before it, and adds your fades after it, so the
limiter can't flatten them. export() then adds dither and writes the file.

A window renders only its span, plus a lead-in and a tail. The filters,
the notches and the limiter then settle exactly as they do in a full
render.
"""
from __future__ import annotations

import dataclasses
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import catalog
from .analyze import tone_plan as _planner
from .analyze.percussion import percussive_share
from .analyze.track import REF_FREQS
from .analyze.tones import estimate_cutoff_hz, scan_fixed_lines
from .audio import eq as user_eq
from .audio import filters, io, meters
from .master import limiter, loudness, tone
from .progress import Progress
from .repair import declick, deesser, dynamic_eq, hash_remover, notch, vocal_grain
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

# The fixes after the notch, in the order they run: (card, tool module).
# Each module has plan(audio, sr), worked out once from the whole song and
# kept with it; apply(x, sr, plan, amount, offset), which returns x itself
# when it changes nothing; and summary(plan, amount) for the report.
_FIX_TOOLS: Tuple[Tuple[str, Any], ...] = (
    ("clicks", declick),
    ("shimmer", hash_remover),
    ("grain", vocal_grain),
    ("sibilance", deesser),
    ("harshness", dynamic_eq.HARSHNESS),
    ("mud", dynamic_eq.MUD),
)
BUILT_CARDS = tuple(card for card, _ in _FIX_TOOLS)
# These run before the notch: a click would ring on through a notch filter.
_BEFORE_NOTCH = ("clicks",)


@dataclass(eq=False)
class Source:
    """A song, loaded once. It keeps what render() works out about the whole
    song (the audio at other rates, the tones found, the loudness before
    mastering), so a preview window does not redo it."""
    audio: np.ndarray                      # float32, (samples, channels)
    sr: int
    path: Optional[str] = None
    _cache: Dict[Any, Any] = field(default_factory=dict, repr=False)
    # Work in progress, by key: two threads asking for the same thing at once
    # (a preview and an export, or the prepare job) work it out once.
    _busy: Dict[Any, Any] = field(default_factory=dict, repr=False)
    _lock: Any = field(default_factory=threading.Lock, repr=False)

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
        """The value for key, worked out by make() the first time. A thread
        that asks while another is still working it out waits for that one
        rather than doing the work again. If that one fails or is cancelled,
        the next to ask works it out itself."""
        while True:
            with self._lock:
                if key in self._cache:
                    return self._cache[key]
                busy = self._busy.get(key)
                if busy is None:
                    busy = self._busy[key] = threading.Event()
                    break
            busy.wait()
        try:
            value = make()
            with self._lock:
                if len(self._cache) >= _CACHE_LIMIT:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = value
            return value
        finally:
            with self._lock:
                self._busy.pop(key, None)
            busy.set()


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


def _tones_plan(source: Source, sr: int, s: Settings,
                notches: Optional[Sequence[notch.Notch]]) -> List[notch.Notch]:
    """The notches this render applies. The Fixed tones card's amount scales
    each notch's depth; "auto" applies them at full depth when the card has
    not been set. `notches` overrides the scan (the screen's own list)."""
    a = _tones_amount(s)
    if a <= 0.0:
        return []
    if notches is None:
        notches = source._remember(
            ("tones_plan", sr),
            lambda: notch.plan_from_lines(scan_fixed_lines(source.at_rate(sr), sr), sr).notches)
    return [dataclasses.replace(n, depth_db=n.depth_db * a) for n in notches]


def _tones_amount(s: Settings) -> float:
    """How deep the Fixed tones notches go, 0-1; 0 when none apply."""
    amount = s.fixes.get("tones")
    if amount is None:
        return 1.0 if s.auto else 0.0
    return max(0.0, float(amount))


def _tools(source: Source, sr: int, s: Settings,
           progress: Optional[Progress] = None) -> List[Tuple[str, Any, Any, float]]:
    """The fixes after the notch this render applies, in chain order:
    (card, module, its whole-song plan, amount)."""
    out = []
    for card, mod in _FIX_TOOLS:
        amount = float(s.fixes.get(card, 0.0))
        if amount > 0.0:
            out.append((card, mod, _plan(source, sr, card, mod, progress, _mode(s, card)),
                        amount))
    return out


def _mode(s: Settings, card: str) -> Optional[str]:
    """How this card's fix works in these settings (catalog.Card.modes)."""
    return catalog.card_mode(card, s.fix_modes.get(card))


def _plan_key(card: str, sr: int, mode: Optional[str]) -> Tuple:
    """A plan's cache key. A card's default mode keeps the plain key."""
    return (card, "plan", sr) if mode in (None, catalog.card_mode(card)) else (
        card, "plan", sr, mode)


def _plan(source: Source, sr: int, card: str, mod: Any,
          progress: Optional[Progress] = None, mode: Optional[str] = None) -> Any:
    """A tool's whole-song plan, worked out once per song, rate and mode. A
    slow one (SLOW_PLAN) says how far it has got under Fixes, and stops
    there if the run is cancelled. A mode in the tool's STEM_MODES gets the
    song's vocal first (_vocal_stem)."""
    key = _plan_key(card, sr, mode)
    if not getattr(mod, "SLOW_PLAN", False):
        return source._remember(key, lambda: mod.plan(source.at_rate(sr), sr))
    c = catalog.card(card)
    label = f"{c.label}: {catalog.TOOL_LABELS.get(c.tool or '', card)}"

    def step(f: float) -> None:
        _stage(progress, "fixes", label, f"reading the whole song once, {f:.0%}")

    def make() -> Any:
        if mode in getattr(mod, "STEM_MODES", ()):
            vocal, why = _vocal_stem(source, sr, progress, label)
            if vocal is None:
                return mod.plan(source.at_rate(sr), sr, step=step, note=why)
            return mod.plan(source.at_rate(sr), sr, step=step, vocal=vocal)
        return mod.plan(source.at_rate(sr), sr, step=step)
    return source._remember(key, make)


# How the engine gets a song's vocal, for a fix mode that needs it (a
# tool's STEM_MODES). The engine carries no splitter of its own: the app
# hands one in at start-up (set_vocal_splitter; shimmer/api/render.py uses
# the Remix tab's). It is called as splitter(path, sr, report) and returns
# (vocal or None, why not); report(detail) says how far it has got.
_VOCAL_SPLITTER: Optional[Any] = None


def set_vocal_splitter(splitter: Optional[Any]) -> None:
    global _VOCAL_SPLITTER
    _VOCAL_SPLITTER = splitter


def _vocal_stem(source: Source, sr: int, progress: Optional[Progress],
                label: str) -> Tuple[Optional[np.ndarray], str]:
    """The song's vocal at `sr` and the song's length, or (None, why not)."""
    path = source.path
    if not path or not os.path.isfile(path):
        return None, "the song has no file on disk to split"
    if _VOCAL_SPLITTER is None:
        return None, "the Remix splitter is not installed"
    try:
        vocal, why = _VOCAL_SPLITTER(
            path, sr, lambda detail: _stage(progress, "fixes", label,
                                            f"splitting out the vocal: {detail}"))
    except Exception as e:  # noqa: BLE001 - a failed split falls back, and says why
        if progress is not None:
            progress.check()
        return None, f"the split failed ({type(e).__name__})"
    if vocal is None:
        return None, why or "the split has no vocal"
    vocal = np.asarray(vocal, dtype=np.float32)
    vocal = vocal[:, None] if vocal.ndim == 1 else vocal
    n = source.at_rate(sr).shape[0]
    out = np.zeros((n, vocal.shape[1]), dtype=np.float32)
    out[:min(n, vocal.shape[0])] = vocal[:n]
    return out, ""


def plans_pending(source: Source, settings: Optional[Settings] = None) -> List[str]:
    """The cards on in these settings whose fix still has to read the whole
    song first: a slow plan (SLOW_PLAN) not yet worked out for this song.
    It never does the work."""
    s = settings if settings is not None else Settings()
    sr = catalog.output_format(s.format).rate_for(source.sr)
    return [card for card, mod in _FIX_TOOLS
            if float(s.fixes.get(card, 0.0)) > 0.0 and getattr(mod, "SLOW_PLAN", False)
            and _plan_key(card, sr, _mode(s, card)) not in source._cache]


def prepare(source: Source, settings: Optional[Settings] = None,
            progress: Optional[Progress] = None) -> None:
    """Do now the whole-song work the slow fixes need, saying how far it has
    got, so the previews after it are quick. The screen runs this as its own
    job the first time a card like Shimmer is on for a song. Cancel stops it
    and keeps nothing half done."""
    s = settings if settings is not None else Settings()
    sr = catalog.output_format(s.format).rate_for(source.sr)
    pending = plans_pending(source, s)
    for card, mod in _FIX_TOOLS:
        if card in pending:
            _plan(source, sr, card, mod, progress, _mode(s, card))


def _tools_key(s: Settings) -> Tuple:
    return tuple((card, float(s.fixes[card]), _mode(s, card)) for card in BUILT_CARDS
                 if s.fixes.get(card, 0.0) > 0.0)


def _fix(x: np.ndarray, sr: int, plan: List[notch.Notch],
         tools: Sequence[Tuple[str, Any, Any, float]] = (), offset: int = 0) -> np.ndarray:
    """The fixes: the de-click, the notch, then each other tool. Returns x
    itself when nothing applies, so a bypass render is bit-exact."""
    y = x
    for card, mod, p, amount in tools:
        if card in _BEFORE_NOTCH:
            y = mod.apply(y, sr, p, amount, offset)
    y = notch.apply(y, sr, plan) if plan else y
    for card, mod, p, amount in tools:
        if card not in _BEFORE_NOTCH:
            y = mod.apply(y, sr, p, amount, offset)
    return y


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
        cutoff = _cutoff(source, sr)
        if ref is not None:
            return tone.match_curve(x, sr, ref[0], amount=s.match_amount, tilt=s.tilt,
                                    cutoff_hz=cutoff, ref_cutoff_hz=ref[1])
        return tone.compute_tone_curve(
            x, sr, strength=tone.intensity_to_strength(s.intensity), tilt=s.tilt,
            cutoff_hz=cutoff)
    curve = source._remember(("tone_curve", sr) + _tone_key(s, reference), make)
    return curve if max(abs(v) for v in curve) >= 1e-3 else []


def _cutoff(source: Source, sr: int) -> Optional[float]:
    """The song's bandwidth cutoff at this rate, or None; worked out once."""
    return source._remember(("cutoff", sr),
                            lambda: estimate_cutoff_hz(source.at_rate(sr), sr).get("cutoff_hz"))


def _toned(x: np.ndarray, sr: int, curve: List[float], cutoff: Optional[float]) -> np.ndarray:
    return tone.apply_tone_curve(x, sr, curve, cutoff_hz=cutoff) if curve else x


def _premaster(x: np.ndarray, sr: int, s: Settings) -> np.ndarray:
    """EQ and the mastering low-cut. Returns x itself when nothing applies,
    so a bypass render is bit-exact."""
    stages = user_eq.designs(s.eq_bands, sr) if s.eq_enabled else []
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
        tuple((n.hz, n.depth_db, n.bw_hz) for n in plan), _tools_key(s))


def _gain_key(s: Settings, sr: int, plan: List[notch.Notch],
              reference: Optional[Source] = None) -> Tuple:
    """The mastering gain also depends on the target and the ceiling."""
    return _whole_key(s, sr, plan, "master_gain", reference) + (s.loudness_target, s.format)


def _whole_premaster(source: Source, sr: int, s: Settings, plan: List[notch.Notch],
                     reference: Optional[Source] = None) -> np.ndarray:
    x = source.at_rate(sr)
    fixed = _fix(x, sr, plan, _tools(source, sr, s))
    return _premaster(_toned(fixed, sr, _tone_curve(source, sr, s, reference),
                             _cutoff(source, sr)), sr, s)


# The gain is checked against the loudness after the shaper and limiter,
# which take a little back (0.02-0.32 LU on real songs, docs/CHAIN-AUDIT.md
# section 4), and corrected up to this many times, until within LOUDNESS_TOL.
# One pass lands within a few hundredths of a LU on real songs.
LOUDNESS_PASSES = 1
LOUDNESS_TOL_LU = 0.05


def _level(y: np.ndarray, sr: int, ceiling_dbtp: float, gain_db: float):
    """Mastering's level stage: the gain, the peak shaper, the limiter."""
    y = np.asarray(y, dtype=np.float64) * 10.0 ** (gain_db / 20.0)
    y, shaper = limiter.soft_peak_shaper(y, ceiling_dbtp)
    y, lim = limiter.true_peak_limiter(y, sr, ceiling_dbtp)
    return y, shaper, lim


def _whole_song_gain(source: Source, sr: int, s: Settings, plan: List[notch.Notch],
                     reference: Optional[Source] = None) -> Tuple[float, float]:
    """(loudness before mastering, gain to the target), for the whole song.
    The gain is the one that lands the finished song on the target, after
    the shaper and the limiter."""
    target = catalog.loudness_target(s.loudness_target).lufs
    ceiling = catalog.output_format(s.format).ceiling_dbtp

    def make() -> Tuple[float, float]:
        y = _whole_premaster(source, sr, s, plan, reference)
        lufs = source._remember(_whole_key(s, sr, plan, "premaster_lufs", reference),
                                lambda: meters.loudness(y, sr))
        gain = loudness.gain_to_target(lufs, target)
        if gain == 0.0:
            return lufs, gain
        for _ in range(LOUDNESS_PASSES):
            miss = target - meters.loudness(_level(y, sr, ceiling, gain)[0], sr)
            if not np.isfinite(miss) or abs(miss) < LOUDNESS_TOL_LU:
                break
            gain += float(miss)
        return lufs, float(gain)
    return source._remember(_gain_key(s, sr, plan, reference), make)


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


def known_gain(source: Source, settings: Optional[Settings] = None, *,
               notches: Optional[Sequence[notch.Notch]] = None,
               reference: Optional[Source] = None,
               checked: bool = False) -> Optional[float]:
    """The one gain in dB that mastering adds for these settings (with
    mastering off, Preserve volume's), when a render has already worked it
    out for this song; else None. It never measures: the Signal Chain view
    asks on every settings change. `notches` is the list the render was
    given (None: the scan's, known only once the scan has run).
    `checked`: only the gain checked against the finished song, never the
    first-pass one (None when only that is known)."""
    s = settings if settings is not None else Settings()
    if not s.mastering and not s.preserve_volume:
        return None
    sr = catalog.output_format(s.format).rate_for(source.sr)
    if notches is None and _tones_amount(s) > 0.0:
        notches = source._cache.get(("tones_plan", sr))
        if notches is None:
            return None
    plan = _tones_plan(source, sr, s, notches or [])
    if s.mastering:
        if reference is not None and ("reference_shape",) not in reference._cache:
            return None
        done = source._cache.get(_gain_key(s, sr, plan, reference))
        if done is not None:
            return float(done[1])
        if checked:
            return None
        # Another target or format, not rendered yet: the first-pass gain,
        # before the shaper and limiter are checked (within a few tenths).
        lufs = source._cache.get(_whole_key(s, sr, plan, "premaster_lufs", reference))
        if lufs is None:
            return None
        return float(loudness.gain_to_target(lufs, catalog.loudness_target(s.loudness_target).lufs))
    g = source._cache.get(_whole_key(s, sr, plan, "preserve_gain"))
    return None if g is None else float(20.0 * np.log10(g))


def premaster_levels(source: Source, settings: Optional[Settings] = None, *,
                     reference: Optional[Source] = None) -> Dict[str, float]:
    """The song's loudness and true peak just before mastering's gain: after
    the fixes, the tone curve, the EQ and the low-cut, at the output rate.
    This is what render() works its gain out from. Album mode picks one gain
    for a whole record from every song's level (master.loudness.album_gains).
    """
    s = settings if settings is not None else Settings()
    sr = catalog.output_format(s.format).rate_for(source.sr)
    plan = _tones_plan(source, sr, s, None)
    y = _whole_premaster(source, sr, s, plan, reference)
    lufs = meters.loudness(y, sr)
    source._remember(_whole_key(s, sr, plan, "premaster_lufs", reference), lambda: lufs)
    return {"lufs_i": lufs, "true_peak_dbtp": meters.true_peak_db(y, sr)}


def tone_plan(source: Source, settings: Optional[Settings] = None, *,
              family: str = "neutral", notches: Optional[Sequence[notch.Notch]] = None,
              reference: Optional[Source] = None) -> Dict[str, Any]:
    """Suggested EQ for this song (analyze.tone_plan), judged the way
    render() will run: at the output rate, after the fixes (the Fixed tones
    notches) and, with mastering on, after the mastering tone curve, so
    nothing is corrected twice. `notches` is the screen's own list, as for
    render(). Measures only."""
    s = settings if settings is not None else Settings()
    sr = catalog.output_format(s.format).rate_for(source.sr)
    x = source.at_rate(sr)
    plan = _tones_plan(source, sr, s, notches)
    tools = _tools(source, sr, s)
    curve = None
    if s.mastering:
        curve = _tone_curve(source, sr, s, reference) or [0.0] * len(tone.REF_DB)
    out = _planner.plan_tone(
        x, sr, family=family,
        cutoff_hz=estimate_cutoff_hz(x, sr).get("cutoff_hz"),
        tone_curve_db=curve,
        notches=[{"hz": n.hz} for n in plan],
        cleaner=(lambda ex: _fix(ex, sr, plan, tools)) if (plan or tools) else None)
    out["mastering_on"] = s.mastering
    return out


# A reference this many times more (or less) percussive than the song gets a
# warning. The sources say to warn when the drums differ "a lot" and give
# no number (MASTERING-SOURCES.md §4): a first guess, to judge on the bench.
PERC_RATIO_WARN = 1.5


def reference_view(source: Source, reference: Source,
                   settings: Optional[Settings] = None) -> Dict[str, Any]:
    """What matching `reference` will do to this song, for the screen:

    song_db, reference_db  both tone shapes, level-matched (1/3-octave bands)
    curve_db               the EQ the match applies: the same call render()
                           makes, at these settings' Amount and Tilt
    matched_up_to_hz       above this the reference has nothing to match
                           (its top-end cutoff), or None
    percussive             each song's share of hits, and "more" / "less"
                           when the reference differs a lot, else None

    Measures only."""
    s = settings if settings is not None else Settings()
    sr = catalog.output_format(s.format).rate_for(source.sr)
    x = source.at_rate(sr)
    ref_shape, ref_cut = _reference(reference)
    cut = estimate_cutoff_hz(x, sr).get("cutoff_hz")
    curve = tone.match_curve(x, sr, ref_shape, amount=s.match_amount, tilt=s.tilt,
                             cutoff_hz=cut, ref_cutoff_hz=ref_cut)
    song_p = source._remember(("percussive",), lambda: percussive_share(source.audio, source.sr))
    ref_p = reference._remember(("percussive",), lambda: percussive_share(reference.audio, reference.sr))
    ratio = ref_p / max(song_p, 1e-6)
    differs = ("more" if ratio >= PERC_RATIO_WARN
               else "less" if ratio <= 1.0 / PERC_RATIO_WARN else None)
    return {
        "freqs_hz": [float(f) for f in REF_FREQS],
        "song_db": [round(float(v), 2) for v in tone.reference_shape(x, sr)],
        "reference_db": [round(float(v), 2) for v in ref_shape],
        "curve_db": [round(float(v), 2) for v in curve],
        "match_amount": s.match_amount,
        "tilt": s.tilt,
        "limit_db": tone.MATCH_LIMIT_DB,
        "song_cutoff_hz": cut,
        "reference_cutoff_hz": ref_cut,
        "matched_up_to_hz": 0.9 * float(ref_cut) if ref_cut else None,
        "percussive": {"song": round(song_p, 3), "reference": round(ref_p, 3), "differs": differs},
    }


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
    sr = fmt.rate_for(source.sr)
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
    tools = _tools(source, sr, s, progress)
    if plan or tools:
        names = (["Fixed tones"] if plan else []) + [catalog.card(c).label for c, _, _, _ in tools]
        _stage(progress, "fixes", ", ".join(names),
               f"{len(plan)} notch{'es' if len(plan) != 1 else ''}" if plan else "")
    fixed = _fix(seg, sr, plan, tools, offset=a)
    if plan:
        report["fixes"]["tones"] = {
            "enabled": True, "notches": len(plan),
            "lines": [{"hz": round(p.hz, 1), "depth_db": round(p.depth_db, 1), "kind": p.kind}
                      for p in plan],
            "deepest_db": round(max(p.depth_db for p in plan), 1),
        }
    for card, mod, p, amount in tools:
        report["fixes"][card] = {"enabled": True, "amount": amount, **mod.summary(p, amount)}
    for key in s.fixes:
        if key == "tones" or key in BUILT_CARDS:
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
    toned = _toned(fixed, sr, curve, _cutoff(source, sr) if curve else None)

    # 3. The user EQ, and the mastering low-cut.
    if s.eq_enabled and user_eq.designs(s.eq_bands, sr):
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
        y, shaper, lim = _level(y, sr, fmt.ceiling_dbtp, gain)
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
