"""describe_chain: what each stage does for a set of settings, for the
Signal chain view. The view must say what a run will do, so where render()
decides something (the notches, the EQ, the ceilings), the test asks render's
own rule and checks the view agrees.
"""
import inspect
import json
import os
import re

import numpy as np
import pytest

from shimmer.core import catalog
from shimmer.core.audio import eq as user_eq
from shimmer.core.chain import CHECKS, TONE_MAX_BOOST_DB, TONE_MAX_CUT_DB, describe_chain
from shimmer.core.master import release, tone
from shimmer.core.render import Source, _tones_plan, known_gain
from shimmer.core.render import render as render_window
from shimmer.core.repair.notch import NotchPlan
from shimmer.core.settings import EqBand, Settings

SONG = {"name": "Alive Again (clip).wav", "sample_rate": 44100, "bits": 16,
        "channels": 2, "duration_s": 30.0}


def _notches(*pairs, sr=44100):
    return NotchPlan.from_dict({"enabled": True, "notches": [
        {"hz": hz, "depth_db": d, "bw_hz": 40.0} for hz, d in pairs]}, sr).notches


THREE = _notches((3510.0, 10.0), (5270.0, 8.0), (11900.0, 6.0))


def _stages(view):
    return {s["key"]: s for s in view["stages"]}


def test_nine_stages_in_signal_order():
    view = describe_chain(Settings())
    assert [(s["key"], s["stage"]) for s in view["stages"]] == list(catalog.STAGES)
    assert view["summary"]["total"] == 9
    json.dumps(view)          # the route sends it as it is


def test_typical_settings():
    """Mastering on (Commercial), Fixed tones with 3 notches, EQ off, WAV
    24-bit: the mockup's first state."""
    view = describe_chain(Settings(fixes={"tones": 1.0}), song=SONG, notches=THREE,
                          cards_on=["tones"])
    st = _stages(view)
    assert view["summary"]["on"] == 6
    assert view["summary"]["text"] == "The sound changes in Fixes, Tone and Master."
    assert view["summary"]["facts"] == ["Commercial · −9 LUFS", "Ceiling −1.0 dBTP",
                                        "WAV 24-bit · 44.1 kHz", "1 card on"]
    assert st["load"]["verdict"] == "On · Alive Again (clip).wav"
    assert st["load"]["badges"] == ["44.1 kHz", "16-bit", "stereo", "0:30"]
    assert (st["edit"]["on"], st["edit"]["off"]) == (False, "no cuts or fades set")
    assert st["rate"]["off"] == "WAV 24-bit keeps the song’s rate"
    assert st["fixes"]["verdict"] == "On · 3 notches, deepest −10 dB"
    assert st["fixes"]["badges"] == ["3 notches", "deepest −10 dB", "Amount 100%"]
    assert st["fixes"]["band"] == {"notches": [3510.0, 5270.0, 11900.0]}
    assert st["fixes"]["band_text"] == "Notches at 3.51 kHz, 5.27 kHz and 11.9 kHz."
    assert st["tone"]["verdict"] == "On · Tone match Medium, Tilt Neutral"
    assert st["tone"]["badges"] == ["Medium", "Neutral tilt", "+2 / −3 dB max"]
    assert st["eq"]["off"] == "EQ is off"
    assert st["master"]["badges"] == ["−9 LUFS", "−1.0 dBTP", "25 Hz low-cut", "one static gain"]
    assert [t for t, _ in st["master"]["steps"]] == [
        "Low-cut at 25 Hz", "Gain to −9 LUFS", "Peak shaper", "True-peak limiter"]
    assert st["export"]["verdict"] == "On · WAV 24-bit at 44.1 kHz"
    assert st["export"]["badges"] == ["44.1 kHz", "tags on", "silence trim off"]
    assert st["report"]["checks"] == list(CHECKS)


def test_mastering_off_shows_preserve_volume_in_masters_place():
    s = Settings(fixes={"tones": 1.0}, mastering=False)
    view = describe_chain(s, song=SONG, notches=THREE, cards_on=["tones"])
    st = _stages(view)
    # The release check runs with mastering on only.
    assert view["summary"]["on"] == 4
    assert (st["report"]["on"], st["report"]["off"]) == (False, "mastering is off")
    assert view["summary"]["text"] == "Mastering is off, so the song keeps its own level."
    assert view["summary"]["facts"][:2] == ["Mastering off", "Preserve volume on"]
    assert st["tone"]["off"] == "mastering is off"
    m = st["master"]
    assert (m["name"], m["on"], m["standin"], m["tag"]) == ("Preserve volume", True, True,
                                                            "Mastering off")
    assert "±12 dB" in " ".join(m["badges"])
    # Nothing before it changes the sound: render() adds no gain then.
    idle = _stages(describe_chain(Settings(fixes={"tones": 0.0}, mastering=False), song=SONG,
                                  notches=THREE))["master"]
    assert (idle["on"], idle["standin"]) == (False, True)
    # Preserve volume off too: a plain skipped stage.
    off = _stages(describe_chain(Settings(mastering=False, preserve_volume=False)))["master"]
    assert (off["on"], off["standin"], off["off"]) == (False, False, "mastering is off")


def test_the_fixes_stage_follows_renders_notch_plan():
    src = Source.from_array(np.zeros((4410, 2), np.float32), 44100)
    cases = [
        (Settings(fixes={"tones": 1.0}), THREE),
        (Settings(fixes={"tones": 0.5}), THREE),
        (Settings(fixes={"tones": 0.0}), THREE),
        (Settings(fixes={}, auto=True), THREE),
        (Settings(fixes={}, auto=False), THREE),
        (Settings(fixes={"tones": 1.0}), []),
    ]
    for s, notches in cases:
        plan = _tones_plan(src, 44100, s, notches)
        st = _stages(describe_chain(s, song=SONG, notches=notches))["fixes"]
        assert st["on"] == bool(plan), (s.fixes, s.auto, len(notches))
        if plan:
            deepest = max(n.depth_db for n in plan)
            assert f"deepest −{deepest:g} dB" in st["badges"]
    half = _stages(describe_chain(Settings(fixes={"tones": 0.5}), notches=THREE))["fixes"]
    assert half["badges"] == ["3 notches", "deepest −5 dB", "Amount 50%"]
    assert _stages(describe_chain(Settings(fixes={"tones": 0.0}), notches=THREE))["fixes"][
        "off"] == "no fix is on"
    assert _stages(describe_chain(Settings(fixes={"tones": 1.0}), notches=[]))["fixes"][
        "off"] == "no steady tones to cut"
    # No song yet: the scan has not run, so the stage says what it will do.
    early = _stages(describe_chain(Settings()))["fixes"]
    assert early["on"] and early["verdict"] == "On · cuts the steady tones Analyze finds"


def test_the_rate_stage_runs_only_when_the_format_needs_it():
    for key in ("wav16", "flac16"):
        s = Settings(format=key)
        at48 = _stages(describe_chain(s, song={**SONG, "sample_rate": 48000}))["rate"]
        assert at48["on"] and at48["badges"] == ["48 kHz → 44.1 kHz"]
        at44 = _stages(describe_chain(s, song=SONG))["rate"]
        assert (at44["on"], at44["off"]) == (False, "the song is already at 44.1 kHz")
    mp3 = _stages(describe_chain(Settings(format="mp3"), song=SONG))["rate"]
    assert mp3["off"] == "MP3 320 kbps keeps the song’s rate"


def test_every_format_shows_its_own_ceiling():
    for f in catalog.FORMATS:
        view = describe_chain(Settings(format=f.key))
        c = f"{f.ceiling_dbtp:.1f}".replace("-", "−")
        assert f"{c} dBTP" in _stages(view)["master"]["badges"], f.key
        assert f"Ceiling {c} dBTP" in view["summary"]["facts"]
        assert f"at or below {c} dBTP" in _stages(view)["master"]["steps"][-1][1]


def test_the_eq_stage_runs_when_render_would():
    bands = (EqBand("bell", 250.0, -2.0, 1.0), EqBand("highpass", 30.0, 0.0, 0.7))
    s = Settings(eq_enabled=True, eq_bands=bands)
    assert user_eq.designs(s.eq_bands, 44100)
    eq = _stages(describe_chain(s, song=SONG))["eq"]
    assert eq["verdict"] == "On · 2 bands"
    assert eq["badges"] == ["2 bands", "Bell 250 Hz −2 dB", "Low-cut 30 Hz"]
    assert "one way" in " ".join(eq["paras"])
    empty = Settings(eq_enabled=True, eq_bands=())
    assert not user_eq.designs(empty.eq_bands, 44100)
    assert _stages(describe_chain(empty))["eq"]["off"] == "no bands set"


def test_a_reference_track_changes_the_tone_stage():
    ref = {"name": "Particle.flac"}
    tone_st = _stages(describe_chain(Settings(match_amount=0.8), reference=ref))["tone"]
    assert tone_st["name"] == "Reference match"
    assert tone_st["verdict"] == "On · matching Particle.flac, Amount 80%"
    assert f"±{tone.MATCH_LIMIT_DB:g} dB max" in tone_st["badges"]
    off = _stages(describe_chain(Settings(mastering=False), reference=ref))["tone"]
    assert off["off"] == "mastering is off"


def test_card_rows_say_where_each_card_acts():
    view = describe_chain(Settings(fixes={"tones": 1.0}), notches=THREE,
                          cards_on=["tones", "air", "loudness"], noted=["phasiness", "clicks"])
    fx = _stages(view)["fixes"]
    assert [r["key"] for r in fx["fixes"]] == ["tones", "air", "loudness"]
    assert fx["fixes"][1]["tag"] == {"kind": "stage", "text": "In Tone", "stage": "tone"}
    assert fx["fixes"][2]["text"].endswith("at −9 LUFS.")
    assert [(r["key"], r["tag"]["text"], r["muted"]) for r in fx["noted"]] == [
        ("clicks", "Held back", False), ("phasiness", "No fix yet", True)]
    assert fx["noted"][0]["text"].startswith("The de-click is built but held back")
    assert fx["verdict"] == "1 fix runs · 2 go to mastering · 1 held back · 1 no fix yet"
    assert fx["nb_badges"] == ["1 held back", "1 no fix yet"]
    assert view["summary"]["facts"][-1] == "3 cards on · 2 noted"
    assert view["summary"]["text"] == ("3 cards are on, and 2 more are noted. Noted cards "
                                       "change nothing yet.")
    # Mastering off: the cards that live in mastering change nothing.
    off = _stages(describe_chain(Settings(mastering=False), cards_on=["air"]))["fixes"]
    assert {r["key"]: r for r in off["fixes"]}["air"]["tag"]["text"] == "Needs mastering"


def test_a_held_back_tool_is_said_to_run():
    # The de-click is built and runs when its card is set (render._FIX_TOOLS),
    # though the screen doesn't offer it yet (catalog.TOOLS_READY).
    view = describe_chain(Settings(fixes={"clicks": 0.5}))
    fx = _stages(view)["fixes"]
    rows = {r["key"]: r for r in fx["fixes"]}
    assert rows["clicks"]["tag"]["text"] == "Held back"
    assert fx["on"] and fx["name"] == "Notch filter, De-click"
    assert view["summary"]["text"] == "The sound changes in Fixes, Tone and Master."


def test_a_card_on_with_no_fix_is_said_plainly():
    view = describe_chain(Settings(fixes={"phasiness": 0.5}))
    rows = {r["key"]: r for r in _stages(view)["fixes"]["fixes"]}
    assert rows["phasiness"]["tag"]["text"] == "No fix yet"
    assert view["summary"]["text"] == "1 card is on, and 1 of them has no tool built yet."


def test_trim_and_export():
    st = _stages(describe_chain(Settings(), song={**SONG, "duration_s": 240.0},
                                trim=(1.2, 238.0)))
    assert st["edit"]["verdict"] == "On · starts at 0:01.2, ends at 3:58.0"
    assert st["edit"]["badges"] == ["in 0:01.2", "out 3:58.0", "keeps 3:57"]
    ex = _stages(describe_chain(Settings(format="wav16", trim_silence=True), tags=False,
                                save_folder=os.path.join("D:" + os.sep, "Music", "Masters")))
    ex = ex["export"]
    assert ex["verdict"] == "On · WAV 16-bit 44.1 kHz"
    assert ex["badges"] == ["44.1 kHz", "dithered", "tags off", "silence trim on",
                            "saved to Masters"]
    lossy = _stages(describe_chain(Settings(format="mp3")))["export"]
    assert any("decodes the file" in p for p in lossy["paras"])


def test_the_report_lists_every_release_check_row():
    labels = set(re.findall(r'_check\("[a-z_]+", "([^"]+)"', inspect.getsource(release)))
    assert labels == set(CHECKS)


def test_a_ready_tool_gets_its_own_row():
    """A card whose tool is in TOOLS_READY: the Fixes stage shows it
    running, with its depth at the Amount set, and says what is built."""
    from shimmer.core.repair import deesser
    view = describe_chain(Settings(fixes={"sibilance": 0.5}, auto=False),
                          cards_on=["sibilance"])
    fx = _stages(view)["fixes"]
    assert fx["on"] and fx["name"] == "De-esser"
    row = fx["fixes"][0]
    assert (row["key"], row["tag"]["text"]) == ("sibilance", "On")
    from shimmer.core.chain import _num
    assert f"By up to {_num(deesser.MAX_CUT_DB * 0.5)} dB at Amount 50%." in row["text"]
    assert fx["verdict"] == "1 fix runs"
    assert fx["badges"] == ["De-esser 50%"]
    assert ("Built so far: the notch filter, de-esser, dynamic EQ, spectral de-noise and "
            "voice de-noise." in fx["paras"][0])
    assert view["summary"]["text"] == "The sound changes in Fixes, Tone and Master."
    # With the notch too, both run and both are named.
    both = _stages(describe_chain(Settings(fixes={"tones": 1.0, "sibilance": 0.5}),
                                  notches=THREE, cards_on=["tones", "sibilance"]))["fixes"]
    assert both["name"] == "Notch filter, De-esser" and both["verdict"].startswith("2 fixes run")


def _music(seconds=6.0, sr=44100):
    rng = np.random.default_rng(1)
    t = np.arange(int(seconds * sr)) / sr
    x = 0.2 * np.sin(2 * np.pi * 220 * t) + 0.05 * rng.standard_normal(t.size)
    return np.stack([x, 0.9 * x], axis=1).astype(np.float32)


def _gain_badge(stage):
    b = stage["badges"][0]
    assert b.endswith(" dB gain"), stage["badges"]
    return float(b.split()[0].replace("−", "-"))


def test_master_shows_the_gain_once_a_render_has_worked_it_out():
    src = Source.from_array(_music(), 44100)
    s = Settings(fixes={"tones": 1.0})
    assert known_gain(src, s, notches=THREE) is None          # nothing rendered yet
    unknown = _stages(describe_chain(s, notches=THREE))["master"]
    assert "once the preview has played" in unknown["steps"][1][1]
    r = render_window(src, s, window=(0.0, 2.0), notches=THREE)
    g = known_gain(src, s, notches=THREE)
    assert g == pytest.approx(r.report["mastering"]["gain_db"])
    master = _stages(describe_chain(s, notches=THREE, gain_db=g))["master"]
    assert _gain_badge(master) == pytest.approx(round(g, 1))
    # A new loudness target needs no new measurement to show a gain: the
    # first-pass gain, before the second pass checks it after the limiter.
    assert known_gain(src, s.replace(loudness_target="streaming"), notches=THREE) == \
        pytest.approx(g - 5.0, abs=0.5)
    assert known_gain(src, s.replace(tilt="bright"), notches=THREE) is None
    # Mastering off: Preserve volume's gain, once rendered.
    off = s.replace(mastering=False)
    assert known_gain(src, off, notches=THREE) is None
    r = render_window(src, off, window=(0.0, 2.0), notches=THREE)
    g = known_gain(src, off, notches=THREE)
    assert g == pytest.approx(r.report["mastering"]["preserve_volume_gain_db"])
    pv = _stages(describe_chain(off, notches=THREE, gain_db=g))["master"]
    assert pv["verdict"].startswith("On · ") and "dB, back to the song’s own level" in pv["verdict"]


def test_tone_limits_are_the_engines():
    p = inspect.signature(tone.tone_curve).parameters
    assert p["max_boost_db"].default == TONE_MAX_BOOST_DB
    assert p["max_cut_db"].default == TONE_MAX_CUT_DB


def test_fades_show_with_the_cuts():
    st = _stages(describe_chain(Settings(), song=SONG, fades=(1.0, 4.0)))
    assert st["edit"]["on"] and st["edit"]["verdict"] == "On · 1 s fade in, 4 s fade out"
    assert st["edit"]["badges"] == ["fade in 1 s", "fade out 4 s"]
    assert any("after mastering" in p for p in st["edit"]["paras"])
    assert any("20 dB down" in p for p in st["edit"]["paras"])


def test_the_release_check_runs_with_mastering_only():
    assert _stages(describe_chain(Settings()))["report"]["on"]
    off = _stages(describe_chain(Settings(mastering=False)))["report"]
    assert (off["on"], off["off"]) == (False, "mastering is off")


def test_a_first_pass_gain_is_marked_as_about():
    m = _stages(describe_chain(Settings(), gain_db=6.24, gain_checked=False))["master"]
    assert m["badges"][0] == "about +6.2 dB gain"
    assert "about +6.2 dB gain" in m["verdict"]
    m = _stages(describe_chain(Settings(), gain_db=6.24))["master"]
    assert m["badges"][0] == "+6.2 dB gain"


def test_mp3_is_written_at_48_khz_at_most():
    view = describe_chain(Settings(format="mp3"), song={**SONG, "sample_rate": 96000})
    st = _stages(view)
    assert st["export"]["verdict"].endswith("at 48 kHz")
    assert st["rate"]["on"] and st["rate"]["badges"] == ["96 kHz → 48 kHz"]
    at48 = _stages(describe_chain(Settings(format="mp3"), song={**SONG, "sample_rate": 48000}))
    assert not at48["rate"]["on"]
    st = _stages(describe_chain(Settings(format="m4a"), song={**SONG, "sample_rate": 96000}))
    assert st["export"]["verdict"].endswith("at 96 kHz")


def test_eq_counts_only_bands_that_change_the_sound():
    bands = [EqBand(type="bell", freq_hz=1000.0, gain_db=0.0, q=1.0, enabled=True),
             EqBand(type="bell", freq_hz=3000.0, gain_db=-2.0, q=1.0, enabled=True)]
    eq = _stages(describe_chain(Settings(eq_enabled=True, eq_bands=bands)))["eq"]
    assert eq["verdict"] == "On · 1 band"


def test_running_fixes_draw_their_range():
    fx = _stages(describe_chain(Settings(fixes={"tones": 0.0, "sibilance": 0.5})))["fixes"]
    assert fx["band"]["ranges"] == [[4500.0, 10000.0]]
    assert fx["band_text"] == "Sibilance 4.5 kHz–10 kHz."


def test_two_cards_on_one_tool_are_named_by_card():
    fx = _stages(describe_chain(Settings(fixes={"tones": 0.0, "harshness": 0.5,
                                                "mud": 0.5})))["fixes"]
    assert fx["name"] == "Dynamic EQ (Harshness and Low-mid build-up)"
    assert fx["badges"] == ["Harshness 50%", "Low-mid build-up 50%"]
