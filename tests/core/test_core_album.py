"""Album mode in the engine: one gain for a whole record.

Interface: shimmer.core
    premaster_levels(source, settings) -> {lufs_i, true_peak_dbtp}
    render(source, settings, gain_db=None): gain_db replaces the song's own
        gain to its loudness target
    master.loudness.album_gains(levels, target) -> one gain per track
"""
import numpy as np

from _contract import needs

pytestmark = needs("shimmer.core.render")

SR = 48000


def _song(seed, level):
    rng = np.random.default_rng(seed)
    n = SR * 6
    t = np.arange(n) / SR
    x = 0.5 * np.sin(2 * np.pi * 82 * t) + 0.4 * rng.standard_normal(n)
    x = np.stack([x, x], axis=1)
    return (level * x / np.max(np.abs(x))).astype(np.float32)


def test_premaster_levels_are_what_render_works_its_gain_out_from():
    from shimmer.core import Settings, Source, premaster_levels, render
    src = Source.from_array(_song(1, 0.3), SR)
    s = Settings()
    levels = premaster_levels(src, s)
    r = render(Source.from_array(_song(1, 0.3), SR), s)
    assert levels["lufs_i"] == r.report["mastering"]["loudness_before_lufs"]
    assert np.isfinite(levels["true_peak_dbtp"])


def test_the_songs_own_gain_passed_in_gives_the_same_master():
    from shimmer.core import Settings, Source, render
    src = Source.from_array(_song(2, 0.3), SR)
    s = Settings(loudness_target="streaming")
    own = render(src, s)
    again = render(src, s, gain_db=own.report["mastering"]["gain_db"])
    assert np.array_equal(own.audio, again.audio)
    assert again.report["mastering"]["album_gain"] is True
    assert own.report["mastering"]["album_gain"] is False


def test_an_album_keeps_its_songs_apart():
    from shimmer.core import Settings, Source, catalog, premaster_levels, render
    from shimmer.core.audio.meters import loudness
    from shimmer.core.master.loudness import album_gains
    s = Settings(loudness_target="streaming")
    songs = [Source.from_array(_song(3, 0.3), SR), Source.from_array(_song(3, 0.15), SR)]
    levels = [premaster_levels(x, s)["lufs_i"] for x in songs]
    gains = album_gains(levels, catalog.loudness_target("streaming").lufs)
    out = [loudness(render(x, s, gain_db=g).audio, SR) for x, g in zip(songs, gains)]
    assert abs(out[0] - (-14.0)) <= 0.3
    assert abs((out[0] - out[1]) - (levels[0] - levels[1])) <= 0.3


def test_a_preview_window_uses_the_album_gain_too():
    from shimmer.core import Settings, Source, render
    src = Source.from_array(_song(4, 0.2), SR)
    s = Settings()
    full = render(src, s, gain_db=-3.0).audio
    w = render(src, s, (2.0, 4.0), gain_db=-3.0).audio
    span = full[2 * SR:4 * SR]
    assert 20 * np.log10(float(np.max(np.abs(w - span))) / float(np.max(np.abs(span))) + 1e-12) < -60
