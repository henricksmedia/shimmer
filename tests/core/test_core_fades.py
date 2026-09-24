"""The Trim card's fades (shimmer/core/analyze/edges.py apply_fades). The
fade-out falls evenly in dB to silence on the last sample; the fade-in rises
on a quarter sine; each is held to half the song."""
import numpy as np

from shimmer.core.analyze.edges import (FADE_CLOSE, FADE_MAX_S, FADE_OUT_RANGE_DB,
                                        apply_fades, fade_in_curve, fade_out_curve)

SR = 48000


def _ones(seconds):
    return np.ones((int(seconds * SR), 2), dtype=np.float32)


def test_no_fade_leaves_the_song_alone():
    x = _ones(3)
    y, rep = apply_fades(x, SR, 0, 0)
    assert not rep["applied"]
    assert np.array_equal(y, x)


def test_fade_out_ends_in_silence_and_falls_evenly_in_db():
    y, rep = apply_fades(_ones(20), SR, 0, 4)
    assert rep["applied"] and rep["fade_out_s"] == 4.0 and rep["fade_in_s"] == 0.0
    assert y[-1, 0] == 0.0 and y[-1, 1] == 0.0
    n = 4 * SR
    g = y[-n:, 0]
    assert g[0] == 1.0
    db = 20 * np.log10(g[: int(n * (1 - FADE_CLOSE))])
    # Evenly in dB: a straight line from 0 dB, the same step all the way.
    steps = np.diff(db[:: SR // 10])
    assert np.ptp(steps) < 0.05
    # Half way through it is half the range down, not 6 dB.
    assert abs(20 * np.log10(g[n // 2]) + FADE_OUT_RANGE_DB / 2) < 0.01
    assert np.array_equal(y[:-n], np.ones_like(y[:-n]))


def test_fade_in_starts_in_silence_and_reaches_full_level():
    y, rep = apply_fades(_ones(10), SR, 1, 0)
    assert rep["fade_in_s"] == 1.0
    assert y[0, 0] == 0.0
    assert abs(y[SR - 1, 0] - 1.0) < 1e-6
    # A quarter sine: past 70 % of full level half way through.
    assert 0.70 < y[SR // 2, 0] < 0.72
    assert np.all(np.diff(y[:SR, 0]) >= 0)


def test_fades_are_held_to_half_the_song_and_the_limit():
    y, rep = apply_fades(_ones(4), SR, 10, 10)
    assert rep["fade_in_s"] == 2.0 and rep["fade_out_s"] == 2.0
    y, rep = apply_fades(_ones(100), SR, 0, 99)
    assert rep["fade_out_s"] == FADE_MAX_S


def test_bad_lengths_mean_no_fade():
    x = _ones(2)
    for bad in (-3, float("nan"), float("inf"), "x", None):
        y, rep = apply_fades(x, SR, bad, bad)
        assert not rep["applied"]


def test_curves_match_the_screen():
    # static/js/trim.js draws and auditions with the same formulas.
    t = np.array([0.5, 0.95])
    want = 10 ** (-FADE_OUT_RANGE_DB * t / 20) * np.clip((1 - t) / FADE_CLOSE, 0, 1)
    assert np.allclose(fade_out_curve(21)[[10, 19]], want, atol=1e-6)
    assert abs(fade_in_curve(3)[1] - np.sin(np.pi / 4)) < 1e-6
