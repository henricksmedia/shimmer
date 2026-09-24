"""The detectors behind Analyze's findings (shimmer/core/analyze/detectors.py).

Each must stay quiet on a finished master and speak up when its fault is
there. The lines themselves were set on the test library (docs/DETECTORS.md).
"""
import os

import numpy as np
import pytest
from scipy import signal as ss

from shimmer.core.analyze import detectors as D
from shimmer.core.analyze.findings import findings, slow_findings
from shimmer.core.render import Source

SR = 48000
REF = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "reference")
REFS = [os.path.join(REF, n) for n in ("reference-hey.wav", "reference-leave-the-world-behind.wav")]
REQUIRE_CORPUS = os.environ.get("SHIMMER_REQUIRE_CORPUS") == "1"


def _noise(seconds=20.0, seed=1):
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(int(seconds * SR))
    # Roughly the slope of a mix: pink-ish, -3 dB per octave.
    b, a = [0.049922035, -0.095993537, 0.050612699, -0.004408786], [1, -2.494956002, 2.017265875, -0.522189400]
    y = ss.lfilter(b, a, x)
    y = np.stack([y, y], axis=1)
    return (0.1 * y / np.max(np.abs(y))).astype(np.float32)


def test_levels():
    assert D._level(1.0, 3.0, 6.0) == ""
    assert D._level(3.0, 3.0, 6.0) == D.SOME
    assert D._level(7.0, 3.0, 6.0) == D.A_LOT


def test_a_dull_song_reads_darker_than_a_bright_one():
    x = _noise()
    sos = ss.butter(4, 6000, btype="lowpass", fs=SR, output="sos")
    dull = ss.sosfilt(sos, x, axis=0).astype(np.float32)
    a_bright = D.air(Source.from_array(x, SR))
    a_dull = D.air(Source.from_array(dull, SR))
    assert a_dull is not None and a_bright is not None
    assert a_dull.value > a_bright.value + 6.0
    assert a_dull.level == D.A_LOT


def test_a_low_mid_bump_is_found():
    x = _noise(seed=2)
    sos = ss.butter(2, [200, 500], btype="bandpass", fs=SR, output="sos")
    bumped = (x + 1.5 * ss.sosfilt(sos, x, axis=0)).astype(np.float32)
    plain = D.lowmid(Source.from_array(x, SR))
    more = D.lowmid(Source.from_array(bumped, SR))
    assert more.value > plain.value + 3.0


def test_findings_carry_level_and_amount():
    x = _noise(seed=3)
    sos = ss.butter(2, [200, 500], btype="bandpass", fs=SR, output="sos")
    muddy = (x + 3.0 * ss.sosfilt(sos, x, axis=0)).astype(np.float32)
    f = {g.card: g for g in findings(Source.from_array(muddy, SR))}
    assert "mud" in f and f["mud"].level in (D.SOME, D.A_LOT)
    assert f["mud"].amount == D.AMOUNT[f["mud"].level]


def test_the_slow_detectors_read_a_share():
    src = Source.from_array(_noise(8.0, seed=4), SR)
    got = D.slow(src)
    assert set(got) == {c for c, _, _ in D.SLOW}
    for r in got.values():
        assert 0.0 <= r.value <= 100.0 and r.unit == "%"


@pytest.mark.skipif(not all(os.path.exists(p) for p in REFS) and not REQUIRE_CORPUS,
                    reason="reference masters not on this machine")
@pytest.mark.parametrize("path", REFS)
def test_a_finished_master_raises_nothing(path):
    src = Source.load(path)
    cards = {f.card for f in findings(src) + slow_findings(src)}
    assert not cards & {"air", "mud", "sibilance", "harshness"}, cards
