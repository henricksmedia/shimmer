"""An M4A uses the system's AAC encoder when ffmpeg has one (audio/io.py
_aac_encoders): ffmpeg's built-in encoder glitched on loud masters, up to
3.6 dB over the master at one spot on a test song."""
import shutil

import numpy as np
import pytest

from shimmer.core.audio import io, meters


def test_system_encoders_come_first_at_their_rates(monkeypatch):
    monkeypatch.setattr(io, "_encoders", lambda: ("aac", "aac_mf", "libmp3lame"))
    assert io._aac_encoders(48000) == ["aac_mf", "aac"]
    assert io._aac_encoders(44100) == ["aac_mf", "aac"]
    assert io._aac_encoders(96000) == ["aac"]          # the system encoders stop at 48 kHz
    monkeypatch.setattr(io, "_encoders", lambda: ("aac",))
    assert io._aac_encoders(48000) == ["aac"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_failing_system_encoder_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(io, "_aac_encoders", lambda sr: ["no_such_encoder", "aac"])
    sr = 48000
    t = np.arange(2 * sr) / sr
    x = np.stack([0.3 * np.sin(2 * np.pi * 440 * t)] * 2, axis=1).astype(np.float32)
    p = tmp_path / "a.m4a"
    io.save(str(p), x, sr, bitrate="256k")
    y, _ = io.load(str(p))
    assert abs(meters.loudness(y, sr) - meters.loudness(x, sr)) < 0.5
