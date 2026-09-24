"""What each stage of the sound path does for a set of settings, for the
Signal Chain view (static/js/chain.js, POST /api/chain).

It follows the rules render() and export() follow, stage by stage, so the
view says what a run will do. Settings only: it touches no audio. What the
song adds (its rate, the tones found, a reference track) comes in as plain
facts from the caller.

Every stage says whether it runs and, when it does not, why. The nine
stages are catalog.STAGES, in signal order.
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import catalog
from .analyze.edges import FADE_OUT_RANGE_DB, TRIM_FADE_MS
from .audio import eq as user_eq
from .audio import trim as silence
from .master import tone
from .render import _FIX_TOOLS, _PRESERVE_MAX_SCALE, _PRESERVE_PEAK, LOW_CUT_HZ, _tones_amount
from .repair import notch as notch_mod
from .repair.notch import Notch
from .settings import Settings

# The built-in tone target's limits: master.tone.tone_curve's defaults (a
# test holds them equal).
TONE_MAX_BOOST_DB = 2.0
TONE_MAX_CUT_DB = 3.0

# Every row the release check can show (master.release; a test holds each
# row it returns to this list).
CHECKS = ("Loudness", "True peak", "Clipping in the source", "Sample rate", "Format",
          "Start", "End", "Length", "DC offset", "Mono check", "Bass in mono", "Tags", "ISRC")

_INTENSITY = {"low": "Low", "med": "Medium", "high": "High"}
_TILT = {"warmer": "Warmer", "warm": "Warm", "neutral": "Neutral", "bright": "Bright",
         "brightest": "Brightest"}
_EQ_TYPE = {"bell": "Bell", "low_shelf": "Low shelf", "high_shelf": "High shelf",
            "highpass": "Low-cut", "lowpass": "High-cut", "notch": "Notch"}
_ONE_WAY = ("highpass", "lowpass")
_STAGE = dict(catalog.STAGES)
_MASTERING_TOOLS = ("tone_target", "loudness_target")
_SAVED = "Your pick is saved on this computer to help test new fixes."

# What each built cleaning tool does, in the Fixes stage's words.
_TOOL_GLOSS = {
    "deesser": "Turns down harsh “s”, “t” and “ch” while they stick out.",
    "dynamic_eq": "Turns the band that sticks out most down while it is louder than usual.",
    "declick": "Finds short pops and crackle and fills them in.",
    "voice_denoise": "Takes out the grainy hiss that rides on the voice.",
    "spectral_denoise": "Turns down fizzy, flickering hiss up top, only where a trained "
                        "model hears it.",
}
# Cards that share a tool say what it does for them (dynamic_eq.HARSHNESS
# and MUD).
_CARD_GLOSS = {
    "harshness": "Turns down up to two narrow bands in 2–5 kHz while they are louder than "
             "they usually are in this song.",
    "mud": "Turns down the band in 200–500 Hz that sticks out most, while it is louder "
           "than it usually is in this song.",
}
# Built, and run by the command line, but held back from the screen until
# it passes its tests (catalog.TOOLS_READY).
_HELD_BACK = ("declick",)


def _card_amount(s: Settings, key: str) -> float:
    return float(s.fixes.get(key, catalog.card(key).default_amount))


def _tool_depth(card: str, amount: float) -> Optional[float]:
    """The deepest cut a built tool makes at this Amount, from its own
    settings (render._FIX_TOOLS), or None when it has no such limit."""
    for c, mod in _FIX_TOOLS:
        if c == card:
            top = getattr(mod, "MAX_CUT_DB", None)
            if top is None:
                top = getattr(mod, "_DEEPEST_DB", None)
            if top is None and hasattr(mod, "cfg"):
                top = getattr(mod.cfg, "max_cut_db", None)
            return None if top is None else float(top) * float(amount)
    return None


def _card_band(card: str) -> Optional[Tuple[float, float]]:
    """The range a card's running fix works in, for the band bar."""
    for c, mod in _FIX_TOOLS:
        if c == card:
            cfg = getattr(mod, "cfg", None)
            if cfg is not None and hasattr(cfg, "lo"):
                return float(cfg.lo), float(cfg.hi)
            fade = getattr(mod, "FADE_HZ", None)
            band = fade if fade is not None else getattr(mod, "BAND_HZ", None)
            if band is not None:
                return float(band[0]), float(band[1])
    b = catalog.card(card).band_hz
    if not b:
        return None
    return float(b[0] or 20.0), float(b[1] or 20000.0)


def _built_sentence() -> str:
    built = ["notch filter"] + [_lower_first(catalog.TOOL_LABELS[t]) for t in catalog.TOOLS_READY
                                if t not in _MASTERING_TOOLS and t != "notch"]
    if len(built) == 1:
        return "Only the notch filter is built so far."
    return f"Built so far: the {_join(built)}."


# ── Words and numbers ───────────────────────────────────────────────────

def _minus(text: str) -> str:
    return text.replace("-", "−")


def _num(v: float, digits: int = 1) -> str:
    """9.0 -> "9", -9.6 -> "−9.6"."""
    s = f"{float(v):.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return _minus("0" if s in ("-0", "") else s)


def _db1(v: float) -> str:
    """Always one decimal: -1.0 -> "−1.0"."""
    return _minus(f"{float(v):.1f}")


def _hz(v: float) -> str:
    v = float(v)
    if v >= 1000.0:
        return f"{float(f'{v / 1000.0:.3g}'):g} kHz"
    return f"{v:.0f} Hz"


def _clock(s: float, tenths: bool = False) -> str:
    s = max(0.0, float(s))
    if tenths:
        m, r = divmod(round(s, 1), 60)
        return f"{int(m)}:{r:04.1f}"
    m, r = divmod(int(round(s)), 60)
    return f"{m}:{r:02d}"


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _count(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _lower_first(s: str) -> str:
    """"De-esser" -> "de-esser", "Dynamic EQ" -> "dynamic EQ"."""
    return s[:1].lower() + s[1:] if len(s) > 1 and s[1].islower() else s


def _stage(key: str, name: str, gloss: str, *, on: bool, off: Optional[str] = None,
           **more: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "key": key, "stage": _STAGE[key], "name": name, "gloss": gloss, "on": bool(on),
        "standin": False, "tag": None, "off": None if on else off, "off_line": None,
        "verdict": None, "badges": [], "nb_badges": [], "band": None, "band_text": None,
        "paras": [], "steps": [], "fixes": [], "noted": [], "checks": [], "action": None,
        "note": None,
    }
    d.update(more)
    return d


def _action(label: str, target: str) -> Dict[str, str]:
    return {"label": label, "target": target}


def _tag(kind: str, text: str, stage: Optional[str] = None) -> Dict[str, Any]:
    return {"kind": kind, "text": text, "stage": stage}


def _row(card: catalog.Card, text: str, tag: Dict[str, Any], muted: bool = False) -> Dict[str, Any]:
    tool = catalog.TOOL_LABELS.get(card.tool) if card.tool else None
    return {"key": card.key, "icon": card.icon, "label": card.label, "tool": tool,
            "text": text, "tag": tag, "muted": muted}


# ── The stages ──────────────────────────────────────────────────────────

def _read(song: Mapping[str, Any]) -> Dict[str, Any]:
    badges = []
    if song.get("sample_rate"):
        badges.append(_hz(song["sample_rate"]))
    if song.get("bits"):
        badges.append(f"{int(song['bits'])}-bit" + (" float" if song.get("float") else ""))
    ch = song.get("channels")
    if ch:
        badges.append({1: "mono", 2: "stereo"}.get(int(ch), f"{int(ch)} channels"))
    if song.get("duration_s"):
        badges.append(_clock(song["duration_s"]))
    name = song.get("name")
    return _stage(
        "load", "Original file", "The whole song, as you loaded it.", on=True,
        verdict=f"On · {name}" if name else "On · no song loaded yet",
        badges=badges,
        paras=["Shimmer reads the whole original file, never the preview copy. "
               "Every stage after this starts from it."],
        note="Set by the file you loaded. No control here.")


def _trim(trim: Optional[Tuple[float, Optional[float]]],
          fades: Optional[Tuple[float, float]],
          duration_s: Optional[float]) -> Dict[str, Any]:
    d = _stage("edit", "Edge cuts and fades", "Cuts and fades at the start and end that you set.",
               on=trim is not None or fades is not None, off="no cuts or fades set",
               action=_action("Open Trim", "trim"))
    if trim is None and fades is None:
        d["paras"] = ["Place a cut or set a fade in the Trim card on the Master tab to remove "
                      "a bad start or end. With none, the song keeps its full length."]
        return d
    words, badges, paras = [], [], []
    if trim is not None:
        t_in, t_out = float(trim[0] or 0.0), trim[1]
        if t_in > 0:
            words.append(f"starts at {_clock(t_in, True)}")
            badges.append(f"in {_clock(t_in, True)}")
        if t_out is not None:
            words.append(f"ends at {_clock(t_out, True)}")
            badges.append(f"out {_clock(t_out, True)}")
        end = float(t_out) if t_out is not None else duration_s
        if end is not None:
            badges.append(f"keeps {_clock(max(0.0, end - t_in))}")
        paras.append("Your cuts remove a bad start or end before anything else runs, so no "
                     f"stage works on audio you cut. Each cut gets a {_num(TRIM_FADE_MS)} ms "
                     "fade, so it can’t click.")
        paras.append("The numbers in this view are measured on the whole song. With cuts "
                     "placed, the export’s can differ a little.")
    if fades is not None:
        f_in, f_out = fades
        if f_in > 0:
            words.append(f"{_num(f_in)} s fade in")
            badges.append(f"fade in {_num(f_in)} s")
        if f_out > 0:
            words.append(f"{_num(f_out)} s fade out")
            badges.append(f"fade out {_num(f_out)} s")
        paras.append("Your fades go on last, after mastering and before the file is written, "
                     "so the limiter can’t flatten them. A fade in starts at the in point and "
                     "a fade out ends at the cut. Each is held to half the song.")
        if f_out > 0:
            paras.append(f"The fade out falls evenly in dB: half way through it is "
                         f"{_num(FADE_OUT_RANGE_DB / 2)} dB down. Over its last tenth it closes "
                         "to silence.")
        if f_in > 0:
            paras.append("The fade in comes up quickly, then eases into full level, so the "
                         "first beat is not lost.")
    d["verdict"] = "On · " + ", ".join(words)
    d["badges"] = badges
    d["paras"] = paras
    return d


def _rate(fmt: catalog.Format, song_sr: Optional[int]) -> Dict[str, Any]:
    fixed = [f for f in catalog.FORMATS if f.sr]
    kinds = []
    for f in fixed:
        k = f.label.split()[0]
        if k not in kinds:
            kinds.append(k)
    rates = _join(sorted({_hz(f.sr) for f in fixed}))
    capped = [f for f in catalog.FORMATS if f.max_sr]
    paras = [f"The 16-bit release copies ({_join(kinds)}) need a set rate: {rates}. "
             + "".join(f"{f.label.split()[0]} holds {_hz(f.max_sr)} at most, so a song above "
                       "that is brought down to it. " for f in capped)
             + "Other formats keep the song’s own rate.",
             "When it runs, it runs before the fixes and the limiter, so the peak ceiling "
             "holds at the rate that is written."]
    note = "Set by the format in Output."
    target = fmt.sr or (fmt.max_sr if fmt.max_sr and song_sr and song_sr > fmt.max_sr else None)
    if not target:
        return _stage("rate", "Resample", "Changes the sample rate when the format needs it.",
                      on=False, off=f"{fmt.label} keeps the song’s rate", paras=paras, note=note)
    if song_sr == target:
        return _stage("rate", "Resample", "Changes the sample rate when the format needs it.",
                      on=False, off=f"the song is already at {_hz(target)}", paras=paras,
                      note=note)
    move = f"{_hz(song_sr)} → {_hz(target)}" if song_sr else f"to {_hz(target)}"
    return _stage("rate", "Resample", "Changes the sample rate when the format needs it.",
                  on=True,
                  verdict=(f"On · {_hz(song_sr)} to {_hz(target)}" if song_sr
                           else f"On · to {_hz(target)}"),
                  badges=[move], paras=paras, note=note)


def _fixes(s: Settings, notches: Optional[Sequence[Notch]], cards_on: List[str],
           noted: List[str]) -> Dict[str, Any]:
    # Fixed tones, as render() plans them (_tones_plan): the card's amount
    # scales each notch; "auto" applies them at full depth when the card has
    # not been set.
    a = _tones_amount(s)
    live = a > 0.0
    plan: Optional[List[Tuple[float, float]]] = None
    if not live:
        plan = []
    elif notches is not None:
        plan = [(float(n.hz), abs(float(n.depth_db)) * a) for n in notches]
    on = live and (plan is None or len(plan) > 0)

    rows: List[Dict[str, Any]] = []
    to_mastering = needs_mastering = not_built = 0
    runs: List[str] = []                 # cards whose built tool runs, besides the notch
    tones = catalog.card("tones")
    if on or "tones" in cards_on:
        if plan is None:
            rows.append(_row(tones, "Cuts the steady tones Analyze finds in the song.",
                             _tag("on", "On")))
        elif plan:
            deepest = max(d for _, d in plan)
            rows.append(_row(tones, f"Cuts {_count(len(plan), 'steady tone')}. "
                                    f"The deepest cut is −{_num(deepest)} dB.", _tag("on", "On")))
        else:
            rows.append(_row(tones, "No steady tones to cut in this song, so nothing is cut.",
                             _tag("nb", "Nothing to cut")))
    for key in cards_on:
        if key == "tones":
            continue
        c = catalog.card(key)
        if c.tool in _MASTERING_TOOLS:
            if not s.mastering:
                needs_mastering += 1
                rows.append(_row(c, "Needs mastering. Mastering is off, so this card changes "
                                    "nothing.", _tag("nb", "Needs mastering")))
            elif c.tool == "tone_target":
                to_mastering += 1
                rows.append(_row(c, "Handled by mastering, in the Tone stage.",
                                 _tag("stage", "In Tone", "tone")))
            else:
                to_mastering += 1
                lufs = catalog.loudness_target(s.loudness_target).lufs
                rows.append(_row(c, f"Handled by mastering, in the Master stage, at "
                                    f"{_num(lufs)} LUFS.", _tag("stage", "In Master", "master")))
        elif c.tool and c.tool in catalog.TOOLS_READY:
            runs.append(key)
            amt = _card_amount(s, key)
            depth = _tool_depth(key, amt)
            text = _CARD_GLOSS.get(key) or _TOOL_GLOSS.get(c.tool, "Runs this card's fix.")
            if c.modes:
                mode = catalog.card_mode(key, s.fix_modes.get(key))
                text += f" Works on: {dict(c.modes)[mode].split(' (')[0].lower()}."
                if mode in getattr(dict(_FIX_TOOLS).get(key), "STEM_MODES", ()):
                    text += (" This needs the Remix splitter. Without it, the fix works on "
                             "the centre of the mix, and the report says so.")
            if depth is not None:
                text += f" By up to {_num(depth)} dB at Amount {round(amt * 100)}%."
            if c.caution:
                text += f" {c.caution[1]}"
            rows.append(_row(c, text, _tag("on", "On")))
        elif c.tool in _HELD_BACK:
            runs.append(key)
            rows.append(_row(c, f"The {_lower_first(catalog.TOOL_LABELS[c.tool])} is built but "
                                "held back until it passes its tests. It runs from the command "
                                "line.", _tag("on", "Held back")))
        elif c.tool and c.tool not in catalog.TOOLS_READY:
            not_built += 1
            rows.append(_row(c, f"The {_lower_first(catalog.TOOL_LABELS[c.tool])} is not built "
                                "yet. This card changes nothing for now.",
                             _tag("nb", "Not built yet")))
        elif not c.tool:
            not_built += 1
            rows.append(_row(c, "No fix yet. This card changes nothing for now.",
                             _tag("nb", "No fix yet"), muted=True))
    no_fix = held = 0
    noted_rows = []
    for key in noted:
        c = catalog.card(key)
        if c.tool in _HELD_BACK:
            held += 1
            noted_rows.append(_row(c, f"The {_lower_first(catalog.TOOL_LABELS[c.tool])} is built "
                                      "but held back until it passes its tests. "
                                      f"{_SAVED}", _tag("nb", "Held back")))
        elif c.tool:
            not_built += 1
            noted_rows.append(_row(c, f"The {_lower_first(catalog.TOOL_LABELS[c.tool])} is not "
                                      f"built yet. {_SAVED}", _tag("nb", "Not built yet")))
        else:
            no_fix += 1
            noted_rows.append(_row(c, f"No fix yet. {_SAVED}", _tag("nb", "No fix yet"),
                                   muted=True))
    # Cards picked "on" with no tool at all count as "no fix yet" too.
    muted_on = sum(1 for r in rows if r["tag"]["text"] == "No fix yet")
    no_fix += muted_on
    not_built -= muted_on

    notch_on = on
    on = notch_on or bool(runs)
    # Two cards can share a tool (Harshness and Low-mid build-up both run
    # the dynamic EQ): name the tool once, with the cards it runs for.
    labels: List[str] = []
    for k in runs:
        tool = catalog.TOOL_LABELS[catalog.card(k).tool]
        share = [catalog.card(j).label for j in runs if catalog.card(j).tool == catalog.card(k).tool]
        label = f"{tool} ({_join(share)})" if len(share) > 1 else tool
        if label not in labels:
            labels.append(label)
    running = (["Notch filter"] if notch_on else []) + labels
    if len(running) > 1:
        name, gloss = ", ".join(running), "Runs the fix for each card that is on."
    elif runs and not notch_on:
        name, gloss = running[0], _TOOL_GLOSS.get(catalog.card(runs[0]).tool, "")
    else:
        name, gloss = "Notch filter", "Cuts steady whistles or whines at one pitch."
    d = _stage("fixes", name, gloss,
               on=on, off="no steady tones to cut" if live else "no fix is on",
               fixes=rows, noted=noted_rows,
               action=_action("Open What do you hear?", "hear"))
    ranges = [(k, _card_band(k)) for k in runs]
    ranges = [(k, r) for k, r in ranges if r]
    spans = [f"{catalog.card(k).label} {_hz(lo)}–{_hz(hi)}" for k, (lo, hi) in ranges]
    if plan or ranges:
        d["band"] = {"notches": [hz for hz, _ in (plan or [])]}
        if ranges:
            d["band"]["ranges"] = [[lo, hi] for _, (lo, hi) in ranges]
        parts = ([f"Notches at {_join([_hz(hz) for hz, _ in plan])}"] if plan else []) + spans
        d["band_text"] = "; ".join(parts) + "."
    else:
        d["band"] = {"empty": True}
        d["band_text"] = ("The notches show here once a song is loaded." if plan is None
                          else "No notches.")
    others = len(rows) - (1 if rows and rows[0]["key"] == "tones" else 0) + len(noted_rows)
    built = _built_sentence()
    if on:
        badges = []
        if notch_on and plan:
            deepest = max(dd for _, dd in plan)
            badges += [_count(len(plan), "notch", "notches"), f"deepest −{_num(deepest)} dB"]
        if notch_on:
            badges.append(f"Amount {round(a * 100)}%")
        for k in runs:
            tool = catalog.card(k).tool
            shared = sum(1 for j in runs if catalog.card(j).tool == tool) > 1
            name = catalog.card(k).label if shared else catalog.TOOL_LABELS[tool]
            badges.append(f"{name} {round(_card_amount(s, k) * 100)}%")
        nb = []
        if held:
            nb.append(f"{held} held back")
        if not_built:
            nb.append(f"{not_built} not built yet")
        if no_fix:
            nb.append(f"{no_fix} no fix yet")
        badges += nb
        d["badges"], d["nb_badges"] = badges, nb
        if others:
            n_run = int(notch_on) + len(runs)
            parts = [f"{n_run} fix{'es' if n_run != 1 else ''} run{'s' if n_run == 1 else ''}"]
            if to_mastering:
                parts.append(f"{to_mastering} go{'es' if to_mastering == 1 else ''} to mastering")
            if needs_mastering:
                parts.append(f"{needs_mastering} need{'s' if needs_mastering == 1 else ''} mastering")
            if held:
                parts.append(f"{held} held back")
            if not_built:
                parts.append(f"{not_built} not built yet")
            if no_fix:
                parts.append(f"{no_fix} no fix yet")
            d["verdict"] = " · ".join(parts)
            d["paras"] = ["One tool runs for each card that is on under What do you hear? "
                          + built]
        else:
            d["verdict"] = ("On · " + f"{_count(len(plan), 'notch', 'notches')}, deepest "
                            f"−{_num(max(dd for _, dd in plan))} dB" if plan
                            else "On · cuts the steady tones Analyze finds")
            what = (f"cuts {_count(len(plan), 'steady tone')}" if plan
                    else "cuts the steady tones Analyze finds")
            d["paras"] = ["One tool runs for each card that is on under What do you hear? "
                          f"Fixed tones is on, so the notch filter {what}.",
                          f"Each notch is about {_num(notch_width_hz(48000), 0)} Hz wide at "
                          f"48 kHz and at most {_num(notch_mod.MAX_NOTCH_DEPTH_DB, 0)} dB deep, "
                          "so the music on either side is kept. Only tones at "
                          f"{_hz(notch_mod.MIN_NOTCH_HZ)} and up are cut.",
                          f"A tone under {_hz(notch_mod.NOTE_GUARD_HZ)} that sits within "
                          f"{_num(notch_mod.NOTE_CENTS, 0)} cents of a musical note, off the "
                          "generator’s usual pitches, is taken for a held note and left alone."]
    else:
        d["paras"] = ["One tool runs for each card that is on under What do you hear? "
                      + (built[:-1] + ": turn on Fixed tones to use it."
                         if built.startswith("Only") else built + " Turn on a card to use it.")]
    return d


def _tone(s: Settings, reference: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    band = {"whole": True}
    band_text = "Works across the whole spectrum, one band at a time."
    act = _action("Open Mastering", "mastering")
    tilt = _TILT.get(s.tilt, s.tilt.title())
    limit = _num(tone.MATCH_LIMIT_DB)
    if not s.mastering:
        return _stage("tone", "Tone match", "Moves the tone toward Shimmer’s built-in target.",
                      on=False, off="mastering is off", band=band, band_text=band_text,
                      paras=["Tone match is part of mastering. Turn mastering on to shape the "
                             "tone toward Shimmer’s tone target, or toward a reference track."],
                      action=act)
    tilt_db = tone.TILT_POSITIONS.get(s.tilt, 0.0)
    tilt_words = (f"The {tilt} tilt adds up to {_num(abs(tilt_db))} dB at the "
                  f"{'top' if tilt_db > 0 else 'bottom'} of the spectrum, and takes as much "
                  f"from the {'bottom' if tilt_db > 0 else 'top'}." if tilt_db else "")
    top = (f"Nothing is boosted at or above 90% of the frequency where the song’s top end "
           f"stops, or above {_hz(tone.boost_limit_hz(None))} when that point can’t be "
           "found. Up there it is mostly noise.")
    if reference is not None:
        pct = round(s.match_amount * 100)
        name = reference.get("name") or "your reference"
        return _stage(
            "tone", "Reference match", "Moves the tone toward your reference track.", on=True,
            verdict=f"On · matching {name}, Amount {pct}%",
            badges=[f"Amount {pct}%", f"{tilt} tilt", f"±{limit} dB max"],
            band=band, band_text=band_text,
            paras=["Mastering shapes the tone toward your reference track, band by band. Both "
                   "songs are matched in level first, so only the tone is compared. The "
                   "difference is smoothed over about an octave, so one odd band can’t pull "
                   "the curve.",
                   f"It takes {pct}% of the difference, and no band moves more than {limit} dB "
                   f"either way. In 5–12 kHz, where fizz lives, no band is boosted more than "
                   f"{_num(tone._HARSH_MAX_BOOST_DB)} dB.",
                   "Where either song has no top end to compare, that part is not matched. "
                   + top]
            + ([tilt_words] if tilt_words else []),
            action=act)
    inten = _INTENSITY.get(s.intensity, s.intensity.title())
    share = round(tone.INTENSITY_STRENGTH.get(s.intensity, 0.55) * 100)
    boost, cut = _num(TONE_MAX_BOOST_DB), _num(TONE_MAX_CUT_DB)
    return _stage(
        "tone", "Tone match", "Moves the tone toward Shimmer’s built-in target.", on=True,
        verdict=f"On · Tone match {inten}, Tilt {tilt}",
        badges=[inten, f"{tilt} tilt", f"+{boost} / −{cut} dB max"],
        band=band, band_text=band_text,
        paras=["Mastering shapes the tone toward Shimmer’s tone target, band by band. The "
               "curve is worked out from the song as it came in, before the fixes.",
               f"Tone match {inten} makes {share}% of the move (Low 25%, Medium 55%, High "
               f"85%). No band is boosted more than {boost} dB or cut more than {cut} dB.",
               top]
        + ([tilt_words] if tilt_words else [])
        + ["To move toward a reference track instead, set the tone target to Reference "
           f"track and load one. It moves by the Amount you set, within ±{limit} dB."],
        action=act)


def _eq(s: Settings, sr: int) -> Dict[str, Any]:
    act = _action("Open Parametric EQ", "eq")
    gloss = "Your EQ bands, plus any Suggested EQ moves you applied."
    on = bool(s.eq_enabled and user_eq.designs(s.eq_bands, sr))
    if not on:
        return _stage("eq", "Parametric EQ", gloss, on=False,
                      off="EQ is off" if not s.eq_enabled else "no bands set",
                      band={"empty": True}, band_text="No bands set.",
                      paras=["Add bands, or apply Suggested EQ moves, in the Parametric EQ "
                             "section of the Master tab. With EQ off, the song passes through "
                             "this stage as it is."],
                      action=act)
    # Only bands that change anything: a 0 dB bell or shelf is left out,
    # as the engine leaves it out (audio.eq.designs).
    bands = [b for b in s.eq_bands if b.enabled and user_eq.designs([b], sr)]
    badges = []
    for b in bands:
        text = f"{_EQ_TYPE.get(b.type, b.type)} {_hz(b.freq_hz)}"
        if b.type in ("bell", "low_shelf", "high_shelf"):
            text += f" {'+' if b.gain_db > 0 else ''}{_num(b.gain_db)} dB"
        badges.append(text)
    paras = ["Your EQ bands run in order, after the tone match and before the loudness gain."]
    if any(b.type in _ONE_WAY for b in bands):
        paras.append("Low-cut and high-cut run one way, so they add no pre-echo.")
    return _stage("eq", "Parametric EQ", gloss, on=True,
                  verdict=f"On · {_count(len(bands), 'band')}",
                  badges=[_count(len(bands), "band")] + badges,
                  band={"notches": [b.freq_hz for b in bands]},
                  band_text=f"Bands at {_join([_hz(b.freq_hz) for b in bands])}.",
                  paras=paras, action=act)


def _ceiling_words(fmt: catalog.Format) -> str:
    lossless = [f for f in catalog.FORMATS if not f.lossy]
    lossy = [f for f in catalog.FORMATS if f.lossy]

    def kinds(fs):
        out = []
        for f in fs:
            k = f.label.split()[0]
            if k not in out:
                out.append(k)
        return _join(out)
    c = _db1(fmt.ceiling_dbtp)
    if fmt.lossy:
        return (f"Holds every peak at or below {c} dBTP before encoding, the ceiling for "
                f"{kinds(lossy)}: the encoder needs room, as it can push peaks higher. "
                f"{kinds(lossless)} use {_db1(lossless[0].ceiling_dbtp)} dBTP.")
    return (f"Holds every peak at or below {c} dBTP, the ceiling for {kinds(lossless)}. "
            f"{kinds(lossy)} use {_db1(lossy[0].ceiling_dbtp)} dBTP.")


def notch_width_hz(sr: int) -> float:
    """A notch's width: notch.NOTCH_BW_BINS analysis bins of sr / 4096."""
    return notch_mod.NOTCH_BW_BINS * sr / 4096.0


def _signed(v: float) -> str:
    """4.24 -> "+4.2", -1.3 -> "−1.3", 0.01 -> "0"."""
    s = _num(v)
    return s if s.startswith("−") or s == "0" else "+" + s


_UNKNOWN_GAIN = "The amount shows here once the preview has played with these settings."


def _master(s: Settings, fmt: catalog.Format, changed: bool,
            gain_db: Optional[float] = None, gain_checked: bool = True) -> Dict[str, Any]:
    act = _action("Open Mastering", "mastering")
    gain = None if gain_db is None else f"{_signed(gain_db)} dB"
    if s.mastering:
        t = catalog.loudness_target(s.loudness_target)
        lufs, ceil, cut = _num(t.lufs), _db1(fmt.ceiling_dbtp), _num(LOW_CUT_HZ)
        return _stage(
            "master", "Loudness and limiter",
            "Sets the release level and keeps peaks under the ceiling.", on=True,
            verdict=(f"On · {t.label}, {lufs} LUFS"
                     + ((f", {gain} gain" if gain_checked else f", about {gain} gain")
                        if gain else "") + f", ceiling {ceil} dBTP"),
            badges=([f"{gain} gain" if gain_checked else f"about {gain} gain"] if gain else [])
            + [f"{lufs} LUFS", f"{ceil} dBTP", f"{cut} Hz low-cut", "one static gain"],
            band={"whole": True, "from": LOW_CUT_HZ, "tick": LOW_CUT_HZ},
            band_text=f"Works on the whole signal. The mark is the low-cut at {cut} Hz.",
            steps=[[f"Low-cut at {cut} Hz", f"Removes rumble below {cut} Hz: 12 dB per "
                                            f"octave, 3 dB down at {cut} Hz. It runs one way, "
                                            "so it adds no pre-echo."],
                   [f"Gain to {lufs} LUFS",
                    ("One static gain for the whole song"
                     + (f": {gain}." if gain and gain_checked
                        else f": about {gain} so far." if gain else ".")
                     + " It does not ride up and down. After the peak shaper and limiter, "
                     "Shimmer measures the finished song once and corrects the gain, so the "
                     "song lands close to its target."
                     + ("" if gain and gain_checked
                        else " The exact amount shows once the preview has played with these "
                             "settings." if gain else f" {_UNKNOWN_GAIN}"))],
                   ["Peak shaper", "A soft clipper that rounds off the tallest peaks before "
                                   "the limiter. It does most of the peak work, so the limiter "
                                   "only catches what is left. It works at 4× the sample rate "
                                   "and both channels get the same gain, so the tones it adds "
                                   "stay about 64 dB down."],
                   ["True-peak limiter", _ceiling_words(fmt)]],
            action=act)
    if s.preserve_volume:
        most = _num(20.0 * math.log10(_PRESERVE_MAX_SCALE), 0)
        d = _stage(
            "master", "Preserve volume", "Puts the song back at its own level.", on=changed,
            standin=True, tag="Mastering off",
            off_line="Mastering is off: no loudness target, no tone match, no limiter.",
            band={"whole": True}, band_text="Works on the whole signal.",
            action=act)
        if changed:
            d["verdict"] = (f"On · {gain}, back to the song’s own level" if gain
                            else "On · back to the song’s own level")
            d["badges"] = ([gain] if gain else []) + ["no limiter", f"at most ±{most} dB"]
            d["paras"] = ["The fixes and your EQ change the level. Preserve volume adds one "
                          "gain for the whole song, so its average level (RMS) matches the "
                          "song as it came in." + ("" if gain else f" {_UNKNOWN_GAIN}"),
                          "It never lifts a peak past "
                          f"{_num(20.0 * math.log10(_PRESERVE_PEAK), 2)} dBFS, just under full "
                          "scale, and never moves the level more than "
                          f"{most} dB either way. So a song whose peaks are already near the "
                          "top can end up a little quieter than it came in. There is no limiter "
                          "here."]
        else:
            d["verdict"] = "Nothing to put back"
            d["badges"] = ["nothing to do"]
            d["paras"] = ["No stage before this one changes the sound, so the song is already "
                          "at its own level."]
        return d
    return _stage("master", "Loudness and limiter",
                  "Sets the release level and keeps peaks under the ceiling.", on=False,
                  off="mastering is off", band={"whole": True},
                  band_text="Works on the whole signal.",
                  paras=["Mastering is off, and so is Preserve volume. The song keeps whatever "
                         "level the stages before leave it at."],
                  action=act)


def _export(s: Settings, fmt: catalog.Format, out_sr: Optional[int], tags: bool,
            save_folder: str, fades: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
    verdict = f"On · {fmt.label}" + (f" at {_hz(out_sr)}" if out_sr and not fmt.sr else "")
    badges = []
    if out_sr:
        badges.append(_hz(out_sr))
    if fmt.bits == 16:
        badges.append("dithered")
    badges += ["tags on" if tags else "tags off",
               "silence trim on" if s.trim_silence else "silence trim off"]
    folder = os.path.basename(os.path.normpath(save_folder)) if save_folder else ""
    if folder:
        badges.append(f"saved to {folder}")
    paras = ["Writes the song in the format picked in Output. "
             + ("The tags from the Tags section go into the file: title (the file name when "
                "it is empty), artist, album, album artist, genre, year, track, copyright, "
                "ISRC, and a comment saying Shimmer made it." if tags
                else "Tags are off, so none are written."),
             (f"Silence trim is on: quiet below {_num(silence.trim_silence.__defaults__[0])} dBFS "
              f"at the start and end is cut, keeping "
              f"{_num(silence.trim_silence.__defaults__[1])} ms before the song and "
              f"{_num(silence.trim_silence.__defaults__[2])} ms after it, with "
              f"{_num(silence.trim_silence.__defaults__[3])} ms fades.") if s.trim_silence
             else "Silence trim is off, so the start and end stay as they are."]
    if fmt.bits == 16:
        paras.append("The 16-bit copy gets TPDF dither, so quiet parts fade out smoothly "
                     "instead of turning grainy."
                     + (" It goes on after your fades." if fades else ""))
    if fmt.lossy:
        paras.append("After encoding, Shimmer decodes the file and checks its peaks. If the "
                     "encoder pushed one over −1.0 dBTP, the file is turned down by that much "
                     "and encoded again, up to 3 times.")
    if not s.mastering:
        paras.append("Any sample past full scale is clipped to it, and the report counts "
                     "them. With mastering off, nothing else stops that.")
    if folder:
        paras.append(f"When the run ends, a copy is saved to {save_folder}.")
    return _stage("export", fmt.label, "Writes the finished file, with your tags.", on=True,
                  verdict=verdict, badges=badges, paras=paras,
                  action=_action("Open Output", "output"))


def _report(s: Settings) -> Dict[str, Any]:
    paras = ["Loudness and true peak are read from the file Shimmer just wrote. The other "
             "checks measure the finished song just before it is written. You get one verdict "
             "first, then any check that needs a look.",
             "It also shows how much each streaming service will turn the song up or down."]
    if catalog.output_format(s.format).lossy:
        paras.append("A lossy file is graded as a listener decodes it: its true peak passes "
                     f"at or under {_db1(catalog.LOSSY_FILE_LIMIT_DBTP)} dBTP. The limiter’s "
                     "lower ceiling is only room for the encoder.")
    if not s.mastering:
        return _stage("report", "Release check", "Measures the exported file. Changes nothing.",
                      on=False, off="mastering is off",
                      paras=["The release check runs with mastering on. With it off, the "
                             "report still shows the loudness before and after."] + paras,
                      checks=list(CHECKS), note="Runs on its own. No control here.")
    return _stage("report", "Release check", "Measures the exported file. Changes nothing.",
                  on=True, verdict="On · after export",
                  badges=["after export", "measures only"],
                  paras=paras, checks=list(CHECKS), note="Runs on its own. No control here.")


# ── The whole chain ─────────────────────────────────────────────────────

def describe_chain(settings: Optional[Settings] = None, *,
                   song: Optional[Mapping[str, Any]] = None,
                   notches: Optional[Sequence[Notch]] = None,
                   trim: Optional[Tuple[float, Optional[float]]] = None,
                   fades: Optional[Tuple[float, float]] = None,
                   reference: Optional[Mapping[str, Any]] = None,
                   cards_on: Optional[Sequence[str]] = None,
                   noted: Sequence[str] = (),
                   tags: bool = True,
                   save_folder: str = "",
                   gain_db: Optional[float] = None,
                   gain_checked: bool = True) -> Dict[str, Any]:
    """The nine stages for these settings, and a summary.

    song         the loaded song's facts: name, sample_rate, bits, float,
                 channels, duration_s (any may be missing), or None
    notches      the notches a run would use (the screen's list or the
                 scan's), or None when no song is loaded
    trim         (in_s, out_s) when cuts are placed (out_s None: the end)
    fades        (fade_in_s, fade_out_s) when a fade is set (0: none)
    reference    the reference track's facts, when the tone target is set
                 to it and one is loaded
    cards_on     "What do you hear?" cards that are on; None: from the
                 settings' fixes
    noted        cards picked as "noted" (no tool built yet)
    gain_db      the gain Master (or Preserve volume) adds, when a render has
                 already worked it out (render.known_gain); None: not known
    gain_checked False when gain_db is the first-pass gain, before the
                 check against the finished song

    Each stage: key, stage (its label), name, gloss, on, off (why not),
    standin and tag (Master with mastering off), off_line, verdict, badges
    (nb_badges drawn dashed), band, band_text, paras, steps, fixes and
    noted (card rows), checks, and an action or a note.
    """
    s = settings if settings is not None else Settings()
    song = dict(song or {})
    fmt = catalog.output_format(s.format)
    song_sr = int(song["sample_rate"]) if song.get("sample_rate") else None
    out_sr = fmt.rate_for(song_sr) if song_sr else fmt.sr
    picked = set(cards_on if cards_on is not None
                 else [k for k, v in s.fixes.items() if v > 0])
    on_keys = [c.key for c in catalog.CARDS if c.key in picked]
    noted_keys = [c.key for c in catalog.CARDS if c.key in set(noted) and c.key not in picked]

    fixes = _fixes(s, notches, on_keys, noted_keys)
    eq = _eq(s, int(out_sr or 48000))
    stages = [
        _read(song),
        _trim(trim, fades, song.get("duration_s")),
        _rate(fmt, song_sr),
        fixes,
        _tone(s, reference),
        eq,
        _master(s, fmt, changed=fixes["on"] or eq["on"], gain_db=gain_db,
                gain_checked=gain_checked),
        _export(s, fmt, out_sr, tags, save_folder, fades),
        _report(s),
    ]

    n_on = sum(1 for d in stages if d["on"])
    sound = [d["stage"] for d in stages
             if d["on"] and d["key"] in ("rate", "fixes", "tone", "eq", "master")]
    no_tool = [k for k in on_keys
               if catalog.card(k).tool not in _MASTERING_TOOLS
               and catalog.card(k).tool not in catalog.TOOLS_READY
               and catalog.card(k).tool not in _HELD_BACK]
    if not s.mastering:
        text = ("Mastering is off, so the song keeps its own level." if s.preserve_volume
                else "Mastering and Preserve volume are off.")
    elif no_tool:
        n = len(on_keys)
        text = (f"{_count(n, 'card')} {'is' if n == 1 else 'are'} on, and {len(no_tool)} of "
                f"them {'has' if len(no_tool) == 1 else 'have'} no tool built yet.")
    elif noted_keys:
        n, k = len(on_keys), len(noted_keys)
        text = (f"{_count(n, 'card')} {'is' if n == 1 else 'are'} on, and {k} more "
                f"{'is' if k == 1 else 'are'} noted. Noted cards change nothing yet.")
    elif sound:
        text = f"The sound changes in {_join(sound)}."
    else:
        text = "Nothing changes the sound."

    fmt_chip = f"{fmt.label} · {_hz(out_sr)}" if out_sr and not fmt.sr else fmt.label
    # Fixed tones runs on its own until a card is set ("auto"): count it.
    auto_tones = "tones" not in on_keys and any(
        r["key"] == "tones" and r["tag"]["kind"] == "on" for r in fixes["fixes"])
    cards_chip = _count(len(on_keys) + int(auto_tones), "card") + " on" + (
        f" · {len(noted_keys)} noted" if noted_keys else "")
    if s.mastering:
        t = catalog.loudness_target(s.loudness_target)
        facts = [f"{t.label} · {_num(t.lufs)} LUFS", f"Ceiling {_db1(fmt.ceiling_dbtp)} dBTP",
                 fmt_chip, cards_chip]
    else:
        facts = ["Mastering off", f"Preserve volume {'on' if s.preserve_volume else 'off'}",
                 fmt_chip, cards_chip]
    return {"stages": stages,
            "summary": {"on": n_on, "total": len(stages), "text": text, "facts": facts}}
