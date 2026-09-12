"""Mastering rules that do not depend on any one song.

Interface: shimmer.core.master.loudness
    album_gains(lufs_per_track, target_lufs) -> list[float]
        one gain for the whole record: the loudest track lands on the target
Interface: shimmer.core.master.tone
    tone_curve(measured_db, target_db, freqs_hz, strength=1.0,
               max_boost_db=2.0, max_cut_db=3.0, cutoff_hz=None) -> ndarray
        the tone target is an input, never a constant (the old one changed
        four times on belief; ARCHITECTURE §3)
"""
import importlib.util

import numpy as np
import pytest

pytestmark = pytest.mark.xfail(importlib.util.find_spec("shimmer.core") is None,
                               reason="shimmer.core is not built yet (rebuild Step 4)",
                               strict=True)

FREQS = np.array([31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 12500, 16000, 20000], dtype=float)


def test_album_mode_keeps_the_distances_between_songs():
    from shimmer.core.master.loudness import album_gains
    gains = album_gains([-12.0, -10.0, -15.0], -9.0)
    assert len(set(round(g, 6) for g in gains)) == 1     # one gain for the record
    assert abs((-10.0 + gains[1]) - (-9.0)) < 1e-6        # the loudest lands on target


def test_the_tone_curve_stays_inside_its_limits():
    from shimmer.core.master.tone import tone_curve
    rng = np.random.default_rng(4)
    measured = rng.uniform(-12, 12, FREQS.size)
    curve = tone_curve(measured, np.zeros(FREQS.size), FREQS, strength=1.0,
                       max_boost_db=2.0, max_cut_db=3.0)
    assert np.max(curve) <= 2.0 + 1e-9
    assert np.min(curve) >= -3.0 - 1e-9


def test_the_tone_target_is_an_input():
    from shimmer.core.master.tone import tone_curve
    measured = np.zeros(FREQS.size)
    a = tone_curve(measured, np.linspace(-1, 1, FREQS.size), FREQS)
    b = tone_curve(measured, np.linspace(1, -1, FREQS.size), FREQS)
    assert not np.allclose(a, b)


def test_nothing_is_boosted_above_the_cutoff():
    from shimmer.core.master.tone import tone_curve
    measured = np.full(FREQS.size, -10.0)     # everything wants a boost
    curve = tone_curve(measured, np.zeros(FREQS.size), FREQS, cutoff_hz=12000.0)
    assert np.all(curve[FREQS >= 0.9 * 12000.0] <= 1e-9)


def test_zero_strength_is_flat():
    from shimmer.core.master.tone import tone_curve
    curve = tone_curve(np.full(FREQS.size, 5.0), np.zeros(FREQS.size), FREQS, strength=0.0)
    assert np.allclose(curve, 0.0)
