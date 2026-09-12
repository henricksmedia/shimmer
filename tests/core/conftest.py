"""Shared test signals for the contract tests of the new engine, shimmer.core.

The contract tests in this folder describe what the rebuilt engine must do
before it exists (docs/ARCHITECTURE.md §15 Step 3). Each file marks itself
"expected to fail" while shimmer.core is missing, strictly: if one of them
passed with no engine, it would be testing nothing, and that fails the run.
The moment shimmer.core exists the mark drops away and every test must pass.

The signals here are synthetic and seeded, so a test never depends on a file
that is not in the repo, and never builds its stimulus from the constant it
tests (PITFALLS.md, "Self-referential tests drift").
"""
import numpy as np
import pytest

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


@pytest.fixture(scope="session")
def clean_mix():
    """(audio, sr): 10 s of clean, music-like stereo, peak -6 dBFS."""
    return _clean(), SR


@pytest.fixture(scope="session")
def headroom_mix():
    """(audio, sr): the clean mix turned down to leave room for every
    Loudness target (peak -18 dBFS)."""
    y = _clean()
    y *= 10 ** (-12 / 20)
    return y.astype(np.float32), SR
