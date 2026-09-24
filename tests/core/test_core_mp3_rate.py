"""An MP3 holds 48 kHz at most (catalog: max_sr). A song above that is
resampled by render(), before the fixes and the limiter, so the peak ceiling
holds at the rate the file is written at; the encoder used to resample it
after the limiter."""
import shutil

import numpy as np
import pytest

from shimmer.core import Settings, Source, catalog, export, render


def test_rate_for():
    mp3, wav, wav16 = (catalog.output_format(k) for k in ("mp3", "wav", "wav16"))
    assert (mp3.rate_for(96000), mp3.rate_for(48000), mp3.rate_for(44100)) == (48000, 48000, 44100)
    assert (wav.rate_for(96000), wav16.rate_for(96000)) == (96000, 44100)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_96_khz_song_is_mastered_at_48_khz_for_mp3(tmp_path):
    sr = 96000
    t = np.arange(3 * sr) / sr
    x = 0.3 * np.sin(2 * np.pi * 440.0 * t) * (1 + 0.5 * np.sin(2 * np.pi * 2 * t))
    src = Source.from_array(np.stack([x, x], axis=1).astype(np.float32), sr)
    r = render(src, Settings(auto=False, format="mp3"))
    assert r.sr == 48000
    rep = export(r, tmp_path / "song.mp3")
    assert rep["sr"] == 48000
    assert rep["true_peak_dbtp"] <= -1.0 + 0.05
