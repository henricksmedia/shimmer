"""Analyze measures and never alters; the notch filter removes fixed tones only.

A clean mix gets no findings (the old detector recommended cleaning finished
masters; PITFALLS "A metric that cannot fail"). A fixed tone is found and
removed; a note that moves is music and is left alone.

Interface: shimmer.core.analyze.findings
    findings(source) -> list[Finding(.card, .value, .detail)]
Interface: shimmer.core.repair.notch
    plan(source) -> list[Notch(.hz, .depth_db)]
    apply(x, sr, notches) -> y
"""
import importlib.util
import os

import numpy as np
import pytest

pytestmark = pytest.mark.xfail(importlib.util.find_spec("shimmer.core") is None,
                               reason="shimmer.core is not built yet (rebuild Step 4)",
                               strict=True)

REFERENCE = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "reference",
                         "reference-hey.wav")


def _with_line(x, sr, hz=16000.0, dbfs=-35.0):
    t = np.arange(len(x)) / sr
    line = 10 ** (dbfs / 20) * np.sin(2 * np.pi * hz * t)
    return (x + np.stack([line, line], axis=1)).astype(np.float32)


def _level_db_at(x, sr, hz):
    m = x.mean(axis=1)
    h = np.abs(np.fft.rfft(m * np.hanning(len(m))))
    f = np.fft.rfftfreq(len(m), 1 / sr)
    i = np.argmin(np.abs(f - hz))
    return 20 * np.log10(np.max(h[i - 2:i + 3]) + 1e-12)


def test_a_clean_mix_has_no_findings(clean_mix):
    from shimmer.core.analyze.findings import findings
    from shimmer.core.render import Source
    x, sr = clean_mix
    assert findings(Source.from_array(x, sr)) == []


def test_a_fixed_tone_is_found(clean_mix):
    from shimmer.core.analyze.findings import findings
    from shimmer.core.render import Source
    x, sr = clean_mix
    found = findings(Source.from_array(_with_line(x, sr), sr))
    assert any(f.card == "tones" and abs(f.value - 16000.0) < 50.0 for f in found)


def test_the_notch_removes_a_fixed_tone(clean_mix):
    from shimmer.core.render import Source
    from shimmer.core.repair import notch
    x, sr = clean_mix
    y = _with_line(x, sr)
    out = notch.apply(y, sr, notch.plan(Source.from_array(y, sr)))
    assert _level_db_at(y, sr, 16000.0) - _level_db_at(out, sr, 16000.0) >= 20.0


def test_a_moving_note_is_not_notched():
    from shimmer.core.render import Source
    from shimmer.core.repair import notch
    sr = 48000
    t = np.arange(10 * sr) / sr
    glide = 0.1 * np.sin(2 * np.pi * (3000.0 * t + 150.0 * t ** 2))   # 3 kHz rising to 6 kHz
    x = np.stack([glide, glide], axis=1).astype(np.float32)
    assert notch.plan(Source.from_array(x, sr)) == []


@pytest.mark.skipif(not os.path.exists(REFERENCE), reason="reference master not on this machine")
def test_a_finished_master_gets_no_artifact_findings():
    from shimmer.core import catalog
    from shimmer.core.analyze.findings import findings
    from shimmer.core.render import Source
    artifact_cards = {c.key for c in catalog.CARDS if c.group == "artifacts"}
    found = findings(Source.load(REFERENCE))
    assert [f for f in found if f.card in artifact_cards] == []
