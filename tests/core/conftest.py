"""Shared test signals for the contract tests of the new engine, shimmer.core.

The contract tests in this folder describe what the rebuilt engine must do
before it exists (docs/ARCHITECTURE.md §15 Step 3). Each test waits for the
exact modules it imports (_contract.needs), so one piece of the engine can
land on its own, and the moment its modules exist the test must pass.

The signals here are synthetic and seeded, so a test never depends on a file
that is not in the repo, and never builds its stimulus from the constant it
tests (PITFALLS.md, "Self-referential tests drift"). Their levels were
measured before any test pinned them (2026-09-12).
"""
import numpy as np
import pytest
from scipy.signal import butter, sosfilt

SR = 48000


def _clean(seconds=10.0, seed=3):
    """Music-like stereo with no artifacts.

    A melody whose note changes every half second, so no partial stays at one
    frequency long enough to look like a fixed tone; a moving bass; and
    noise-burst drums on every quarter second. Peak at -6 dBFS.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    x = np.zeros(n)
    step = int(0.5 * SR)
    for i in range(n // step):
        s, e = i * step, (i + 1) * step
        seg = np.arange(e - s) / SR
        f0 = 220.0 * 2 ** (rng.integers(0, 12) / 12.0)
        env = np.exp(-3.0 * seg)
        for h in range(1, 7):
            x[s:e] += (0.2 / h) * env * np.sin(2 * np.pi * f0 * h * seg)
        x[s:e] += 0.3 * env * np.sin(2 * np.pi * (f0 / 4.0) * seg)
    hit = int(0.03 * SR)
    for s in range(0, n - hit, int(0.25 * SR)):
        x[s:s + hit] += 0.4 * rng.standard_normal(hit) * np.exp(-np.linspace(0, 6, hit))
    left = x
    right = 0.9 * x
    y = np.stack([left, right], axis=1)
    y *= 10 ** (-6 / 20) / np.max(np.abs(y))
    return y.astype(np.float32)


def _dense(seconds=10.0, seed=5):
    """A dense, sustained mix, like a finished song before mastering.

    A four-note pad whose chord changes every 2 s, a bass, a high noise bed
    and a kick every half second. Peak at -6 dBFS.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    step = int(2.0 * SR)
    for i in range(n // step + 1):
        s, e = i * step, min((i + 1) * step, n)
        if s >= n:
            break
        seg = t[s:e] - t[s]
        root = 110.0 * 2 ** (rng.integers(0, 12) / 12.0)
        for ratio in (1.0, 1.26, 1.5, 2.0):
            for h in range(1, 5):
                x[s:e] += (0.06 / h) * np.sin(2 * np.pi * root * ratio * h * seg + rng.uniform(0, 6.28))
    x += 0.25 * np.sin(2 * np.pi * 55.0 * t) * (0.7 + 0.3 * np.sin(2 * np.pi * 0.5 * t))
    x += 0.08 * sosfilt(butter(2, 5000, "highpass", fs=SR, output="sos"), rng.standard_normal(n))
    hit = int(0.08 * SR)
    kt = np.arange(hit) / SR
    kick = np.sin(2 * np.pi * (60 * kt + 400 * (1 - np.exp(-kt * 40)) / 40)) * np.exp(-kt * 30)
    for s in range(0, n - hit, int(0.5 * SR)):
        x[s:s + hit] += 0.5 * kick
    y = np.stack([x, 0.95 * np.roll(x, 7)], axis=1)
    y *= 10 ** (-6 / 20) / np.max(np.abs(y))
    return y.astype(np.float32)


@pytest.fixture(scope="session")
def clean_mix():
    """(audio, sr): 10 s of clean, music-like stereo, peak -6 dBFS.

    Sparse and very dynamic: -24.6 LUFS, peak-to-loudness 19.1 dB. The old
    engine fell 1.35 LU short of -9 LUFS on it, so tests ask it for "never
    louder than the target", not "reaches the target".
    """
    return _clean(), SR


@pytest.fixture(scope="session")
def dense_mix():
    """(audio, sr): 10 s of dense, sustained stereo.

    -19.5 LUFS, true peak -5.9 dBTP, peak-to-loudness 13.6 dB. Every
    Loudness target is reachable from it with a few dB of limiting: the old
    engine landed within 0.12 LU of each.
    """
    return _dense(), SR
