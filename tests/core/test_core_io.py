"""Files come in and go out unchanged in shape, rate and level.

Interface: shimmer.core.audio.io
    load(path) -> (float32 (samples, channels), sr)
    save(path, y, sr, subtype="PCM_24", bitrate=None)
    wav_bytes(y, sr, subtype="PCM_16") -> bytes
    resample(x, sr, target_sr) -> (y, target_sr)
"""
import shutil

import numpy as np
import pytest
import soundfile as sf

from _contract import needs

pytestmark = needs("shimmer.core.audio.io")

SR = 48000
NEEDS_FFMPEG = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _tone(channels=2, seconds=1.0, hz=1000.0, dbfs=-12.0):
    t = np.arange(int(seconds * SR)) / SR
    s = 10 ** (dbfs / 20) * np.sin(2 * np.pi * hz * t)
    return np.stack([s] * channels, axis=1).astype(np.float32)


@pytest.mark.parametrize("ext, subtype", [(".wav", "PCM_24"), (".wav", "FLOAT"),
                                          (".flac", "PCM_24"), (".wav", "PCM_16")])
def test_lossless_files_round_trip(tmp_path, ext, subtype):
    from shimmer.core.audio import io
    x = _tone()
    p = tmp_path / f"a{ext}"
    io.save(p, x, SR, subtype=subtype)
    y, sr = io.load(p)
    assert sr == SR and y.shape == x.shape and y.dtype == np.float32
    assert np.max(np.abs(y - x)) < 2.0 / 32768


def test_mono_stays_mono(tmp_path):
    from shimmer.core.audio import io
    p = tmp_path / "m.wav"
    io.save(p, _tone(channels=1)[:, 0], SR)
    y, _ = io.load(p)
    assert y.shape[1] == 1


def test_ogg_is_vorbis_and_reads_back(tmp_path):
    from shimmer.core.audio import io
    p = tmp_path / "a.ogg"
    io.save(p, _tone(seconds=2.0), SR)
    assert sf.info(str(p)).subtype == "VORBIS"
    y, sr = io.load(p)
    assert sr == SR and abs(len(y) - 2 * SR) < SR // 10


def test_a_long_ogg_writes_without_crashing(tmp_path):
    # libsndfile's Vorbis encoder overflowed the stack on one big write: a
    # 20 s stereo OGG killed Python outright. A whole song must write.
    from shimmer.core.audio import io
    p = tmp_path / "long.ogg"
    io.save(p, _tone(seconds=60.0, dbfs=-20.0), SR, quality=0.8)
    y, sr = io.load(p)
    assert sr == SR and abs(len(y) - 60 * SR) < SR // 10


@NEEDS_FFMPEG
@pytest.mark.parametrize("ext, channels", [(".mp3", 2), (".m4a", 2), (".mp3", 1)])
def test_lossy_files_keep_rate_channels_and_level(tmp_path, ext, channels):
    from shimmer.core.audio import io
    x = _tone(channels=channels, seconds=2.0)
    p = tmp_path / f"a{ext}"
    io.save(p, x, SR, bitrate="320k" if ext == ".mp3" else "256k")
    y, sr = io.load(p)
    assert sr == SR and y.shape[1] == channels
    assert abs(len(y) - len(x)) < SR // 10                      # encoder padding only
    rms = lambda a: 20 * np.log10(np.sqrt(np.mean(a.astype(np.float64) ** 2)))
    assert abs(rms(y) - rms(x)) < 0.5


def test_lossy_encoding_starts_from_float(tmp_path, monkeypatch):
    # The old path wrote a 16-bit temp file with no dither before encoding.
    from shimmer.core.audio import io
    seen = []
    real = io.sf.write
    monkeypatch.setattr(io.sf, "write", lambda *a, **k: (seen.append(k.get("subtype")), real(*a, **k))[1])
    monkeypatch.setattr(io.subprocess, "run", lambda *a, **k: None)
    io.save(tmp_path / "a.mp3", _tone(), SR, bitrate="320k")
    assert seen == ["FLOAT"]


def test_unknown_formats_fail_clearly(tmp_path):
    from shimmer.core.audio import io
    with pytest.raises(io.AudioIOError):
        io.save(tmp_path / "a.xyz", _tone(), SR)


def test_wav_bytes_is_a_readable_wav():
    import io as bytesio
    from shimmer.core.audio import io
    y, sr = sf.read(bytesio.BytesIO(io.wav_bytes(_tone(), SR)), always_2d=True)
    assert sr == SR and y.shape == (SR, 2)


def test_resampling_keeps_a_tone_and_its_level():
    from shimmer.core.audio import io
    x = _tone(seconds=2.0)
    y, sr = io.resample(x, SR, 44100)
    assert sr == 44100 and abs(len(y) - 2 * 44100) <= 1
    mid = slice(len(y) // 4, 3 * len(y) // 4)
    assert abs(np.max(np.abs(y[mid])) - np.max(np.abs(x))) < 0.01
    same, sr2 = io.resample(x, SR, SR)
    assert sr2 == SR and np.array_equal(same, x.astype(np.float64))
