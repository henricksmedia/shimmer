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
from .audio import eq as user_eq
from .master import tone
from .render import _FIX_TOOLS, _PRESERVE_MAX_SCALE, LOW_CUT_HZ, _tones_amount
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
    "dynamic_eq": "Cuts a band only while it rings out above the rest.",
    "declick": "Finds short pops and crackle and fills them in.",
    "voice_denoise": "Takes out the grainy hiss that rides on the voice.",
    "spectral_denoise": "Turns down fizzy, flickering hiss up top, only where a trained "
                        "model hears it.",
}


def _card_amount(s: Settings, key: str) -> float:
    return float(s.fixes.get(key, catalog.card(key).default_amount))


def _tool_depth(card: str, amount: float) -> Optional[float]:
    """The deepest cut a built tool makes at this Amount, from its own
    settings (render._FIX_TOOLS), or None when it has no such limit."""
    for c, mod in _FIX_TOOLS:
        if c == card:
            top = getattr(mod, "MAX_CUT_DB", None)
            if top is None and hasattr(mod, "cfg"):
                top = getattr(mod.cfg, "max_cut_db", None)
            return None if top is None else float(top) * float(amount)
    return None


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
          duration_s: Optional[float]) -> Dict[str, Any]:
    d = _stage("edit", "Edge cuts", "Cuts at the start and end that you place.",
               on=trim is not None, off="no cuts placed", action=_action("Open Trim", "trim"))
    if trim is None:
        d["paras"] = ["Place a cut in the Trim card on the Master tab to remove a bad start "
                      "or end. With no cuts, the song keeps its full length."]
        return d
    t_in, t_out = float(trim[0] or 0.0), trim[1]
    words, badges = [], []
    if t_in > 0:
        words.append(f"starts at {_clock(t_in, True)}")
        badges.append(f"in {_clock(t_in, True)}")
    if t_out is not None:
        words.append(f"ends at {_clock(t_out, True)}")
        badges.append(f"out {_clock(t_out, True)}")
    end = float(t_out) if t_out is not None else duration_s
    if end is not None:
        badges.append(f"keeps {_clock(max(0.0, end - t_in))}")
    d["verdict"] = "On · " + (", ".join(words) if words else "cuts placed")
    d["badges"] = badges
    d["paras"] = ["Your cuts remove a bad start or end before anything else runs, so no "
                  "stage works on audio you cut."]
    return d


def _rate(fmt: catalog.Format, song_sr: Optional[int]) -> Dict[str, Any]:
    fixed = [f for f in catalog.FORMATS if f.sr]
    kinds = []
    for f in fixed:
        k = f.label.split()[0]
        if k not in kinds:
            kinds.append(k)
    rates = _join(sorted({_hz(f.sr) for f in fixed}))
    paras = [f"Only the 16-bit release copies ({_join(kinds)}) need a set rate: {rates}. "
             "Other formats keep the song’s own rate.",
             "When it runs, it runs before the fixes and the limiter, so the peak ceiling "
             "holds at the rate that is written."]
    note = "Set by the format in Output."
    if not fmt.sr:
        return _stage("rate", "Resample", "Changes the sample rate when the format needs it.",
                      on=False, off=f"{fmt.label} keeps the song’s rate", paras=paras, note=note)
    if song_sr == fmt.sr:
        return _stage("rate", "Resample", "Changes the sample rate when the format needs it.",
                      on=False, off=f"the song is already at {_hz(fmt.sr)}", paras=paras,
                      note=note)
    move = f"{_hz(song_sr)} → {_hz(fmt.sr)}" if song_sr else f"to {_hz(fmt.sr)}"
    return _stage("rate", "Resample", "Changes the sample rate when the format needs it.",
                  on=True,
                  verdict=(f"On · {_hz(song_sr)} to {_hz(fmt.sr)}" if song_sr
                           else f"On · to {_hz(fmt.sr)}"),
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
            text = _TOOL_GLOSS.get(c.tool, "Runs this card's fix.")
            if c.modes:
                mode = catalog.card_mode(key, s.fix_modes.get(key))
                text += f" Works on: {dict(c.modes)[mode].split(' (')[0].lower()}."
            if depth is not None:
                text += f" By up to {_num(depth)} dB at Amount {round(amt * 100)}%."
            rows.append(_row(c, text, _tag("on", "On")))
        elif c.tool and c.tool not in catalog.TOOLS_READY:
            not_built += 1
            rows.append(_row(c, f"The {_lower_first(catalog.TOOL_LABELS[c.tool])} is not built "
                                "yet. This card changes nothing for now.",
                             _tag("nb", "Not built yet")))
        elif not c.tool:
            not_built += 1
            rows.append(_row(c, "No fix yet. This card changes nothing for now.",
                             _tag("nb", "No fix yet"), muted=True))
    noted_rows = []
    for key in noted:
        c = catalog.card(key)
        if c.tool:
            noted_rows.append(_row(c, f"The {_lower_first(catalog.TOOL_LABELS[c.tool])} is not "
                                      f"built yet. {_SAVED}", _tag("nb", "Not built yet")))
        else:
            noted_rows.append(_row(c, f"No fix yet. {_SAVED}", _tag("nb", "No fix yet"),
                                   muted=True))

    notch_on = on
    on = notch_on or bool(runs)
    running = (["Notch filter"] if notch_on else []) + \
        [catalog.TOOL_LABELS[catalog.card(k).tool] for k in runs]
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
    if plan:
        d["band"] = {"notches": [hz for hz, _ in plan]}
        d["band_text"] = f"Notches at {_join([_hz(hz) for hz, _ in plan])}."
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
            badges.append(f"{catalog.TOOL_LABELS[catalog.card(k).tool]} "
                          f"{round(_card_amount(s, k) * 100)}%")
        nb = []
        if not_built + len(noted_rows):
            nb = [f"{not_built + len(noted_rows)} not built yet"]
            badges.insert(1, nb[0])
        d["badges"], d["nb_badges"] = badges, nb
        if others:
            n_run = int(notch_on) + len(runs)
            parts = [f"{n_run} fix{'es' if n_run != 1 else ''} run{'s' if n_run == 1 else ''}"]
            if to_mastering:
                parts.append(f"{to_mastering} go{'es' if to_mastering == 1 else ''} to mastering")
            if needs_mastering:
                parts.append(f"{needs_mastering} need{'s' if needs_mastering == 1 else ''} mastering")
            if not_built + len(noted_rows):
                parts.append(f"{not_built + len(noted_rows)} not built yet")
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
                          "Each notch is narrow, so the music on either side is kept."]
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
    if reference is not None:
        pct = round(s.match_amount * 100)
        name = reference.get("name") or "your reference"
        return _stage(
            "tone", "Reference match", "Moves the tone toward your reference track.", on=True,
            verdict=f"On · matching {name}, Amount {pct}%",
            badges=[f"Amount {pct}%", f"{tilt} tilt", f"±{limit} dB max"],
            band=band, band_text=band_text,
            paras=["Mastering shapes the tone toward your reference track, band by band. Both "
                   "songs are matched in level first, so only the tone is compared.",
                   f"It takes {pct}% of the difference, and no band moves more than {limit} dB "
                   "either way.",
                   "Where the reference has no top end to compare, your song’s own top is kept."],
            action=act)
    inten = _INTENSITY.get(s.intensity, s.intensity.title())
    boost, cut = _num(TONE_MAX_BOOST_DB), _num(TONE_MAX_CUT_DB)
    return _stage(
        "tone", "Tone match", "Moves the tone toward Shimmer’s built-in target.", on=True,
        verdict=f"On · Tone match {inten}, Tilt {tilt}",
        badges=[inten, f"{tilt} tilt", f"+{boost} / −{cut} dB max"],
        band=band, band_text=band_text,
        paras=["Mastering shapes the tone toward Shimmer’s tone target: the middle of hundreds "
               "of finished masters, band by band.",
               f"No band is boosted more than {boost} dB or cut more than {cut} dB.",
               "With a reference track loaded, it moves toward that track instead, by the Amount "
               f"you set, within ±{limit} dB."],
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
    bands = [b for b in s.eq_bands if b.enabled]
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
        return (f"Holds every peak at or below {c} dBTP, the ceiling for {kinds(lossy)}: the "
                f"encoder needs room. {kinds(lossless)} use {_db1(lossless[0].ceiling_dbtp)} dBTP.")
    return (f"Holds every peak at or below {c} dBTP, the ceiling for {kinds(lossless)}. "
            f"{kinds(lossy)} use {_db1(lossy[0].ceiling_dbtp)} dBTP.")


def _signed(v: float) -> str:
    """4.24 -> "+4.2", -1.3 -> "−1.3", 0.01 -> "0"."""
    s = _num(v)
    return s if s.startswith("−") or s == "0" else "+" + s


_UNKNOWN_GAIN = "The amount shows here once the preview has played with these settings."


def _master(s: Settings, fmt: catalog.Format, changed: bool,
            gain_db: Optional[float] = None) -> Dict[str, Any]:
    act = _action("Open Mastering", "mastering")
    gain = None if gain_db is None else f"{_signed(gain_db)} dB"
    if s.mastering:
        t = catalog.loudness_target(s.loudness_target)
        lufs, ceil, cut = _num(t.lufs), _db1(fmt.ceiling_dbtp), _num(LOW_CUT_HZ)
        return _stage(
            "master", "Loudness and limiter",
            "Sets the release level and keeps peaks under the ceiling.", on=True,
            verdict=(f"On · {t.label}, {lufs} LUFS"
                     + (f", {gain} gain" if gain else "") + f", ceiling {ceil} dBTP"),
            badges=([f"{gain} gain"] if gain else [])
            + [f"{lufs} LUFS", f"{ceil} dBTP", f"{cut} Hz low-cut", "one static gain"],
            band={"whole": True, "from": LOW_CUT_HZ, "tick": LOW_CUT_HZ},
            band_text=f"Works on the whole signal. The mark is the low-cut at {cut} Hz.",
            steps=[[f"Low-cut at {cut} Hz", f"Removes rumble below {cut} Hz."],
                   [f"Gain to {lufs} LUFS",
                    (f"One static gain for the whole song: {gain}. It does not ride up and "
                     "down." if gain else "One static gain for the whole song. It does not "
                     f"ride up and down. {_UNKNOWN_GAIN}")],
                   ["Peak shaper", "Softly rounds the tallest peaks, so the limiter has less "
                                   "to do."],
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
            d["paras"] = ["The fixes can change the level a little. Preserve volume adds one "
                          "gain for the whole song, so it plays at the level it came in at."
                          + ("" if gain else f" {_UNKNOWN_GAIN}"),
                          "It keeps peaks just under full scale and never moves the level more "
                          f"than {most} dB either way."]
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
            save_folder: str) -> Dict[str, Any]:
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
             + ("Title, artist and album tags go into the file." if tags
                else "Tags are off, so none are written."),
             "Silence trim is on, so silence at the start and end is cut." if s.trim_silence
             else "Silence trim is off, so the start and end stay as they are."]
    if fmt.bits == 16:
        paras.append("The 16-bit copy gets TPDF dither, so quiet parts fade out smoothly "
                     "instead of turning grainy.")
    if fmt.lossy:
        paras.append("After encoding, Shimmer decodes the file and checks its peaks. If the "
                     "encoder pushed one over −1.0 dBTP, the file is turned down and encoded "
                     "again.")
    if folder:
        paras.append(f"When the run ends, a copy is saved to {save_folder}.")
    return _stage("export", fmt.label, "Writes the finished file, with your tags.", on=True,
                  verdict=verdict, badges=badges, paras=paras,
                  action=_action("Open Output", "output"))


def _report() -> Dict[str, Any]:
    return _stage("report", "Release check", "Measures the exported file. Changes nothing.",
                  on=True, verdict="Runs after export, on the file itself",
                  badges=["after export", "measures only"],
                  paras=["Shimmer opens the file it just wrote and checks it. You get one "
                         "verdict first, then any check that needs a look."],
                  checks=list(CHECKS), note="Runs on its own. No control here.")


# ── The whole chain ─────────────────────────────────────────────────────

def describe_chain(settings: Optional[Settings] = None, *,
                   song: Optional[Mapping[str, Any]] = None,
                   notches: Optional[Sequence[Notch]] = None,
                   trim: Optional[Tuple[float, Optional[float]]] = None,
                   reference: Optional[Mapping[str, Any]] = None,
                   cards_on: Optional[Sequence[str]] = None,
                   noted: Sequence[str] = (),
                   tags: bool = True,
                   save_folder: str = "",
                   gain_db: Optional[float] = None) -> Dict[str, Any]:
    """The nine stages for these settings, and a summary.

    song         the loaded song's facts: name, sample_rate, bits, float,
                 channels, duration_s (any may be missing), or None
    notches      the notches a run would use (the screen's list or the
                 scan's), or None when no song is loaded
    trim         (in_s, out_s) when cuts are placed (out_s None: the end)
    reference    the reference track's facts, when the tone target is set
                 to it and one is loaded
    cards_on     "What do you hear?" cards that are on; None: from the
                 settings' fixes
    noted        cards picked as "noted" (no tool built yet)
    gain_db      the gain Master (or Preserve volume) adds, when a render has
                 already worked it out (render.known_gain); None: not known

    Each stage: key, stage (its label), name, gloss, on, off (why not),
    standin and tag (Master with mastering off), off_line, verdict, badges
    (nb_badges drawn dashed), band, band_text, paras, steps, fixes and
    noted (card rows), checks, and an action or a note.
    """
    s = settings if settings is not None else Settings()
    song = dict(song or {})
    fmt = catalog.output_format(s.format)
    song_sr = int(song["sample_rate"]) if song.get("sample_rate") else None
    out_sr = fmt.sr or song_sr
    picked = set(cards_on if cards_on is not None
                 else [k for k, v in s.fixes.items() if v > 0])
    on_keys = [c.key for c in catalog.CARDS if c.key in picked]
    noted_keys = [c.key for c in catalog.CARDS if c.key in set(noted) and c.key not in picked]

    fixes = _fixes(s, notches, on_keys, noted_keys)
    eq = _eq(s, int(out_sr or 48000))
    stages = [
        _read(song),
        _trim(trim, song.get("duration_s")),
        _rate(fmt, song_sr),
        fixes,
        _tone(s, reference),
        eq,
        _master(s, fmt, changed=fixes["on"] or eq["on"], gain_db=gain_db),
        _export(s, fmt, out_sr, tags, save_folder),
        _report(),
    ]

    n_on = sum(1 for d in stages if d["on"])
    sound = [d["stage"] for d in stages
             if d["on"] and d["key"] in ("rate", "fixes", "tone", "eq", "master")]
    no_tool = [k for k in on_keys
               if catalog.card(k).tool not in _MASTERING_TOOLS
               and catalog.card(k).tool not in catalog.TOOLS_READY]
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
                f"{'is' if k == 1 else 'are'} noted: no tool is built for "
                f"{'it' if k == 1 else 'them'} yet.")
    elif sound:
        text = f"The sound changes in {_join(sound)}."
    else:
        text = "Nothing changes the sound."

    fmt_chip = f"{fmt.label} · {_hz(out_sr)}" if out_sr and not fmt.sr else fmt.label
    cards_chip = _count(len(on_keys), "card") + " on" + (
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
