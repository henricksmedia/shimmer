"""What the reference-track match will do, for the screen
(core.reference_view): the same EQ curve render() applies, both tone
shapes, where the top is not matched, and whether the drums differ a lot.

Interface: shimmer.core
    reference_view(source, reference, settings) -> view dict
    percussive_share(audio, sr) -> 0 (held notes) .. 1 (hits)
"""
import numpy as np

from _contract import needs

pytestmark = needs("shimmer.core.analyze.percussion")

SR = 44100


def _stereo(x):
    return np.stack([x, x], axis=1).astype(np.float32)


def _pad(seconds=12.0, seed=0):
    """Held notes: a slow chord with a little noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    x = sum(0.2 * np.sin(2 * np.pi * f * t) for f in (220.0, 277.2, 329.6, 440.0))
    x = x * (0.8 + 0.2 * np.sin(2 * np.pi * 0.2 * t)) + 0.01 * rng.standard_normal(t.size)
    return _stereo(0.4 * x / np.max(np.abs(x)))


def _drums(seconds=12.0, seed=1):
    """Hits: noise bursts and kick thumps four times a second."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    beat = (t * 4.0) % 1.0
    env = np.exp(-beat * 40.0)
    x = env * (rng.standard_normal(n) * 0.5 + np.sin(2 * np.pi * 60.0 * t))
    return _stereo(0.4 * x / np.max(np.abs(x)))


def _noise(db_per_octave, seconds=12.0, seed=2, top_hz=None):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.maximum(np.fft.rfftfreq(n, 1.0 / SR), 20.0)
    g = 10.0 ** (db_per_octave * np.log2(f / 1000.0) / 20.0)
    if top_hz:
        g[f > top_hz] = 0.0
    x = np.fft.irfft(spec * g, n)
    return _stereo(0.1 * x / np.std(x))


def test_held_notes_and_hits_read_apart():
    from shimmer.core import percussive_share
    pad, drums = percussive_share(_pad(), SR), percussive_share(_drums(), SR)
    assert pad < 0.3 < 0.6 < drums, (pad, drums)
    assert percussive_share(np.zeros((SR, 2), np.float32), SR) == 0.0


def test_the_chart_curve_is_the_curve_render_applies():
    from shimmer import core
    song = core.Source.from_array(_noise(-2.0), SR)
    ref = core.Source.from_array(_noise(0.0, seed=3), SR)
    s = core.Settings(match_amount=0.5, tilt="warm")
    view = core.reference_view(song, ref, s)
    applied = core.render(song, s, reference=ref).report["mastering"]["tone_curve_db"]
    assert view["curve_db"] == applied
    assert len(view["song_db"]) == len(view["reference_db"]) == len(view["freqs_hz"]) == 29
    assert view["match_amount"] == 0.5 and view["limit_db"] == 3.0


def test_very_different_drums_are_flagged_both_ways():
    from shimmer import core
    pad, drums = core.Source.from_array(_pad(), SR), core.Source.from_array(_drums(), SR)
    assert core.reference_view(pad, drums)["percussive"]["differs"] == "more"
    assert core.reference_view(drums, pad)["percussive"]["differs"] == "less"
    other = core.Source.from_array(_pad(seed=5), SR)
    assert core.reference_view(pad, other)["percussive"]["differs"] is None


def test_an_mp3_like_reference_says_where_matching_stops():
    from shimmer import core
    song = core.Source.from_array(_noise(-1.0), SR)
    ref = core.Source.from_array(_noise(-1.0, seed=4, top_hz=16000.0), SR)
    view = core.reference_view(song, ref)
    assert 13000.0 < view["matched_up_to_hz"] < 15000.0, view["reference_cutoff_hz"]
    full = core.reference_view(song, core.Source.from_array(_noise(-1.0, seed=6), SR))
    assert full["matched_up_to_hz"] is None
