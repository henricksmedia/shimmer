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
import numpy as np

from _contract import needs

album = needs("shimmer.core.master.loudness")
tone = needs("shimmer.core.master.tone")

FREQS = np.array([31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 12500, 16000, 20000], dtype=float)


@album
def test_album_mode_keeps_the_distances_between_songs():
    from shimmer.core.master.loudness import album_gains
    gains = album_gains([-12.0, -10.0, -15.0], -9.0)
    assert len(set(round(g, 6) for g in gains)) == 1     # one gain for the record
    assert abs((-10.0 + gains[1]) - (-9.0)) < 1e-6        # the loudest lands on target


@album
def test_a_silent_track_does_not_break_album_mode():
    from shimmer.core.master.loudness import album_gains
    gains = album_gains([-12.0, float("-inf"), -10.0], -9.0)
    assert all(np.isfinite(g) for g in gains)
    assert abs((-10.0 + gains[2]) - (-9.0)) < 1e-6


@tone
def test_the_tone_curve_stays_inside_its_limits():
    from shimmer.core.master.tone import tone_curve
    rng = np.random.default_rng(4)
    measured = rng.uniform(-12, 12, FREQS.size)
    curve = tone_curve(measured, np.zeros(FREQS.size), FREQS, strength=1.0,
                       max_boost_db=2.0, max_cut_db=3.0)
    assert np.max(curve) <= 2.0 + 1e-9
    assert np.min(curve) >= -3.0 - 1e-9


@tone
def test_the_tone_curve_moves_toward_the_target():
    from shimmer.core.master.tone import tone_curve
    measured = np.linspace(-2.0, 2.0, FREQS.size)      # a mix tilted bright
    curve = tone_curve(measured, np.zeros(FREQS.size), FREQS)
    assert curve[0] > 0 > curve[-1]
    assert np.corrcoef(curve, -measured)[0, 1] > 0.9


@tone
def test_strength_scales_the_curve():
    from shimmer.core.master.tone import tone_curve
    measured = np.linspace(-1.0, 1.0, FREQS.size)      # small enough to stay inside the limits
    full = tone_curve(measured, np.zeros(FREQS.size), FREQS, strength=1.0)
    half = tone_curve(measured, np.zeros(FREQS.size), FREQS, strength=0.5)
    assert np.max(np.abs(full)) > 0.3
    assert np.allclose(half, 0.5 * full, atol=0.05)


@tone
def test_the_tone_target_is_an_input():
    from shimmer.core.master.tone import tone_curve
    measured = np.zeros(FREQS.size)
    a = tone_curve(measured, np.linspace(-1, 1, FREQS.size), FREQS)
    b = tone_curve(measured, np.linspace(1, -1, FREQS.size), FREQS)
    assert not np.allclose(a, b)


@tone
def test_nothing_is_boosted_above_the_cutoff():
    from shimmer.core.master.tone import tone_curve
    measured = np.full(FREQS.size, -10.0)     # everything wants a boost
    curve = tone_curve(measured, np.zeros(FREQS.size), FREQS, cutoff_hz=12000.0)
    assert np.all(curve[FREQS >= 0.9 * 12000.0] <= 1e-9)


@tone
def test_zero_strength_is_flat():
    from shimmer.core.master.tone import tone_curve
    curve = tone_curve(np.full(FREQS.size, 5.0), np.zeros(FREQS.size), FREQS, strength=0.0)
    assert np.allclose(curve, 0.0)
