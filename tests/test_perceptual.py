"""Tests for the BS.1387 damage model.

These are the properties `purity` failed. Each one is a thing the old metric
got wrong on real audio, written as a test so it cannot come back.
"""
import numpy as np
import pytest

from shimmer import perceptual as P


SR = 48000


def _tone(f, secs=2.0, amp=0.5, sr=SR):
    t = np.arange(int(secs * sr)) / sr
    return amp * np.sin(2 * np.pi * f * t)


def _noise(secs=2.0, amp=1e-3, sr=SR, seed=0):
    rng = np.random.default_rng(seed)
    return amp * rng.standard_normal(int(secs * sr))


def _music(secs=3.0, sr=SR, seed=1):
    """A crude but broadband stand-in: harmonic stack + noise bed + hits."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(secs * sr)) / sr
    x = sum(0.3 / k * np.sin(2 * np.pi * 220 * k * t) for k in range(1, 12))
    x += 0.02 * rng.standard_normal(t.size)          # broadband bed
    for onset in np.arange(0.25, secs, 0.5):         # transients
        i = int(onset * sr)
        env = np.exp(-np.arange(sr // 10) / (sr * 0.01))
        x[i:i + env.size] += 0.4 * env * rng.standard_normal(env.size)
    return 0.4 * x / np.max(np.abs(x))


# ── Model wiring ───────────────────────────────────────────────────────

def test_critical_bands_match_the_published_table():
    # BS.1387 Basic version: 109 bands of 0.25 Bark spanning 80 Hz-18 kHz.
    # The first band is 80.000-103.445 Hz centred on 91.708 Hz in the
    # standard's own table; hitting that to three decimals says the Bark
    # mapping is right, not merely plausible.
    b = P.bands()
    assert b.n == 109
    assert b.fl[0] == pytest.approx(80.0, abs=0.01)
    assert b.fc[0] == pytest.approx(91.708, abs=0.01)
    assert b.fu[0] == pytest.approx(103.445, abs=0.01)
    assert b.fu[-1] == pytest.approx(18000.0, abs=1.0)
    assert np.all(np.diff(b.fc) > 0)


def test_ear_weighting_matches_the_published_response():
    # Kabal eq. 6: about -1.9 dB at 1 kHz, peak near +5.6 dB at 3.3 kHz.
    w = P._ear_weight(np.array([1000.0, 3300.0]))
    assert 20 * np.log10(w[0]) == pytest.approx(-1.9, abs=0.2)
    assert 20 * np.log10(w[1]) == pytest.approx(5.6, abs=0.3)
    assert P._ear_weight(np.array([0.0]))[0] == 0.0


def test_loudness_of_a_calibration_tone_is_physical():
    # Full-scale 1 kHz sine is calibrated to 92 dB SPL; loudness should land
    # in the tens of sones, not near zero and not absurd.
    lo = P.loudness(P.excitation_patterns(_tone(1000.0, amp=1.0), SR)[1])
    assert 10.0 < float(np.median(lo)) < 100.0


def test_quiet_signal_is_far_less_loud_than_a_loud_one():
    loud = P.loudness(P.excitation_patterns(_tone(1000.0, amp=1.0), SR)[1])
    quiet = P.loudness(P.excitation_patterns(_tone(1000.0, amp=0.01), SR)[1])
    assert float(np.median(quiet)) < 0.25 * float(np.median(loud))


# ── The properties purity could not deliver ────────────────────────────

def test_no_processing_is_no_damage():
    x = _music()
    d = P.measure_damage(x, x.copy(), SR)
    assert d.lin_dist < 0.01
    assert d.missing < 0.01
    assert d.added < 0.01


def test_removing_audible_content_registers_as_missing():
    """A 6 dB cut above 4 kHz is plainly audible and must score."""
    from shimmer.eq import EqBand, EqParams, apply_eq
    x = _music()
    y = apply_eq(x[:, None], SR, EqParams(
        enabled=True,
        bands=[EqBand("high_shelf", 4000.0, -6.0, 0.7, True)]))[:, 0]
    d = P.measure_damage(x, y, SR)
    assert d.missing > 0.05, d.as_dict()


def test_a_bigger_cut_scores_worse_than_a_smaller_one():
    """Monotonic in the amount removed — the core requirement."""
    from shimmer.eq import EqBand, EqParams, apply_eq
    x = _music()
    out = []
    for gain in (-2.0, -6.0, -12.0):
        y = apply_eq(x[:, None], SR, EqParams(
            enabled=True,
            bands=[EqBand("high_shelf", 4000.0, gain, 0.7, True)]))[:, 0]
        out.append(P.measure_damage(x, y, SR).missing)
    assert out[0] < out[1] < out[2], out


def _shelf(x, gain_db, freq=3000.0):
    from shimmer.eq import EqBand, EqParams, apply_eq
    return apply_eq(x[:, None], SR, EqParams(
        enabled=True,
        bands=[EqBand("high_shelf", freq, gain_db, 0.7, True)]))[:, 0]


def test_spectral_tilt_shows_up_as_linear_distortion():
    """lin_dist is the measure that catches Shimmer's actual failure mode."""
    x = _music()
    flat = P.measure_damage(x, x.copy(), SR).lin_dist
    assert P.measure_damage(x, _shelf(x, -8.0), SR).lin_dist > flat


def test_lin_dist_lands_at_the_expected_magnitude():
    """Pin the SIZE of lin_dist, not just its sign.

    budget.py thresholds this measure with absolute constants
    (LIN_DIST_BASE = 1.0), so a silent change of scale would move the line
    between "a preset a listener accepted" and "the preset ranked last on
    every song" while every other test stayed green.

    That is not hypothetical. An audit's mutation testing left a `* 0.04`
    factor in measure_damage, and the whole suite passed with it in place:
    the -12 dB case read 1.97 instead of 49.4, and the budget then allowed
    4.5x more removal. This test is the one that would have caught it.

    The band is wide on purpose - the same shelf scores ~49 on this
    transient-bearing signal and ~72 on the transient-free one used in
    test_budget.py, so the value is signal-dependent and only its order of
    magnitude is a property of the model.
    """
    x = _music()
    lin = P.measure_damage(x, _shelf(x, -12.0), SR).lin_dist
    assert 30.0 < lin < 80.0, f"lin_dist scale has moved: {lin}"


def test_lin_dist_grows_with_the_size_of_the_tilt():
    x = _music()
    got = [P.measure_damage(x, _shelf(x, g), SR).lin_dist
           for g in (-3.0, -6.0, -12.0)]
    assert got[0] < got[1] < got[2], got
    # ...and the smallest tilt still clears the budget's base ceiling, so the
    # ceiling is doing work rather than sitting above everything.
    from shimmer.budget import LIN_DIST_BASE
    assert got[0] > LIN_DIST_BASE


def test_added_noise_registers_as_added_not_missing():
    x = _music()
    y = x + _noise(secs=len(x) / SR, amp=0.02, seed=7)[:len(x)]
    d = P.measure_damage(x, y, SR)
    assert d.added > d.missing, d.as_dict()


def test_inaudible_change_scores_near_zero():
    """The whole point: a change buried far under the masking threshold is
    not damage. `purity` would have scored this the same as a cymbal."""
    x = _music()
    y = x + _noise(secs=len(x) / SR, amp=1e-7, seed=3)[:len(x)]
    d = P.measure_damage(x, y, SR)
    assert d.added < 0.01, d.as_dict()
    assert d.missing < 0.01, d.as_dict()


def test_gate_skips_the_leading_silence():
    """The gate must react to the silence, not just to the fixed delay.

    The earlier version of this test only asserted gated_frames < frames on a
    padded clip. That is true of ANY clip longer than the unconditional
    half-second delay, so it passed with the loudness gate disabled entirely.
    Comparing padded against unpadded is what actually exercises it.
    """
    x = _music()
    bare = P.measure_damage(x, x.copy(), SR)
    padded_audio = np.concatenate([np.zeros(SR), x])
    padded = P.measure_damage(padded_audio, padded_audio.copy(), SR)

    dropped_bare = bare.frames - bare.gated_frames
    dropped_padded = padded.frames - padded.gated_frames
    # A second of silence must push the start later by roughly a second of
    # frames, not leave it on the fixed delay alone.
    assert dropped_padded > dropped_bare + 0.5 * P.FSS, (
        f"gate did not react to leading silence: {dropped_bare} -> {dropped_padded}")


def test_measure_accepts_stereo_and_mismatched_lengths():
    x = _music()
    st = np.stack([x, x * 0.9], axis=1)
    d = P.measure_damage(st, st[:-1000], SR)
    assert d.frames > 0
