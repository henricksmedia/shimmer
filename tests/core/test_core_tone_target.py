"""The tone target is an input: 1.1.1's by default, bit for bit, and a
reference track's when the user picks one (docs/MASTERING-SOURCES.md §4).

Interface: shimmer.core.master.tone
    compute_tone_curve(x, sr, ..., target_db=None, deadband_db=None) -> list
    reference_shape(x_ref, sr) -> one level per band, level-matched
    match_curve(x, sr, reference_db, amount=MATCH_AMOUNT, tilt="neutral",
                cutoff_hz=None, ref_cutoff_hz=None) -> list
    MATCH_AMOUNT (0.5), MATCH_LIMIT_DB (3.0)
"""
import numpy as np
import pytest

from _contract import needs

pytestmark = needs("shimmer.core.master.tone")

SR = 48000


def _noise(seed=0, db_per_octave=0.0, seconds=4.0, top_hz=None, level=0.1):
    """Stereo noise with a straight tilt around 1 kHz, optionally cut off
    above top_hz like a band-limited file."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.maximum(np.fft.rfftfreq(n, 1.0 / SR), 20.0)
    gain = 10.0 ** (db_per_octave * np.log2(f / 1000.0) / 20.0)
    if top_hz:
        gain[f > top_hz] = 0.0
    x = np.fft.irfft(spec * gain, n)
    x = level * x / np.std(x)
    return np.stack([x, x], axis=1).astype(np.float32)


def _band(hz):
    from shimmer.core.analyze.track import REF_FREQS
    return int(np.argmin(np.abs(REF_FREQS - hz)))


# ── The target as an input ──────────────────────────────────────────────

def test_the_default_target_is_1_1_1s_bit_for_bit():
    from shimmer.core.master import tone
    x = _noise(1, -1.5)
    base = tone.compute_tone_curve(x, SR, strength=0.55, tilt="warm")
    assert tone.compute_tone_curve(x, SR, strength=0.55, tilt="warm",
                                   target_db=tone.REF_DB) == base
    old = pytest.importorskip("shimmer.mastering")
    assert old.compute_tone_curve(x, SR, strength=0.55, tilt="warm") == base


def test_the_target_decides_where_the_curve_goes():
    # The song's own shape as the target: nothing to do. The same, 1 dB up
    # from 2 kHz: a lift there, and nothing below.
    from shimmer.core.analyze.track import REF_FREQS
    from shimmer.core.master import tone
    x = _noise(2, -1.0)
    own = tone.reference_shape(x, SR)
    same = tone.compute_tone_curve(x, SR, strength=1.0, target_db=own)
    assert max(abs(v) for v in same) < 0.05
    lifted = tone.compute_tone_curve(x, SR, strength=1.0,
                                     target_db=own + np.where(REF_FREQS >= 2000.0, 1.0, 0.0))
    assert lifted[_band(4000)] > 0.8
    assert abs(lifted[_band(250)]) < 0.05


def test_a_deadband_wider_than_every_difference_leaves_the_song_alone():
    from shimmer.core.master import tone
    curve = tone.compute_tone_curve(_noise(3, -2.0), SR, strength=1.0, deadband_db=100.0)
    assert curve == [0.0] * len(curve)


def test_a_per_band_deadband_must_have_one_value_per_band():
    from shimmer.core.master import tone
    with pytest.raises(ValueError):
        tone.compute_tone_curve(_noise(4), SR, deadband_db=[1.0, 2.0])


def test_the_candidate_deadband_only_ever_shrinks_the_move():
    from shimmer.core.master import tone
    x = _noise(5, -2.0)
    full = np.abs(tone.compute_tone_curve(x, SR, strength=1.0))
    held = np.abs(tone.compute_tone_curve(x, SR, strength=1.0, deadband_db=tone.REF_TOL_DB))
    assert float(held.sum()) < float(full.sum())


# ── Reference-track matching ────────────────────────────────────────────

def test_the_defaults_follow_the_sources():
    from shimmer.core.master import tone
    assert tone.MATCH_AMOUNT == 0.5
    assert tone.MATCH_LIMIT_DB == 3.0


def test_the_reference_shape_ignores_its_level():
    from shimmer.core.master import tone
    quiet = tone.reference_shape(_noise(6, 1.0, level=0.01), SR)
    loud = tone.reference_shape(_noise(6, 1.0, level=0.3), SR)
    assert np.max(np.abs(quiet - loud)) < 0.02


def test_matching_a_song_to_itself_changes_nothing():
    from shimmer.core.master import tone
    x = _noise(7, -1.0)
    curve = tone.match_curve(x, SR, tone.reference_shape(x, SR))
    assert max(abs(v) for v in curve) < 0.02


def test_a_brighter_reference_brightens_and_a_darker_one_darkens():
    from shimmer.core.master import tone
    x = _noise(8)
    bright = tone.match_curve(x, SR, tone.reference_shape(_noise(9, 1.0), SR))
    dark = tone.match_curve(x, SR, tone.reference_shape(_noise(9, -1.0), SR))
    assert bright[_band(8000)] > 0.5 and bright[_band(63)] < -0.5
    assert dark[_band(8000)] < -0.5 and dark[_band(63)] > 0.5


def test_the_match_never_moves_a_band_more_than_3_db():
    from shimmer.core.master import tone
    x = _noise(10)
    for tilt in ("warmer", "neutral", "brightest"):
        for slope in (-6.0, 6.0):
            curve = tone.match_curve(x, SR, tone.reference_shape(_noise(11, slope), SR),
                                     amount=1.0, tilt=tilt)
            assert max(abs(v) for v in curve) <= 3.0 + 1e-9, (tilt, slope)


def test_the_amount_scales_the_match():
    # Small differences, so no limit is reached: half the amount is half
    # the curve, band by band.
    from shimmer.core.master import tone
    x = _noise(12)
    ref = tone.reference_shape(_noise(13, 0.2), SR)
    full = np.array(tone.match_curve(x, SR, ref, amount=1.0))
    assert np.max(np.abs(full)) < 1.9
    half = np.array(tone.match_curve(x, SR, ref))
    assert np.allclose(half, 0.5 * full, atol=1e-9)


def test_the_match_is_smooth():
    # About an octave of smoothing: neighbouring bands never jump apart,
    # even against a jagged reference.
    from shimmer.core.master import tone
    x = _noise(14)
    ref = tone.reference_shape(x, SR) + np.where(np.arange(29) % 2 == 0, 4.0, -4.0)
    curve = np.array(tone.match_curve(x, SR, ref, amount=1.0))
    assert np.max(np.abs(np.diff(curve))) < 1.0


def test_an_empty_top_in_the_reference_never_cuts_the_songs_real_one():
    # A 16 kHz MP3 as the reference, against a full-band song of the same
    # shape: the empty bands are not matched, and do not drag the next
    # band down through the smoothing.
    from shimmer.core.master import tone
    x = _noise(15)
    ref = tone.reference_shape(_noise(15, top_hz=16000.0), SR)
    curve = tone.match_curve(x, SR, ref, ref_cutoff_hz=16000.0)
    assert curve[_band(16000)] == 0.0 and curve[_band(20000)] == 0.0
    assert abs(curve[_band(12500)]) < 0.05


def test_nothing_is_boosted_above_the_songs_cutoff():
    from shimmer.core.master import tone
    x = _noise(16, top_hz=15000.0)
    ref = tone.reference_shape(_noise(17, 2.0), SR)
    curve = tone.match_curve(x, SR, ref, amount=1.0, tilt="brightest", cutoff_hz=15000.0)
    assert curve[_band(16000)] <= 0.0 and curve[_band(20000)] <= 0.0


def test_the_tilt_still_applies_on_top_of_a_match():
    from shimmer.core.master import tone
    x = _noise(18)
    ref = tone.reference_shape(x, SR)
    bright = tone.match_curve(x, SR, ref, tilt="bright")
    assert bright[_band(3150)] > 0.3 and bright[_band(63)] < -0.3
