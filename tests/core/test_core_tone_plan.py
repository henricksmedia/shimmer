"""Suggested EQ in the engine: core.tone_plan(source, settings) judges the
song the way render() will run it, after the fixes and the mastering tone
curve, so nothing is corrected twice.

Interface: shimmer.core
    tone_plan(source, settings=None, family="neutral", notches=None,
              reference=None) -> the plan (moves, regions, shape, verify, eq)
    family_list(), normalize_family(key), moves_to_eq_payload(moves, amount)
"""
import numpy as np

import conftest
from _contract import needs

pytestmark = needs("shimmer.core.analyze.tone_plan")

SR = 48000


def _song(tone_hz=None, seconds=24.0):
    x = conftest._clean(seconds=seconds).astype(np.float64)
    if tone_hz:
        t = np.arange(x.shape[0]) / SR
        x += (10 ** (-42 / 20) * np.sin(2 * np.pi * tone_hz * t))[:, None]
    return x.astype(np.float32)


def test_with_mastering_on_the_plan_is_judged_after_the_tone_curve():
    from shimmer import core
    from shimmer.core.analyze.tones import estimate_cutoff_hz
    from shimmer.core.master import tone
    src = core.Source.from_array(_song(), SR)
    on = core.tone_plan(src, core.Settings(auto=False))
    off = core.tone_plan(src, core.Settings(auto=False, mastering=False))
    assert on["mastering_on"] and on["analysis"]["tone_curve_applied"]
    assert not off["mastering_on"] and not off["analysis"]["tone_curve_applied"]
    curve = tone.compute_tone_curve(src.audio, SR, strength=tone.intensity_to_strength("med"),
                                    cutoff_hz=estimate_cutoff_hz(src.audio, SR).get("cutoff_hz"))
    judged = np.array(on["shape"]["judged_db"]) - np.array(on["shape"]["measured_db"])
    assert np.allclose(judged, curve, atol=0.02)


def test_a_fixed_tone_is_judged_after_its_notch():
    from shimmer import core
    src = core.Source.from_array(_song(tone_hz=3510.0), SR)
    found = core.tone_plan(src, core.Settings(mastering=False))
    assert found["analysis"]["cleaning_applied"] is True
    assert not [m for m in found["moves"]
                if m["kind"] == "resonance" and abs(m["freq_hz"] - 3510.0) / 3510.0 < 0.03]
    none = core.tone_plan(src, core.Settings(mastering=False, auto=False))
    assert none["analysis"]["cleaning_applied"] is False


def test_the_plan_is_the_same_at_every_level():
    # The plan reads shape, not level: a quieter copy gets the same moves.
    from shimmer import core
    x = _song()
    a = core.tone_plan(core.Source.from_array(x, SR), core.Settings(auto=False))
    b = core.tone_plan(core.Source.from_array(x * 0.25, SR), core.Settings(auto=False))
    assert [(m["type"], m["freq_hz"], m["gain_db"]) for m in a["moves"]] == \
           [(m["type"], m["freq_hz"], m["gain_db"]) for m in b["moves"]]


def test_families_and_the_eq_payload():
    from shimmer import core
    fams = core.family_list()
    assert fams[0]["key"] == "neutral" and len(fams) == 9
    assert core.normalize_family(" EDM ") == "edm"
    assert core.normalize_family("nonsense") == "neutral"
    moves = [{"type": "bell", "freq_hz": 300.0, "gain_db": -2.0, "q": 1.4, "enabled": True}]
    assert core.moves_to_eq_payload(moves, amount=0.5)["bands"][0]["gain_db"] == -1.0
    assert core.moves_to_eq_payload([])["enabled"] is False


def test_the_old_name_points_to_the_engine():
    from shimmer import autoeq
    from shimmer.core.analyze import tone_plan
    assert autoeq.plan_tone is tone_plan.plan_tone
