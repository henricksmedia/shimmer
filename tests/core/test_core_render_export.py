"""One render path and one export stage, for every tab.

The old app had six copies of load -> clean -> master -> save, and its preview
differed from its export in 13 ways (ARCHITECTURE §5). Now the preview is
the same render on a window, and every tab writes through one export.

Interface: shimmer.core.render
    Source.from_array(x, sr) / Source.load(path)
    render(source, settings, window=None) -> Rendered(.audio, .sr, .report)
        window = (start_s, end_s) or None
Interface: shimmer.core.export
    export(rendered, path, source_path=None, tags=None) -> dict
        dict has "lufs" and "true_peak_dbtp" as written to disk
"""
import importlib.util
import shutil

import numpy as np
import pytest
import soundfile as sf

pytestmark = pytest.mark.xfail(importlib.util.find_spec("shimmer.core") is None,
                               reason="shimmer.core is not built yet (rebuild Step 4)",
                               strict=True)

TARGET_LUFS = {"streaming": -14.0, "loud": -11.0, "cd": -9.0}
CEILING = {"wav": -1.0, "wav16": -1.0, "flac": -1.0, "mp3": -1.5, "ogg": -1.5, "m4a": -1.5}
EXT = {"wav": ".wav", "wav16": ".wav", "flac": ".flac", "mp3": ".mp3", "ogg": ".ogg", "m4a": ".m4a"}


def _residual_db(a, b):
    """How far below `b` the difference a - b sits, in dB (positive = below)."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    n = min(len(a), len(b))
    d = a[:n] - b[:n]
    return 10 * np.log10(np.mean(b[:n] ** 2) / max(np.mean(d ** 2), 1e-30))


def test_bypass_changes_nothing(clean_mix):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    out = render(Source.from_array(x, sr), Settings.bypass()).audio
    assert np.array_equal(np.asarray(out, dtype=np.float32), x)


def test_length_is_preserved(clean_mix):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    assert render(Source.from_array(x, sr), Settings()).audio.shape == x.shape


def test_the_preview_is_the_export_on_a_window(clean_mix):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    src = Source.from_array(x, sr)
    full = render(src, Settings()).audio
    win = render(src, Settings(), window=(3.0, 6.0)).audio
    ref = full[int(3.0 * sr):int(6.0 * sr)]
    assert len(win) == len(ref)
    assert _residual_db(win, ref) >= 60.0


def test_a_clean_track_comes_out_unchanged(clean_mix):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    out = render(Source.from_array(x, sr), Settings(auto=True, mastering=False)).audio
    assert _residual_db(out, x) >= 60.0


@pytest.mark.parametrize("target", ["streaming", "loud", "cd"])
def test_every_loudness_choice_is_reached_under_the_ceiling(headroom_mix, target):
    from shimmer.core.audio import meters
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = headroom_mix
    out = render(Source.from_array(x, sr), Settings(loudness_target=target)).audio
    assert abs(meters.loudness(out, sr) - TARGET_LUFS[target]) <= 0.3
    assert meters.true_peak_db(out, sr) <= -1.0 + 0.05


@pytest.mark.parametrize("fmt", ["wav", "wav16", "flac", "ogg"])
def test_exports_write_and_stay_under_their_ceiling(tmp_path, headroom_mix, fmt):
    from shimmer.core.audio import meters
    from shimmer.core.export import export
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = headroom_mix
    rendered = render(Source.from_array(x, sr), Settings(loudness_target="cd", format=fmt))
    path = tmp_path / f"out{EXT[fmt]}"
    rep = export(rendered, path)
    y, ysr = sf.read(str(path), always_2d=True)
    measured = meters.loudness(y, ysr)
    if fmt == "ogg":
        # Lossy: the -1.5 ceiling leaves room for the decoder's overshoot.
        assert meters.true_peak_db(y, ysr) <= -1.0
    else:
        assert meters.true_peak_db(y, ysr) <= CEILING[fmt] + 0.05
        assert abs(rep["lufs"] - measured) <= 0.1


def test_the_release_copy_is_16_bit_44k_and_dithered(tmp_path, headroom_mix):
    from shimmer.core.export import export
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = headroom_mix
    rendered = render(Source.from_array(x, sr), Settings(format="wav16"))
    path = tmp_path / "release.wav"
    export(rendered, path)
    info = sf.info(str(path))
    assert info.samplerate == 44100
    assert info.subtype == "PCM_16"
    # Dither: silence written at 16 bits is not all zeros.
    silent = render(Source.from_array(np.zeros_like(x), sr), Settings.bypass().replace(format="wav16"))
    export(silent, tmp_path / "silent.wav")
    z, _ = sf.read(str(tmp_path / "silent.wav"), dtype="int16", always_2d=True)
    assert np.mean(z != 0) > 0.3


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
@pytest.mark.parametrize("fmt", ["mp3", "m4a"])
def test_lossy_exports_write_and_read_back(tmp_path, headroom_mix, fmt):
    from shimmer.core.audio import io, meters
    from shimmer.core.export import export
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = headroom_mix
    rendered = render(Source.from_array(x, sr), Settings(loudness_target="cd", format=fmt))
    path = tmp_path / f"out{EXT[fmt]}"
    export(rendered, path)
    y, ysr = io.load(path)
    assert abs(len(y) / ysr - len(x) / sr) < 0.2
    assert meters.true_peak_db(y, ysr) <= -1.0


def test_export_never_overwrites_the_source(tmp_path, clean_mix):
    from shimmer.core.export import export
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    song = tmp_path / "song.wav"
    sf.write(str(song), x, sr, subtype="PCM_24")
    rendered = render(Source.load(song), Settings())
    with pytest.raises(ValueError):
        export(rendered, song, source_path=song)
