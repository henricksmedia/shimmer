"""render() with a reference track: the tone curve moves toward the
reference, and everything else holds as it does without one.

Interface: shimmer.core
    render(source, settings, window=None, ..., reference=None)
    Settings.match_amount (default catalog.MATCH_AMOUNT)
"""
import numpy as np

from _contract import needs

pytestmark = needs("shimmer.core.render", "shimmer.core.master.tone")

SR = 48000


def _noise(seed=0, db_per_octave=0.0, seconds=8.0, level=0.1):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    spec = np.fft.rfft(rng.standard_normal((n, 2)), axis=0)
    f = np.maximum(np.fft.rfftfreq(n, 1.0 / SR), 20.0)
    gain = 10.0 ** (db_per_octave * np.log2(f / 1000.0) / 20.0)
    x = np.fft.irfft(spec * gain[:, None], n, axis=0)
    return (level * x / np.std(x)).astype(np.float32)


def _sources():
    from shimmer.core import Source
    song = Source.from_array(_noise(1, -3.0), SR)
    ref = Source.from_array(_noise(2, -2.0, seconds=6.0), SR)
    return song, ref


def test_without_a_reference_the_target_is_shimmers():
    from shimmer.core import Settings, render
    from shimmer.core.master import tone
    song, _ = _sources()
    r = render(song, Settings())
    assert r.report["mastering"]["tone_target"] == "shimmer"
    assert "match_amount" not in r.report["mastering"]
    expected = tone.compute_tone_curve(song.audio, SR, strength=tone.intensity_to_strength("med"),
                                       tilt="neutral", cutoff_hz=None)
    assert r.report["mastering"]["tone_curve_db"] == [round(v, 2) for v in expected]


def test_with_a_reference_the_curve_is_the_match():
    from shimmer.core import Settings, render
    from shimmer.core.master import tone
    song, ref = _sources()
    s = Settings(match_amount=0.4, tilt="warm")
    r = render(song, s, reference=ref)
    m = r.report["mastering"]
    assert m["tone_target"] == "reference" and m["match_amount"] == 0.4
    expected = tone.match_curve(song.audio, SR, tone.reference_shape(ref.audio, SR),
                                amount=0.4, tilt="warm")
    assert m["tone_curve_db"] == [round(v, 2) for v in expected]
    # The reference is brighter than the song, so the match lifts the top.
    assert m["tone_curve_db"][25] > 0.5


def test_the_same_song_renders_differently_with_and_without_a_reference():
    from shimmer.core import Settings, render
    song, ref = _sources()
    a = render(song, Settings()).audio
    b = render(song, Settings(), reference=ref).audio
    assert float(np.max(np.abs(a - b))) > 1e-3
    # And the cache keeps them apart: the plain render again is unchanged.
    assert np.array_equal(render(song, Settings()).audio, a)


def test_a_preview_window_matches_the_export_with_a_reference():
    from shimmer.core import Settings, render
    song, ref = _sources()
    s = Settings()
    full = render(song, s, reference=ref).audio
    w = render(song, s, (3.0, 5.0), reference=ref).audio
    span = full[int(round(3.0 * SR)):int(round(5.0 * SR))]
    err = float(np.max(np.abs(w - span))) / float(np.max(np.abs(span)))
    assert 20.0 * np.log10(err + 1e-12) < -60.0


def test_loudness_still_lands_on_target_with_a_reference():
    from shimmer.core import Settings, catalog, render
    from shimmer.core.audio.meters import loudness
    song, ref = _sources()
    for key in ("cd", "streaming"):
        r = render(song, Settings(loudness_target=key), reference=ref)
        got = loudness(r.audio, SR)
        assert abs(got - catalog.loudness_target(key).lufs) <= 0.3, (key, got)


def test_match_amount_is_kept_between_0_and_1():
    from shimmer.core import Settings, catalog
    assert Settings().match_amount == catalog.MATCH_AMOUNT == 0.5
    assert Settings(match_amount=3.0).match_amount == 1.0
    assert Settings(match_amount=-1).match_amount == 0.0
    assert Settings(match_amount="x").match_amount == 0.5
    assert Settings.from_dict(Settings(match_amount=0.3).to_dict()).match_amount == 0.3
