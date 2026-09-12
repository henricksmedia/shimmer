"""Analyze measures and never alters; the notch filter removes fixed tones only.

A clean mix gets no artifact findings (the old detector recommended cleaning
finished masters; PITFALLS "A metric that cannot fail"). A fixed tone is
found and removed; a note that moves, or is held for a few seconds, is music
and is left alone.

Interface: shimmer.core.analyze.findings
    findings(source) -> list[Finding(.card, .value, .unit, .detail)]
Interface: shimmer.core.repair.notch
    plan(source) -> list[Notch(.hz, .depth_db)]
    apply(x, sr, notches) -> y

SHIMMER_REQUIRE_CORPUS=1 turns "reference master not on this machine" from a
skip into a failure, so a run that is meant to judge real music cannot pass
by skipping it.
"""
import os

import numpy as np
import pytest

from _contract import needs

finds = needs("shimmer.core.analyze.findings", "shimmer.core.render", "shimmer.core.catalog")
notches = needs("shimmer.core.repair.notch", "shimmer.core.render")

REFERENCE = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "reference",
                         "reference-hey.wav")
REQUIRE_CORPUS = os.environ.get("SHIMMER_REQUIRE_CORPUS") == "1"


def _artifact_cards():
    from shimmer.core import catalog
    return {c.key for c in catalog.CARDS if c.group == "artifacts"}


def _with_line(x, sr, hz=16000.0, dbfs=-35.0):
    t = np.arange(len(x)) / sr
    line = 10 ** (dbfs / 20) * np.sin(2 * np.pi * hz * t)
    return (x + np.stack([line, line], axis=1)).astype(np.float32)


def _with_held_note(x, sr, hz=1760.0, start=3.0, end=7.0, dbfs=-20.0):
    """A note held for four of the ten seconds, with three harmonics."""
    y = x.astype(np.float64).copy()
    s, e = int(start * sr), int(end * sr)
    t = np.arange(e - s) / sr
    ramp = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.05)
    note = sum((0.5 ** k) * np.sin(2 * np.pi * hz * (k + 1) * t) for k in range(3))
    note *= 10 ** (dbfs / 20) * ramp
    y[s:e] += note[:, None]
    return y.astype(np.float32)


def _level_db_at(x, sr, hz):
    m = x.mean(axis=1)
    h = np.abs(np.fft.rfft(m * np.hanning(len(m))))
    f = np.fft.rfftfreq(len(m), 1 / sr)
    i = np.argmin(np.abs(f - hz))
    return 20 * np.log10(np.max(h[i - 2:i + 3]) + 1e-12)


@finds
def test_a_clean_mix_has_no_artifact_findings(clean_mix):
    from shimmer.core.analyze.findings import findings
    from shimmer.core.render import Source
    x, sr = clean_mix
    assert [f for f in findings(Source.from_array(x, sr)) if f.card in _artifact_cards()] == []


@finds
def test_a_fixed_tone_is_found(clean_mix):
    from shimmer.core.analyze.findings import findings
    from shimmer.core.render import Source
    x, sr = clean_mix
    found = findings(Source.from_array(_with_line(x, sr), sr))
    assert any(f.card == "tones" and abs(f.value - 16000.0) < 50.0 for f in found)


@finds
def test_a_held_note_is_not_a_fixed_tone(clean_mix):
    from shimmer.core.analyze.findings import findings
    from shimmer.core.render import Source
    x, sr = clean_mix
    found = findings(Source.from_array(_with_held_note(x, sr), sr))
    assert [f for f in found if f.card == "tones"] == []


@notches
def test_the_notch_removes_a_fixed_tone(clean_mix):
    from shimmer.core.render import Source
    from shimmer.core.repair import notch
    x, sr = clean_mix
    y = _with_line(x, sr)
    out = notch.apply(y, sr, notch.plan(Source.from_array(y, sr)))
    assert _level_db_at(y, sr, 16000.0) - _level_db_at(out, sr, 16000.0) >= 20.0


@notches
def test_a_moving_note_is_not_notched():
    from shimmer.core.render import Source
    from shimmer.core.repair import notch
    sr = 48000
    t = np.arange(10 * sr) / sr
    glide = 0.1 * np.sin(2 * np.pi * (3000.0 * t + 150.0 * t ** 2))   # 3 kHz rising to 6 kHz
    x = np.stack([glide, glide], axis=1).astype(np.float32)
    assert notch.plan(Source.from_array(x, sr)) == []


@notches
def test_a_held_note_is_not_notched(clean_mix):
    from shimmer.core.render import Source
    from shimmer.core.repair import notch
    x, sr = clean_mix
    assert notch.plan(Source.from_array(_with_held_note(x, sr), sr)) == []


@finds
@pytest.mark.skipif(not os.path.exists(REFERENCE) and not REQUIRE_CORPUS,
                    reason="reference master not on this machine")
def test_a_finished_master_gets_no_artifact_findings():
    from shimmer.core.analyze.findings import findings
    from shimmer.core.render import Source
    assert os.path.exists(REFERENCE), "SHIMMER_REQUIRE_CORPUS is set but the reference is missing"
    found = findings(Source.load(REFERENCE))
    assert [f for f in found if f.card in _artifact_cards()] == []
