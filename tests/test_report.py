"""
Report numbers (report.py): band spectra with a level-matched delta,
peak-to-loudness ratio, stereo correlation.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_report.py -q
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.report import (band_centers, band_spectrum_db, plr_db,
                            spectra_report, stereo_correlation)

SR = 48000


def _tone(hz: float, amp: float, secs: float = 4.0) -> np.ndarray:
    t = np.arange(int(secs * SR)) / SR
    s = (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    return np.stack([s, s], axis=1)


def _noise(secs: float = 4.0, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((int(secs * SR), 2)) * 0.05).astype(np.float32)


def test_band_spectrum_puts_a_tone_in_its_band():
    centers = band_centers(SR)
    bands = band_spectrum_db(_tone(1000.0, 0.5), SR, centers)
    peak = int(np.argmax(bands))
    assert abs(np.log2(centers[peak] / 1000.0)) < 0.2
    # Everything an octave away is far down.
    far = [b for c, b in zip(centers, bands) if abs(np.log2(c / 1000.0)) > 1.0]
    assert max(far) < bands[peak] - 40.0


def test_level_matched_delta_ignores_plain_gain():
    x = _noise()
    r = spectra_report(x, x * 2.0, None, SR)
    assert abs(r["gain_db"] - 6.02) < 0.2
    assert max(abs(d) for d in r["delta_db"]) < 0.3
    assert r["cut"] is None


def test_delta_finds_a_high_cut():
    x = _noise()
    # Take 10 dB out above ~6 kHz with a simple FFT brick-wall.
    spec = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(x.shape[0], 1.0 / SR)
    spec[f > 6000.0] *= 10 ** (-10 / 20)
    y = np.fft.irfft(spec, n=x.shape[0], axis=0).astype(np.float32)
    r = spectra_report(x, y, x - y, SR)
    assert r["cut"] is not None
    assert r["cut"]["lo_hz"] >= 4000.0
    assert 7.0 < r["cut"]["max_cut_db"] < 12.0
    assert r["low_max_abs_db"] < 1.0
    # The removed signal's spectrum is highest where the cut is.
    rem = np.asarray(r["removed_db"])
    centers = np.asarray(r["centers_hz"])
    assert centers[int(np.argmax(rem))] > 4000.0


def test_stereo_correlation_extremes():
    s = _tone(440.0, 0.3)
    assert stereo_correlation(s) > 0.99
    anti = np.stack([s[:, 0], -s[:, 0]], axis=1)
    assert stereo_correlation(anti) < -0.99
    assert stereo_correlation(s[:, :1]) is None


def test_plr_is_peak_minus_loudness():
    x = _tone(1000.0, 0.5)
    # A -6 dBFS sine: true peak about -6 dBTP; PLR = tp - lufs.
    v = plr_db(x, SR, -9.0)
    assert v is not None and 2.0 < v < 4.0
    assert plr_db(x, SR, None) is None
