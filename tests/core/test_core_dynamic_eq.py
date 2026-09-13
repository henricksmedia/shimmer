"""The dynamic EQ (shimmer/core/repair/dynamic_eq.py), the Harshness and
Low-mid build-up cards' fix.

What it must do, and what it must not (docs/GOALS.md, "Never damage the
music"): find a resonance that rides the music, take it down while it is
loud, leave quiet stretches and far-off bands alone, put nothing before a
hit, keep the stereo image, and render a preview window exactly as the
full song.

The resonances come from shimmer/artifacts.py (random centres in the band,
the music's own content through a resonance), not from this tool's finder.
"""
import numpy as np
import pytest
from scipy import signal as ss

from shimmer import artifacts
from shimmer.core import Settings, Source, render
from shimmer.core.repair import dynamic_eq as DQ

SR = 48000


def _music(seconds=6.0, seed=0):
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
        for h in range(1, 13):
            x[s:e] += (0.25 / h) * env * np.sin(2 * np.pi * f0 * h * t)
        x[s:e] += 0.3 * env * np.sin(2 * np.pi * f0 / 4.0 * t)
    hit = int(0.03 * SR)
    for s in range(0, n - hit, int(0.25 * SR)):
        x[s:s + hit] += 0.5 * rng.standard_normal(hit) * np.exp(-np.linspace(0, 6, hit))
    amb = ss.sosfilt(ss.butter(2, [200.0, 8000.0], btype="bandpass", fs=SR, output="sos"),
                     rng.standard_normal((n, 2)), axis=0)
    y = np.stack([x, x], axis=1) + 0.05 * amb
    return y * 10 ** (-6 / 20) / np.max(np.abs(y))


def _planted(card, host, level=0.7):
    a = artifacts.make(card, host.shape[0], SR, host=host).astype(np.float64)
    return host + level * float(np.max(np.abs(host))) * a


def _centres(card):
    """The model's own centres, from its seed (shimmer/artifacts.py)."""
    if card == "harshness":
        rng = np.random.default_rng(9)
        return sorted(np.exp(rng.uniform(np.log(2000.0), np.log(5000.0), 2)))
    rng = np.random.default_rng(10)
    return [float(np.exp(rng.uniform(np.log(200.0), np.log(500.0))))]


def _band(x, f, width_oct=1 / 3):
    lo, hi = f / 2 ** (width_oct / 2), f * 2 ** (width_oct / 2)
    sos = ss.butter(4, [lo, hi], btype="bandpass", fs=SR, output="sos")
    return ss.sosfiltfilt(sos, np.asarray(x, dtype=np.float64), axis=0)


def _db(e):
    return 10.0 * np.log10(max(float(e), 1e-30))


TOOLS = {"harshness": DQ.HARSHNESS, "mud": DQ.MUD}


@pytest.mark.parametrize("card,within_oct", [("harshness", 0.25), ("mud", 0.4)])
def test_it_finds_a_planted_resonance(card, within_oct):
    """Close enough that the cut covers the resonance's peak: within about
    half its own bell's width (Q 3: a quarter octave; Q 1.4: 0.4 octave)."""
    x = _planted(card, _music())
    found = TOOLS[card].plan(x, SR).centres_hz
    assert found
    for f in _centres(card)[:1]:
        assert min(abs(np.log2(f / g)) for g in found) <= within_oct, (f, found)


@pytest.mark.parametrize("card", ["harshness", "mud"])
def test_it_takes_the_resonance_down(card):
    tool = TOOLS[card]
    x = _planted(card, _music())
    p = tool.plan(x, SR)
    y = tool.apply(x, SR, p, 1.0)
    f = p.centres_hz[0]
    assert _db(np.sum(_band(x, f) ** 2)) - _db(np.sum(_band(y, f) ** 2)) > 1.0


@pytest.mark.parametrize("card", ["harshness", "mud"])
def test_quiet_stretches_are_left_alone(card):
    tool = TOOLS[card]
    x = _planted(card, _music())
    half = x.shape[0] // 2
    x[half:] *= 0.05                      # the second half 26 dB down
    y = tool.apply(x, SR, tool.plan(x, SR), 1.0)
    q = slice(half + int(0.3 * SR), x.shape[0] - int(0.05 * SR))
    assert _db(np.sum((y - x)[q] ** 2)) - _db(np.sum(x[q] ** 2)) < -60.0


@pytest.mark.parametrize("card,far", [("harshness", (60.0, 800.0)), ("mud", (2000.0, 16000.0))])
def test_nothing_far_outside_the_band_moves(card, far):
    tool = TOOLS[card]
    x = _planted(card, _music())
    y = tool.apply(x, SR, tool.plan(x, SR), 1.0)
    sos = ss.butter(4, list(far), btype="bandpass", fs=SR, output="sos")
    fx, fy = ss.sosfiltfilt(sos, x, axis=0), ss.sosfiltfilt(sos, y, axis=0)
    assert _db(np.sum((fy - fx) ** 2)) - _db(np.sum(fx ** 2)) < -40.0


@pytest.mark.parametrize("card", ["harshness", "mud"])
def test_nothing_comes_before_a_hit(card):
    """A loud hit at the found band after a quiet stretch: nothing the cut
    changes may reach more than 20 ms before it (-60 dB)."""
    tool = TOOLS[card]
    p = tool.plan(_planted(card, _music()), SR)
    f = p.centres_hz[0]
    n, t0 = 2 * SR, SR
    rng = np.random.default_rng(5)
    L = int(0.1 * SR)
    hit = _band(rng.standard_normal(L), f, 0.5) * np.exp(-np.linspace(0, 4, L))
    x = np.zeros((n, 2))
    x[:, :] = 1e-3 * _band(rng.standard_normal((n, 2)), f, 2.0)
    x[t0:t0 + L] += (0.5 * hit / np.max(np.abs(hit)))[:, None]
    y = tool.apply(x, SR, p, 1.0)
    d = np.abs(y - x)
    assert float(d.max()) > 1e-4                       # it did act on the hit
    early = float(d[:t0 - int(0.020 * SR)].max())
    assert 20.0 * np.log10(max(early, 1e-15) / float(np.abs(x).max())) <= -60.0


@pytest.mark.parametrize("card", ["harshness", "mud"])
def test_both_channels_get_the_same_cut(card):
    tool = TOOLS[card]
    x = _planted(card, _music())[:, :1]
    x = np.concatenate([x, 0.5 * x], axis=1)
    y = tool.apply(x, SR, tool.plan(x, SR), 1.0)
    assert not np.allclose(y, x)
    assert np.allclose(y[:, 1], 0.5 * y[:, 0], atol=1e-12)


@pytest.mark.parametrize("card", ["harshness", "mud"])
def test_the_preview_is_the_export_on_a_window(card):
    x = _planted(card, _music()).astype(np.float32)
    src = Source.from_array(x, SR)
    s = Settings(fixes={card: 1.0}, auto=False, mastering=False, preserve_volume=False)
    full = render(src, s).audio
    for w in ((0.0, 2.0), (1.337, 3.911), (4.5, 6.0)):
        part = render(src, s, window=w).audio
        a = int(round(w[0] * SR))
        ref = full[a:a + part.shape[0]]
        res = 10 * np.log10(np.sum((part - ref) ** 2.0) / np.sum(ref ** 2.0) + 1e-30)
        assert res < -60.0, (card, w, res)


def test_render_reports_it():
    x = _planted("harshness", _music()).astype(np.float32)
    r = render(Source.from_array(x, SR), Settings(fixes={"harshness": 0.5}, auto=False,
                                                   mastering=False, preserve_volume=False))
    rep = r.report["fixes"]["harshness"]
    assert rep["tool"] == "dynamic_eq" and rep["centres_hz"]
    assert rep["max_cut_db"] == round(DQ.HARSHNESS.cfg.max_cut_db * 0.5, 1)


@pytest.mark.parametrize("card", ["harshness", "mud"])
def test_bypass_and_nothing_to_find(card):
    tool = TOOLS[card]
    x = _planted(card, _music())
    assert tool.apply(x, SR, tool.plan(x, SR), 0.0) is x
    # Plain noise has no resonance: nothing found, nothing changed.
    noise = np.random.default_rng(2).standard_normal((4 * SR, 2)) * 0.1
    p = tool.plan(noise, SR)
    assert p.centres_hz == () and tool.apply(noise, SR, p, 1.0) is noise
