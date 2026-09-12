"""The click and crackle models do what their docstrings say.

These pin the shape of the two models the de-clicker is judged against, so
a later edit cannot quietly make them easier (for example, by shaping every
click to the de-clicker's own 2 ms, above-2-kHz definition).
"""
import numpy as np

from shimmer import artifacts as A

SR = 48000
N = SR * 4


def _power_above(x, sr, hz):
    m = x.mean(axis=1)
    P = np.abs(np.fft.rfft(m)) ** 2
    f = np.fft.rfftfreq(len(m), 1 / sr)
    return float(P[f >= hz].sum() / max(P.sum(), 1e-30))


def test_clicks_are_repeatable_and_seeded():
    a = A.clicks(N, SR)
    assert np.array_equal(a, A.clicks(N, SR))
    assert not np.array_equal(a, A.clicks(N, SR, seed=99))
    assert a.shape == (N, 2) and a.dtype == np.float32


def test_clicks_are_sparse():
    a = A.clicks(N, SR)
    # A few clicks a second, each a few ms: almost every sample is near zero.
    busy = float(np.mean(np.abs(a).max(axis=1) > 0.05))
    assert 0.0 < busy < 0.02


def test_clicks_are_not_shaped_to_the_declicker():
    # The de-clicker only inspects above 2 kHz and only runs up to 2 ms.
    # The model must carry real energy below 2 kHz, or the test is circular.
    a = A.clicks(N, SR)
    below = 1.0 - _power_above(a, SR, 2000.0)
    assert below > 0.05


def test_crackle_follows_the_host():
    rng = np.random.default_rng(0)
    host = np.zeros((N, 2), dtype=np.float32)
    # Top-end activity in the first half only; silence after.
    host[: N // 2] = rng.standard_normal((N // 2, 2)).astype(np.float32) * 0.1
    c = A.crackle(N, SR, host)
    first = float(np.sum(c[: N // 2] ** 2))
    second = float(np.sum(c[N // 2 + SR // 10:] ** 2))
    assert first > 0.0
    assert second < 1e-3 * first


def test_make_passes_the_host_to_crackle():
    rng = np.random.default_rng(1)
    host = (rng.standard_normal((N, 2)) * 0.1).astype(np.float32)
    assert np.array_equal(A.make("crackle", N, SR, host=host), A.crackle(N, SR, host))
    assert "crackle" in A.NEEDS_HOST and "shadow" in A.NEEDS_HOST
