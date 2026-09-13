"""
The fault models added for Step 6 (consonants, harshness, mud, phasiness in
shimmer/artifacts.py) and the side-effect measures (shimmer/side_effects.py).

A model is ground truth only if it is what it claims: in its band, shaped
by the music the way the complaint describes, and repeatable. A side-effect
measure is useful only if it reads zero on "nothing changed" and moves the
right way on a process known to cause that side effect.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from scipy import signal as ss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer import artifacts as A        # noqa: E402
from shimmer import side_effects as SE    # noqa: E402

SR = 48000


def _music(seconds: float = 4.0, seed: int = 0) -> np.ndarray:
    """Chords that change every half second, a bass, noise-burst drums every
    quarter second, and a little wide ambience: stereo, peak -6 dBFS."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    x = np.zeros(n)
    step = int(0.5 * SR)
    for i in range(n // step):
        s, e = i * step, (i + 1) * step
        t = np.arange(e - s) / SR
        f0 = 220.0 * 2 ** (rng.integers(0, 12) / 12.0)
        env = np.exp(-2.0 * t)
        for h in range(1, 9):
            x[s:e] += (0.25 / h) * env * np.sin(2 * np.pi * f0 * h * t)
        x[s:e] += 0.3 * env * np.sin(2 * np.pi * f0 / 4.0 * t)
    hit = int(0.03 * SR)
    for s in range(0, n - hit, int(0.25 * SR)):
        x[s:s + hit] += 0.5 * rng.standard_normal(hit) * np.exp(-np.linspace(0, 6, hit))
    amb = ss.sosfilt(ss.butter(2, [500.0, 8000.0], btype="bandpass", fs=SR, output="sos"),
                     rng.standard_normal((n, 2)), axis=0)
    y = np.stack([x, x], axis=1) + 0.05 * amb
    return (y * 10 ** (-6 / 20) / np.max(np.abs(y))).astype(np.float32)


def _band_share(x: np.ndarray, lo: float, hi: float) -> float:
    f, P = ss.welch(np.asarray(x, dtype=np.float64).mean(axis=1), fs=SR, nperseg=4096)
    m = (f >= lo) & (f < hi)
    return float(P[m].sum() / P.sum())


def _envelope(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    sos = ss.butter(4, [lo, hi], btype="bandpass", fs=SR, output="sos")
    e = np.abs(ss.hilbert(ss.sosfilt(sos, np.asarray(x, dtype=np.float64).mean(axis=1))))
    k = int(0.05 * SR)
    return np.convolve(e, np.ones(k) / k, mode="same")[::k]


@pytest.mark.parametrize("name", ["consonants", "harshness", "mud", "phasiness"])
def test_new_models_are_repeatable_stereo_and_finite(name):
    h = _music()
    a = A.make(name, h.shape[0], SR, host=h)
    assert a.shape == h.shape and a.dtype == np.float32
    assert np.array_equal(a, A.make(name, h.shape[0], SR, host=h))
    assert np.all(np.isfinite(a)) and float(np.abs(a).max()) > 1e-3


@pytest.mark.parametrize("name,lo,hi,share", [
    ("consonants", 4500.0, 9500.0, 0.9),
    ("harshness", 1600.0, 7000.0, 0.85),
    ("mud", 170.0, 600.0, 0.75),
    ("phasiness", 900.0, 13000.0, 0.95),
])
def test_new_models_sit_in_their_band(name, lo, hi, share):
    h = _music()
    assert _band_share(A.make(name, h.shape[0], SR, host=h), lo, hi) > share


@pytest.mark.parametrize("name,lo,hi", [("harshness", 1000.0, 6000.0), ("mud", 150.0, 600.0)])
def test_resonances_come_and_go_with_the_music(name, lo, hi):
    h = _music()
    a = A.make(name, h.shape[0], SR, host=h)
    r = np.corrcoef(_envelope(h, lo, hi), _envelope(a, lo, hi))[0, 1]
    assert r > 0.6, r


def test_harshness_centres_move_with_the_seed():
    h = _music()
    peaks = set()
    for seed in (1, 2, 3):
        a = A.harshness(h.shape[0], SR, h, seed=seed)
        f, P = ss.welch(a.mean(axis=1), fs=SR, nperseg=8192)
        peaks.add(int(round(f[int(np.argmax(P))] / 100.0)))
    assert len(peaks) >= 2


def test_phasiness_keeps_the_level_and_scrambles_the_phase():
    h = _music()
    a = A.make("phasiness", h.shape[0], SR, host=h)
    r = h + a
    f, _, H = ss.stft(h[:, 0], fs=SR, nperseg=2048)
    _, _, R = ss.stft(r[:, 0], fs=SR, nperseg=2048)
    band = (f >= 1000.0) & (f <= 12000.0)
    lh = 10 * np.log10(np.sum(np.abs(H[band]) ** 2))
    lr = 10 * np.log10(np.sum(np.abs(R[band]) ** 2))
    # Frames keep their levels; overlapping scrambled frames partly cancel,
    # so the tails lose about 1.5 dB (the model's docstring).
    assert abs(lr - lh) < 2.0, (lh, lr)
    # The change is real: the difference is a large share of the band.
    assert float(np.sqrt(np.mean(a ** 2))) > 0.2 * float(np.sqrt(np.mean(
        ss.sosfilt(ss.butter(4, [1000.0, 12000.0], btype="bandpass", fs=SR, output="sos"),
                   h, axis=0) ** 2)))


def test_side_effects_read_zero_when_nothing_changes():
    h = _music()
    m = SE.measure(h, h.copy(), SR)
    assert m == {"width_db": 0.0, "attack_db": 0.0, "pumping_db": 0.0}


def test_width_reads_a_narrower_mix():
    h = _music()
    mid = h.mean(axis=1, keepdims=True)
    narrower = (mid + 0.3 * (h - mid)).astype(np.float32)
    assert SE.width_db(h, narrower) < -9.0


def test_pumping_reads_a_mix_ducked_by_its_hits():
    h = _music()
    env = _envelope(h, 60.0, 20000.0)
    duck = np.repeat(1.0 / (1.0 + 4.0 * env / env.max()), int(0.05 * SR))[:h.shape[0]]
    duck = np.pad(duck, (0, h.shape[0] - len(duck)), mode="edge")
    assert SE.pumping_db(h, (h * duck[:, None]).astype(np.float32), SR) > 3.0


def test_a_static_filter_does_not_pump():
    h = _music()
    y = ss.sosfilt(ss.butter(2, 3000.0, btype="lowpass", fs=SR, output="sos"), h, axis=0)
    assert SE.pumping_db(h, y.astype(np.float32), SR, band=(3000.0, None)) < 0.5


def test_attack_reads_softened_hits():
    h = _music()
    pos = SE.onsets(h, SR)
    assert len(pos) >= 8
    g = np.ones(h.shape[0])
    w = int(0.008 * SR)
    for p in pos:
        g[p:p + w] = np.minimum(g[p:p + w], np.linspace(0.3, 1.0, len(g[p:p + w])))
    assert SE.attack_db(h, (h * g[:, None]).astype(np.float32), SR) < -2.0
