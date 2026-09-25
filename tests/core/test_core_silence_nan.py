"""Digital silence never turns a fix's output into NaN.

The de-esser and the dynamic EQ read a running mean of squares in dB. In
exact silence that mean can round a hair below zero, and its log was NaN:
on one library song the de-esser wrote NaN into the audio. Found by the
Sibilance detector, which runs the de-esser on every song."""
import numpy as np
import pytest

from shimmer.core import Settings, Source, render

SR = 48000


def _song_with_silences():
    rng = np.random.default_rng(3)
    x = np.zeros(int(12 * SR))
    for s in range(0, x.size, 3 * SR):
        n = int(1.5 * SR)
        t = np.arange(n) / SR
        x[s:s + n] = 0.3 * np.sin(2 * np.pi * 330 * t) + 0.05 * rng.standard_normal(n)
    # A lone large sample right before exact zeros is what makes the running
    # mean round below zero.
    x[int(1.5 * SR)] = 0.9
    return np.stack([x, 0.8 * x], axis=1).astype(np.float32)


@pytest.mark.parametrize("card", ["sibilance", "harshness", "mud"])
def test_silence_stays_finite(card):
    src = Source.from_array(_song_with_silences(), SR)
    r = render(src, Settings(auto=False, fixes={card: 1.0, "tones": 0.0}, mastering=False,
                             preserve_volume=False), with_removed=True)
    assert np.isfinite(r.audio).all()
    assert np.isfinite(r.removed).all()


@pytest.mark.parametrize("module", ["deesser", "dynamic_eq"])
def test_the_level_never_turns_nan(module):
    # Loud samples, then exact silence: the running mean of squares rounds
    # to -3e-16 here, and the old log of it was NaN.
    import importlib
    mod = importlib.import_module(f"shimmer.core.repair.{module}")
    rng = np.random.default_rng(3)
    y = np.concatenate([rng.standard_normal(5000) * 0.7, np.zeros(5000)])
    assert np.isfinite(mod._level_db(y, SR)).all()

