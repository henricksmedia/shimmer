"""
chain.py — The Signal Chain, generated from the code that runs it.

The Signal Chain view used to be a hand-written list in chain.js. It was
right about the order and wrong about the numbers (crossover, Mid scale
and stage bands change per preset) and it was missing both ends (Trim
at the start, Match Loudness and Export at the end). This module builds
the chain description from the same Params / MasterParams / options a
run would use, in the order pipeline.py, engine.py and server.py apply
them, so the view cannot drift from the sound path.

Nothing here touches audio. `build_chain()` is pure and cheap; the
server exposes it as POST /api/chain and the Master tab hands it the
exact state a Clean & Master click would send.

Wording rule for every string below: plain English at an 8th-grade
level, and the terms a plugin manual would use (notch, high-pass,
shelf, de-esser, de-click, noise reduction, mid/side, crossover,
transient, limiter, true peak, LUFS).

Order (see docs/README.md "Architecture" and docs/PLAN.md Section 2):

    Trim -> De-click -> Static Notches -> Tone curve -> Crossover -> M/S
      -> [pre-scan mask] -> STFT stages in STAGE_REGISTRY order
         (x passes; flatness gate + transient hold ride alongside)
      -> Side width comp -> Recombine + mix -> Post EQ + fades
      -> Parametric EQ -> Match loudness (mastering off)
      -> Mastering: high-pass -> loudness gain -> soft clip -> limiter
      -> Export
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .edges import TRIM_FADE_MS
from .engine import STAGE_REGISTRY
from .mastering import get_export_ceiling_dbtp
from .params import MasterParams, Params
from .repair import DECLICK_K_MAX, DECLICK_K_MIN, MAX_NOTCH_DEPTH_DB

_LOSSY = {"mp3", "ogg", "m4a", "aac", "mp4"}


def _hz(v: float) -> str:
    v = float(v)
    if v >= 1000.0:
        s = f"{v / 1000.0:.2f}".rstrip("0").rstrip(".")
        return f"{s} kHz"
    return f"{v:.0f} Hz"


def _band(lo: float, hi: float) -> str:
    return f"{_hz(lo)}–{_hz(hi)}"


def _pct(v: float) -> str:
    return f"{float(v) * 100.0:.0f}%"


def _mod(mid: str, cat: str, name: str, gloss: str, detail: str,
         badges: Optional[List[str]] = None, active: bool = True,
         adv: Optional[List[str]] = None, off_reason: str = "") -> Dict[str, Any]:
    return {
        "id": mid, "cat": cat, "name": name, "gloss": gloss,
        "badges": list(badges or []), "detail": detail,
        "active": bool(active), "adv": list(adv or []),
        "off_reason": off_reason,
    }


# ---------------------------------------------------------------------------
# STFT stage descriptors, keyed by the registry class name
# ---------------------------------------------------------------------------

def _stage_descriptor(cls_name: str, p: Params) -> Dict[str, Any]:
    if cls_name == "ExpanderStage":
        return dict(
            mid="expander", name="Downward Expander",
            gloss=f"turns {_band(p.exp_start_hz, p.exp_end_hz)} down when it gets quiet",
            badges=[f"{p.exp_threshold_db:.0f} dB threshold", f"{p.exp_ratio:g}:1 ratio"],
            detail=("When the band drops below the threshold, the expander "
                    "turns it down further. That catches shimmer tails "
                    "between notes. Only Echo Sheen uses it."),
        )
    if cls_name == "DenoiseStage":
        return dict(
            mid="denoise", name="Noise Reduction",
            gloss="learns the noise floor and subtracts it",
            badges=[_band(p.dn_start_hz, p.dn_end_hz), f"{p.dn_floor_db:.0f} dB floor",
                    _pct(p.denoise)],
            detail=("Spectral noise reduction. It learns the noise floor from "
                    "the quietest moments and subtracts it. A floor keeps it "
                    "from digging holes. The Denoise slider sets how much."),
            adv=["denoise"],
        )
    if cls_name == "DeResonatorStage":
        return dict(
            mid="deres", name="De-resonator (dynamic notch)",
            gloss="notches ringing peaks while they ring",
            badges=[_band(p.deq_start_hz, p.deq_end_hz), f"{p.deq_max_att_db:.0f} dB max",
                    _pct(p.deres)],
            detail=("Finds narrow peaks that ring for a while and notches them "
                    "only while they ring. The De-resonator slider sets how "
                    "much."),
            adv=["deres"],
        )
    if cls_name == "ShimmerStage":
        return dict(
            mid="shimmer", name="Shimmer Suppressor",
            gloss="the main narrow-band detector",
            badges=[_band(p.start_hz, p.end_hz), f"threshold {p.thr_db:g} dB", f"slope {p.slope:g}"],
            detail=("Looks for narrow peaks that poke above the nearby "
                    "spectrum inside the band and turns them down. The Band, "
                    "Threshold and Slope controls set it."),
            adv=["start_hz", "end_hz", "thr_db", "slope"],
        )
    if cls_name == "DeHarshStage":
        return dict(
            mid="deharsh", name="De-harsh (dynamic EQ)",
            gloss="turns the band down when it gets too hot",
            badges=[_band(p.dh_start_hz, p.dh_end_hz),
                    f"ref {_band(p.dh_ref_start_hz, p.dh_ref_end_hz)}",
                    f"{p.dh_max_att_db:.0f} dB max", _pct(p.deharsh),
                    f"{_pct(p.dh_per_bin)} per-bin"],
            detail=("A dynamic EQ that compares the band with a reference "
                    "band. When the band gets too loud against the reference, "
                    "it is turned down. The cut is weighted per bin: the peaks "
                    "that stand above the band's own spectrum take more of it, "
                    "so the whole band is not dulled to catch a few glazed "
                    "overtones. Vocal Glaze uses the low range of the voice as "
                    "the reference."),
            adv=["deharsh"],
        )
    if cls_name == "FlickerTamerStage":
        return dict(
            mid="flicker", name="Flicker Tamer",
            gloss="compresses fast flicker in the hash band",
            badges=[_band(p.ft_start_hz, p.ft_end_hz), f"{p.ft_n_bands} bands",
                    f"{p.ft_max_att_db:.0f} dB max", _pct(p.flicker_tame)],
            detail=("Splits the band into sub-bands and compresses the fast "
                    "flicker that makes AI hash sound like frying. Set per "
                    "preset."),
        )
    if cls_name == "DeCheckerStage":
        return dict(
            mid="decheck", name="Comb Suppressor",
            gloss="evenly spaced peaks",
            badges=[_band(p.cb_start_hz, p.cb_end_hz),
                    f"{p.cb_min_spacing_hz:.0f}–{p.cb_max_spacing_hz:.0f} Hz spacing",
                    _pct(p.decheck)],
            detail=("Finds evenly spaced peaks (the comb pattern some "
                    "generators leave) and turns the comb down. The "
                    "De-checker slider sets how much."),
            adv=["decheck"],
        )
    if cls_name == "NarrowToneStage":
        return dict(
            mid="tonekill", name="Tone Notcher (tracking)",
            gloss="tracks steady whistles",
            badges=[_band(p.tk_start_hz, p.tk_end_hz), f"{p.tk_max_att_db:.0f} dB max",
                    _pct(p.tone_kill)],
            detail=("Tracks whistles that hold one pitch for seconds and "
                    "notches them. Fixed tones are cut earlier by Static "
                    "Notches; this stage catches the ones that drift. Set per "
                    "preset."),
        )
    if cls_name == "NoiseResynthStage":
        return dict(
            mid="resynth", name="Noise Resynthesis",
            gloss="replaces glassy texture with smooth noise",
            badges=[f"{_pct(p.noise_resynth)} depth", _band(p.start_hz, p.end_hz)],
            detail=("Blends in a copy of the band with random phase, so what "
                    "is left sounds like smooth noise instead of glassy "
                    "texture."),
        )
    # Unknown stage: still show it so the view never silently omits code.
    return dict(mid=cls_name.lower(), name=cls_name, gloss="", badges=[], detail="")


# ---------------------------------------------------------------------------
# Chain builder
# ---------------------------------------------------------------------------

def build_chain(p: Params,
                master: Optional[MasterParams] = None,
                *,
                eq_bands: int = 0,
                preserve_volume: bool = True,
                trim_silence: bool = False,
                output_format: str = "wav",
                trim_armed: bool = False,
                repair: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Describe the processing chain for these exact settings.

    Returns {"modules": [...], "gates": {...}, "summary": {...}}. Every
    module carries `active` (whether it does anything for this preset /
    options) and `off_reason` when it does not.
    """
    mastering_on = bool(master is not None and master.enabled)
    fmt = str(output_format or "wav").lower().lstrip(".")
    lossy = fmt in _LOSSY
    ceiling = (float(master.ceiling_dbtp) if master is not None
               else get_export_ceiling_dbtp(fmt))
    modules: List[Dict[str, Any]] = []

    # ── Edit ────────────────────────────────────────────────────────────
    modules.append(_mod(
        "trim", "Edit", "Trim (top & tail)",
        "cuts the glitch at the start or end",
        ("Every upload is checked for the short glitch generators leave "
         "at the very start of a render. Nothing is cut until you arm a "
         "cut in the Trim card. Then the file is trimmed here, first, with "
         "short fades, so every later stage sees the real start of the "
         "song."),
        badges=[f"{TRIM_FADE_MS:g} ms fades", "armed" if trim_armed else "not armed"],
        active=trim_armed,
        off_reason="no cut armed in the Trim card",
    ))

    # ── Repair (fixed, before anything that listens and reacts) ─────────
    dc_amount = float(min(1.0, max(0.0, p.declick)))
    dc_on = dc_amount > 1e-6
    k_sigma = DECLICK_K_MAX - (DECLICK_K_MAX - DECLICK_K_MIN) * dc_amount
    modules.append(_mod(
        "declick", "Repair", "De-click",
        f"clicks, pops and crackle above {_hz(p.dc_min_hz)}",
        ("Finds clicks, pops and crackle in the high end and patches them "
         "from the sound on either side. Only short, isolated blips "
         "count; a drum hit or a hard consonant is left alone. It runs "
         "first because a click would fool every stage after it. Nothing "
         f"below {_hz(p.dc_min_hz)} is touched. Busy hi-hats can trip it, "
         "so set it by ear."),
        badges=[_pct(dc_amount), f"> {_hz(p.dc_min_hz)}", f"≤ {p.dc_max_ms:g} ms",
                f"{k_sigma:.1f}σ threshold"],
        active=dc_on, adv=["declick"],
        off_reason="this preset leaves De-click at zero",
    ))
    rep = repair or {}
    rep_enabled = rep.get("enabled", True) is not False
    rep_notches = rep.get("notches")
    if isinstance(rep_notches, list):
        n_lines = len(rep_notches)
        deepest = max([float(n.get("depth_db", 0.0) or 0.0) for n in rep_notches] or [0.0])
        rep_badges = [f"{n_lines} tone{'s' if n_lines != 1 else ''}"]
        if n_lines:
            top = max(rep_notches, key=lambda n: float(n.get("depth_db", 0.0) or 0.0))
            rep_badges.append(f"{_hz(float(top.get('hz', 0.0)))} −{deepest:.0f} dB")
        rep_active = rep_enabled and n_lines > 0
        rep_off = "no fixed tones found in this file" if rep_enabled else "turned off"
    else:
        rep_badges = ["scanned per file", f"≤ {MAX_NOTCH_DEPTH_DB:.0f} dB"]
        rep_active = rep_enabled
        rep_off = "turned off"
    modules.append(_mod(
        "repair", "Repair", "Static Notches",
        "fixed tones from the generator",
        ("AI generators leave thin fixed-pitch tones (often 16–20 kHz) "
         "that never move for the whole song. Shimmer finds them once "
         "across the file and cuts each one with a narrow linear-phase "
         "notch on both channels, at full depth. Analyze lists them; "
         "untick any you want to keep."),
        badges=rep_badges, active=rep_active, off_reason=rep_off,
    ))

    # ── Pre ─────────────────────────────────────────────────────────────
    tone_badges = ["+2.0 / −3.0 dB max", "before cleaning"]
    if mastering_on:
        tone_badges += [f"match {master.intensity}", f"tilt {master.tilt}"]
    if float(p.cutoff_hz) > 0:
        tone_badges.append(f"no boost above {_hz(p.cutoff_hz)}")
    modules.append(_mod(
        "tone", "Pre", "Tone Curve",
        "gentle EQ match, applied before cleaning",
        ("With mastering on, a gentle EQ curve matched to a neutral "
         "reference is applied before cleaning. Boosts are limited to "
         "+2 dB (+0.5 dB from 5 to 12 kHz), so hiss and fizz are never "
         "boosted. If the render's top end stops early, nothing above that "
         "point is boosted."),
        badges=tone_badges, active=mastering_on,
        off_reason="mastering is off",
    ))

    # ── Split ───────────────────────────────────────────────────────────
    modules.append(_mod(
        "xover", "Split", "Crossover",
        f"below {_hz(p.crossover_hz)} is left alone",
        (f"A linear-phase crossover splits the mix at {_hz(p.crossover_hz)}. "
         "Everything below it skips the cleaning engine and comes back "
         "untouched. Most presets split at 4.5 kHz. The presence presets "
         "split lower, and Vocal Glaze splits at 300 Hz so it can use the "
         "low range of the voice as its reference."),
        badges=[f"{p.crossover_hz:.0f} Hz", f"{p.crossover_taps}-tap FIR"],
    ))
    modules.append(_mod(
        "ms", "Split", "Mid/Side Split",
        f"center cleaned at {p.ms_mid_scale:g}×, sides at {p.ms_side_scale:g}×",
        (f"The high band is split into mid (center) and side. The center "
         f"holds the vocal and the snare, so it is cleaned at "
         f"{_pct(p.ms_mid_scale)}. The sides get {_pct(p.ms_side_scale)}. "
         "Most AI shimmer is in the sides. Deep Scrub and the Vocal Glaze "
         "presets clean the center harder."),
        badges=[f"Mid {p.ms_mid_scale:g}×", f"Side {p.ms_side_scale:g}×"],
    ))

    # ── Fine pass (1024/256), before the coarse engine ──────────────────
    from .finepass import fine_pass_active
    fine_on = fine_pass_active(p)
    fine_cat = f"Fine {int(p.fine_n_fft)}/{int(p.fine_hop)}"
    ft_on = fine_on and float(p.flicker_tame) > 1e-6
    modules.append(_mod(
        "fine-flicker", fine_cat, "Flicker Tamer",
        "compresses fast flicker in the hash band",
        ("Splits the hash band into sub-bands and turns down the fast "
         "flicker that makes AI hash sound like frying. It runs on a "
         "short 23 ms window so it can see flicker at 10–50 Hz, and it "
         "measures each burst against the band's floor, not its average, "
         "so the bursts can really be pushed down. It only acts where a "
         "band is flickering; steady cymbal wash is left alone, and a "
         "transient hold protects drum hits."),
        badges=[_band(p.ft_start_hz, p.ft_end_hz), f"{p.ft_n_bands} bands",
                f"{p.ft_max_att_db:.0f} dB max", _pct(p.flicker_tame)],
        active=ft_on,
        off_reason=("fine pass is off" if not p.fine_pass
                    else "this preset leaves the Flicker Tamer at zero"),
    ))
    de_on = fine_on and float(p.deess) > 1e-6
    modules.append(_mod(
        "fine-deess", fine_cat, "De-esser (spectral)",
        f"tames sibilant bursts in {_band(p.de_start_hz, p.de_end_hz)}",
        ("When the band jumps far above its reference (1–4 kHz), the "
         "burst is turned down like a de-esser, but per bin: the peaks "
         "that stand above the band's own spectrum take most of the cut, "
         "the rest takes little. It is not held back on transients, "
         "because a hard 's' is the transient it is there for."),
        badges=[_band(p.de_start_hz, p.de_end_hz),
                f"ref {_band(p.de_ref_start_hz, p.de_ref_end_hz)}",
                f"{p.de_max_att_db:.0f} dB max", _pct(p.deess)],
        active=de_on, adv=["deess"],
        off_reason=("fine pass is off" if not p.fine_pass
                    else "this preset leaves the De-esser at zero"),
    ))

    # ── STFT engine ─────────────────────────────────────────────────────
    n_iter = int(max(1, min(3, int(p.iterations))))
    modules.append(_mod(
        "premask", "STFT", "Pre-scan Mask",
        "a full-song scan before the passes",
        ("A quick scan of the whole song finds the bins with long-term "
         "excess and flicker and turns them down a little on every frame "
         "before the stages run. Only Deep Scrub uses it."),
        badges=[_band(p.pa_start_hz, p.pa_end_hz), f"{p.pa_max_att_db:.0f} dB max"],
        active=bool(p.pre_analyze), off_reason="this preset does not pre-scan",
    ))
    stages = [cls() for cls in STAGE_REGISTRY]
    n = len(stages)
    for i, st in enumerate(stages, start=1):
        d = _stage_descriptor(type(st).__name__, p)
        active = bool(st.enabled(p))
        off_reason = "" if active else "this preset leaves it at zero"
        if type(st).__name__ == "FlickerTamerStage" and ft_on:
            # Moved to the fine pass; the coarse copy is skipped so the
            # same flicker is not compressed twice.
            active = False
            off_reason = "runs in the fine pass instead"
        modules.append(_mod(
            d["mid"], f"STFT {i}/{n}", d["name"], d["gloss"], d["detail"],
            badges=d["badges"], active=active, adv=d.get("adv"),
            off_reason=off_reason,
        ))

    # ── Recombine ───────────────────────────────────────────────────────
    modules.append(_mod(
        "swc", "Recombine", "Side Width Comp",
        "brings the stereo width back",
        ("Cleaning the sides narrows the stereo image. This measures the "
         "loss and adds a small make-up gain so the mix keeps its width."),
        badges=[f"+{p.swc_max_makeup_db:g} dB max", f"{p.swc_threshold_db:g} dB threshold"],
    ))
    modules.append(_mod(
        "mix", "Recombine", "Recombine + Mix",
        "join the bands, blend with the original",
        ("Turns mid/side back into left/right, joins the untouched low "
         "band, and blends with the original by the Mix control."),
        badges=[f"mix {_pct(p.mix)}"], adv=["mix"],
    ))

    # ── Post ────────────────────────────────────────────────────────────
    post_badges: List[str] = []
    if p.high_shelf_hz > 0 and abs(p.high_shelf_db) > 1e-6:
        post_badges.append(f"shelf {p.high_shelf_db:+.1f} dB @ {_hz(p.high_shelf_hz)}")
    if p.presence_hz > 0 and abs(p.presence_db) > 1e-6:
        post_badges.append(f"presence {p.presence_db:+.1f} dB @ {_hz(p.presence_hz)}")
    if p.lowmid_hz > 0 and abs(p.lowmid_db) > 1e-6:
        post_badges.append(f"bell {p.lowmid_db:+.1f} dB @ {_hz(p.lowmid_hz)}")
    if p.subsonic_hz > 0:
        post_badges.append(f"high-pass {p.subsonic_hz:g} Hz")
    if float(p.cutoff_hz) > 0 and (p.high_shelf_db > 0.1 or p.presence_db > 0.1):
        post_badges.append(f"boost capped at {_hz(p.cutoff_hz)}")
    post_badges.append(f"{p.fade_ms:g} ms fades")
    modules.append(_mod(
        "post", "Post", "Post EQ + Fades",
        "shelves, bell, high-pass",
        ("Linear-phase EQ applied once at the end of cleaning: the preset's "
         "air shelf, presence shelf and low-mid bell, a high-pass for "
         "rumble, and short fades at the edges. If the render's top end "
         "stops early, a shelf boost is capped at that point."),
        badges=post_badges, adv=["high_shelf_db"],
    ))
    modules.append(_mod(
        "eq", "Post", "Parametric EQ",
        "your EQ, after cleaning and before mastering",
        ("Your Parametric EQ card is applied here, linear-phase, after "
         "cleaning and before mastering. Your EQ moves never fight the "
         "cleaner, and the limiter catches any boost."),
        badges=[f"{eq_bands} band{'s' if eq_bands != 1 else ''}" if eq_bands else "no bands"],
        active=eq_bands > 0, off_reason="no EQ bands set",
    ))

    # ── Level (mastering off) ───────────────────────────────────────────
    preserve_active = (not mastering_on) and bool(preserve_volume)
    modules.append(_mod(
        "preserve", "Level", "Match Loudness",
        "same loudness as the input (mastering off)",
        ("With mastering off, the cleaned file is brought back to the "
         "input's loudness (RMS) and kept under full scale. With mastering "
         "on, the master sets the level instead."),
        badges=["RMS match", "0.999 peak"],
        active=preserve_active,
        off_reason=("mastering sets the level" if mastering_on
                    else "Preserve volume is off"),
    ))

    # ── Master ──────────────────────────────────────────────────────────
    off_m = "mastering is off"
    hp = master.hp_hz if master is not None else 25.0
    modules.append(_mod(
        "m-hp", "Master", "High-pass / DC", "removes rumble and DC offset",
        "A gentle high-pass removes DC offset and rumble before loudness "
        "is measured.",
        badges=[f"{hp:g} Hz"], active=mastering_on, off_reason=off_m,
    ))
    target = master.target_lufs if master is not None else -14.0
    modules.append(_mod(
        "m-gain", "Master", "Loudness Gain", "one fixed gain to the LUFS target",
        "One fixed gain moves the song to your loudness target. There is "
        "no multiband compression, so the dynamics you generated stay as "
        "they are.",
        badges=[f"{target:g} LUFS"], active=mastering_on, off_reason=off_m,
    ))
    modules.append(_mod(
        "m-clip", "Master", "Soft Clip", "rounds the top ~2 dB",
        "A soft clipper rounds off only the top couple of dB of the peaks "
        "so the limiter has less to do.",
        badges=["top ~2 dB"], active=mastering_on, off_reason=off_m,
    ))
    la = master.lookahead_ms if master is not None else 2.0
    modules.append(_mod(
        "m-limit", "Master", "True-Peak Limiter", "keeps peaks under the ceiling",
        (f"A look-ahead limiter with 4× oversampling keeps true peaks under "
         f"the ceiling: {ceiling:.1f} dBTP for this export ("
         f"{'lossy, so the encoder cannot clip' if lossy else 'lossless'})."),
        badges=[f"{ceiling:.1f} dBTP", "4× oversampling", f"{la:g} ms look-ahead"],
        active=mastering_on, off_reason=off_m,
    ))

    # ── Export ──────────────────────────────────────────────────────────
    enc = {"wav": "24-bit PCM", "flac": "24-bit FLAC", "aiff": "24-bit PCM"}.get(
        fmt, f"ffmpeg {fmt.upper()}")
    exp_badges = [fmt.upper(), enc]
    if trim_silence:
        exp_badges.append("silence trim < −60 dBFS")
    modules.append(_mod(
        "export", "Export", "Encode + Export",
        "format, bit depth, silence trim",
        ("The finished file is written in your chosen format. Lossless "
         "exports are 24-bit; lossy formats go through ffmpeg. If Trim "
         "silence is on, a second copy with the leading and trailing "
         "silence removed is written next to it; the playback files are "
         "not changed."),
        badges=exp_badges,
    ))

    gates = {
        "flatness": [float(p.flat_start), float(p.flat_end)],
        "hold_ms": float(p.th_hold_ms),
        "release_ms": float(p.th_release_ms),
        "surgical_reduction": float(p.th_surgical_reduction),
        "low_band_bypass_hz": float(p.crossover_hz),
    }
    summary = {
        "n_fft": int(p.n_fft), "hop": int(p.hop),
        "fine_pass": bool(fine_on),
        "fine_n_fft": int(p.fine_n_fft), "fine_hop": int(p.fine_hop),
        "iterations": n_iter, "pre_analyze": bool(p.pre_analyze),
        "crossover_hz": float(p.crossover_hz),
        "ms_mid_scale": float(p.ms_mid_scale),
        "mastering": mastering_on, "output_format": fmt,
        "ceiling_dbtp": float(ceiling),
        "active_modules": sum(1 for m in modules if m["active"]),
    }
    return {"modules": modules, "gates": gates, "summary": summary}
