"""One render path and one export stage, for every tab.

The old app had six copies of load -> clean -> master -> save, and its preview
differed from its export in 13 ways (ARCHITECTURE §5). Now the preview is
the same render on a window, and every tab writes through one export.

Interface: shimmer.core.render
    Source.from_array(x, sr) / Source.load(path)
    render(source, settings, window=None) -> Rendered(.audio, .sr, .report)
        window = (start_s, end_s) or None: samples round(start_s * sr) up
        to round(end_s * sr), at the output rate. The output rate is the
        chosen format's (44.1 kHz for the release copy), so the preview of
        a release copy matches it too.
Interface: shimmer.core.export
    export(rendered, path, source_path=None, tags=None) -> dict
        dict has "lufs" and "true_peak_dbtp" as written to disk.
        Refuses (ValueError) to write over the file the render came from.

Loudness and true peak are read here with meters independent of the engine
(_contract.lufs and true_peak_16x_db).
"""
import shutil

import numpy as np
import pytest
import soundfile as sf

from _contract import lufs, needs, true_peak_16x_db

rendering = needs("shimmer.core.render", "shimmer.core.settings")
exporting = needs("shimmer.core.render", "shimmer.core.settings", "shimmer.core.export")

TARGET_LUFS = {"streaming": -14.0, "loud": -11.0, "cd": -9.0}
EXT = {"wav": ".wav", "wav16": ".wav", "flac": ".flac", "mp3": ".mp3", "ogg": ".ogg", "m4a": ".m4a"}
NEEDS_FFMPEG = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _residual_db(a, b):
    """How far below `b` the difference a - b sits, in dB (positive = below)."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    n = min(len(a), len(b))
    d = a[:n] - b[:n]
    return 10 * np.log10(np.mean(b[:n] ** 2) / max(np.mean(d ** 2), 1e-30))


def _stepped(x):
    """First half 12 dB quieter, so a gain worked out from a window alone
    would be wrong."""
    y = x.astype(np.float64).copy()
    y[: len(y) // 2] *= 10 ** (-12 / 20)
    return y.astype(np.float32)


@rendering
def test_bypass_changes_nothing(clean_mix):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    out = render(Source.from_array(x, sr), Settings.bypass()).audio
    assert np.array_equal(np.asarray(out, dtype=np.float32), x)


@rendering
def test_length_is_preserved(clean_mix):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    assert render(Source.from_array(x, sr), Settings()).audio.shape == x.shape


@rendering
@pytest.mark.parametrize("window", [(0.0, 2.0), (3.137, 6.411), (7.5, 10.0)])
def test_the_preview_is_the_export_on_a_window(dense_mix, window):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = dense_mix
    src = Source.from_array(_stepped(x), sr)
    full = render(src, Settings()).audio
    win = render(src, Settings(), window=window).audio
    ref = full[round(window[0] * sr):round(window[1] * sr)]
    assert len(win) == len(ref)
    assert _residual_db(win, ref) >= 60.0


@rendering
def test_the_release_copy_preview_matches_it(dense_mix):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = dense_mix
    src = Source.from_array(x, sr)
    full = render(src, Settings(format="wav16"))
    win = render(src, Settings(format="wav16"), window=(3.0, 6.0))
    assert full.sr == win.sr == 44100
    assert _residual_db(win.audio, full.audio[round(3.0 * 44100):round(6.0 * 44100)]) >= 60.0


@rendering
def test_a_clean_track_comes_out_unchanged(clean_mix):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    out = render(Source.from_array(x, sr), Settings(auto=True, mastering=False)).audio
    assert _residual_db(out, x) >= 60.0


@rendering
@pytest.mark.parametrize("target", ["streaming", "loud", "cd"])
def test_every_loudness_choice_is_reached_under_the_ceiling(dense_mix, target):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = dense_mix
    out = render(Source.from_array(x, sr), Settings(loudness_target=target))
    assert abs(lufs(out.audio, out.sr) - TARGET_LUFS[target]) <= 0.3
    assert true_peak_16x_db(out.audio) <= -1.0 + 0.05


@rendering
@pytest.mark.parametrize("target", ["streaming", "loud", "cd"])
def test_a_very_dynamic_track_is_never_pushed_past_its_target(clean_mix, target):
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    out = render(Source.from_array(x, sr), Settings(loudness_target=target))
    assert lufs(out.audio, out.sr) <= TARGET_LUFS[target] + 0.3
    assert true_peak_16x_db(out.audio) <= -1.0 + 0.05


@exporting
@pytest.mark.parametrize("fmt", ["wav", "wav16", "flac"])
def test_lossless_exports_hit_the_target_under_the_ceiling(tmp_path, dense_mix, fmt):
    from shimmer.core.export import export
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = dense_mix
    rendered = render(Source.from_array(x, sr), Settings(loudness_target="cd", format=fmt))
    path = tmp_path / f"out{EXT[fmt]}"
    rep = export(rendered, path)
    y, ysr = sf.read(str(path), always_2d=True)
    measured = lufs(y, ysr)
    assert abs(measured - TARGET_LUFS["cd"]) <= 0.3
    assert abs(rep["lufs"] - measured) <= 0.1               # the report tells the truth
    assert true_peak_16x_db(y) <= -1.0 + 0.05


@exporting
@pytest.mark.parametrize("fmt", ["ogg",
                                 pytest.param("mp3", marks=NEEDS_FFMPEG),
                                 pytest.param("m4a", marks=NEEDS_FFMPEG)])
def test_lossy_exports_decode_under_the_ceiling(tmp_path, dense_mix, fmt):
    from shimmer.core.audio import io
    from shimmer.core.export import export
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = dense_mix
    rendered = render(Source.from_array(x, sr), Settings(loudness_target="cd", format=fmt))
    path = tmp_path / f"out{EXT[fmt]}"
    export(rendered, path)
    y, ysr = io.load(path)
    assert abs(len(y) / ysr - len(x) / sr) < 0.2
    # What the listener hears is the decoded file. OGG written at -1.5
    # dBTP decoded at -0.48 in the old engine (ARCHITECTURE §19).
    assert true_peak_16x_db(y) <= -1.0


@exporting
def test_the_release_copy_is_16_bit_44k_and_dithered(tmp_path, dense_mix):
    from shimmer.core.export import export
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = dense_mix
    export(render(Source.from_array(x, sr), Settings(format="wav16")), tmp_path / "release.wav")
    info = sf.info(str(tmp_path / "release.wav"))
    assert info.samplerate == 44100
    assert info.subtype == "PCM_16"
    # Dither: a 1 kHz tone at -100 dBFS is a third of one 16-bit step.
    # Rounded plainly it vanishes; with TPDF dither it survives at its level
    # (measured -99.9 dBFS with textbook dither, 2026-09-12).
    t = np.arange(len(x)) / sr
    faint = np.repeat((10 ** (-100 / 20) * np.sin(2 * np.pi * 1000.0 * t))[:, None], 2, axis=1)
    export(render(Source.from_array(faint.astype(np.float32), sr),
                  Settings.bypass().replace(format="wav16")), tmp_path / "faint.wav")
    z, zsr = sf.read(str(tmp_path / "faint.wav"), always_2d=True)
    m = z.mean(axis=1)
    win = np.hanning(len(m))
    h = np.abs(np.fft.rfft(m * win)) / (np.sum(win) / 2)
    f = np.fft.rfftfreq(len(m), 1 / zsr)
    i = np.argmin(np.abs(f - 1000.0))
    assert abs(20 * np.log10(np.max(h[i - 2:i + 3]) + 1e-20) - (-100.0)) < 1.5


@exporting
def test_exports_carry_their_tags(tmp_path, dense_mix):
    from mutagen.flac import FLAC
    from shimmer.core.export import export
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = dense_mix
    path = tmp_path / "tagged.flac"
    export(render(Source.from_array(x, sr), Settings(format="flac")), path,
           tags={"title": "Test Song", "artist": "Test Artist"})
    got = FLAC(str(path))
    assert got["TITLE"] == ["Test Song"]
    assert got["ARTIST"] == ["Test Artist"]


@exporting
def test_export_never_overwrites_the_source(tmp_path, clean_mix):
    from shimmer.core.export import export
    from shimmer.core.render import Source, render
    from shimmer.core.settings import Settings
    x, sr = clean_mix
    song = tmp_path / "song.wav"
    sf.write(str(song), x, sr, subtype="PCM_24")
    before = song.read_bytes()
    rendered = render(Source.load(song), Settings())
    with pytest.raises(ValueError):
        export(rendered, song, source_path=song)
    with pytest.raises(ValueError):
        export(rendered, song)                                   # the render knows where it came from
    with pytest.raises(ValueError):
        export(rendered, tmp_path / "sub" / ".." / "song.wav")   # the same file, spelled differently
    assert song.read_bytes() == before
