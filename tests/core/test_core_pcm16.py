"""16-bit files round to the nearest step, WAV and FLAC alike
(shimmer/core/audio/io.py). libsndfile 1.2.2 rounds WAV down, which added
3 dB of noise and half a step of DC (docs/CHAIN-AUDIT.md section 4)."""
import numpy as np
import pytest
import soundfile as sf

from shimmer.core.audio import io

SR = 48000


@pytest.mark.parametrize("ext", [".wav", ".flac"])
def test_16_bit_rounds_to_nearest(tmp_path, ext):
    x = (np.random.default_rng(0).standard_normal((SR, 2)) * 0.1).astype(np.float32)
    path = tmp_path / f"r16{ext}"
    io.save(path, x, SR, "PCM_16")
    y, _ = sf.read(path, dtype="int16")
    err = y / 32768.0 - x
    assert np.max(np.abs(err)) * 32768.0 <= 0.5 + 1e-6      # never more than half a step
    assert abs(float(np.mean(err))) * 32768.0 < 0.01          # no DC
