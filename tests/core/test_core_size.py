"""How big each file will be, for the size limit: the estimate against the
file export() really writes.

Interface: shimmer.core.export
    estimate_size(audio, sr, key) -> {format, bytes, low, high, exact}
    estimate_sizes(audio, sr) -> {key: estimate} for every format
    export(...)["size_bytes"]: the written file's size
"""
import os

import pytest

import conftest
from _contract import needs

pytestmark = needs("shimmer.core.export")

SR = 48000


def _master(tmp_path, key, seconds=40.0):
    from shimmer import core
    src = core.Source.from_array(conftest._clean(seconds=seconds), SR)
    r = core.render(src, core.Settings(format=key))
    path = tmp_path / f"out_{key}{core.catalog.output_format(key).ext}"
    rep = core.export(r, str(path))
    return r, rep, path


@pytest.mark.parametrize("key", ["wav", "wav16"])
def test_a_wav_size_is_exact(tmp_path, key):
    from shimmer.core.export import estimate_size
    r, rep, path = _master(tmp_path, key)
    est = estimate_size(r.audio, r.sr, key)
    assert est["exact"] and est["low"] == est["high"] == est["bytes"]
    assert abs(os.path.getsize(path) - est["bytes"]) <= 64
    assert rep["size_bytes"] == os.path.getsize(path)


def test_the_release_copy_size_is_worked_out_from_a_48_khz_master(tmp_path):
    from shimmer.core.export import estimate_size
    r48, _, _ = _master(tmp_path, "wav")
    _, _, path16 = _master(tmp_path, "wav16")
    est = estimate_size(r48.audio, r48.sr, "wav16")
    assert abs(os.path.getsize(path16) - est["bytes"]) <= 64


@pytest.mark.parametrize("key", ["flac", "flac16"])
def test_a_flac_size_lands_in_its_range(tmp_path, key):
    from shimmer.core.export import estimate_size
    r, rep, path = _master(tmp_path, key)
    est = estimate_size(r.audio, r.sr, key)
    assert not est["exact"]
    assert est["low"] <= os.path.getsize(path) <= est["high"], (est, os.path.getsize(path))


def test_flac16_is_the_release_copy_as_flac(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    from shimmer.core.export import estimate_sizes
    r, _, path = _master(tmp_path, "flac16")
    info = soundfile.info(str(path))
    assert (info.format, info.subtype, info.samplerate) == ("FLAC", "PCM_16", 44100)
    sizes = estimate_sizes(r.audio, r.sr)
    assert sizes["flac16"]["high"] < sizes["wav16"]["bytes"]


def test_before_the_run_the_estimate_reads_the_master_not_the_upload(tmp_path):
    # A 16-bit upload written as 24-bit FLAC keeps its low bits empty and
    # compresses to half its mastered size; the estimate renders windows of
    # the master instead, so it brackets the real file.
    soundfile = pytest.importorskip("soundfile")
    from shimmer import core
    from shimmer.core.export import estimate_sizes_for
    x = conftest._clean(seconds=45.0)
    upload = tmp_path / "upload.wav"
    soundfile.write(str(upload), x, SR, subtype="PCM_16")
    src = core.Source.load(str(upload))
    for key in ("flac", "flac16", "wav"):
        s = core.Settings(format=key, loudness_target="cd")
        est = estimate_sizes_for(src, s)[key]
        path = tmp_path / f"m_{key}{core.catalog.output_format(key).ext}"
        size = core.export(core.render(src, s), str(path))["size_bytes"]
        assert est["low"] <= size <= est["high"] or abs(size - est["bytes"]) <= 64, (key, est, size)


def test_every_format_has_an_estimate():
    from shimmer.core import catalog
    from shimmer.core.export import estimate_sizes
    sizes = estimate_sizes(conftest._clean(seconds=12.0), SR)
    assert set(sizes) == {f.key for f in catalog.FORMATS}
    mp3 = sizes["mp3"]
    assert mp3["low"] == mp3["high"] == round(12.0 * 320_000 / 8)
    assert sizes["ogg"]["low"] < sizes["ogg"]["high"]
