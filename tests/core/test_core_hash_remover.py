"""The hash remover (shimmer/core/repair/hash_remover.py), the Shimmer card's
candidate fix.

What it must do, and what it must not (docs/GOALS.md, "Never damage the
music"): give the trained network's gains, take modelled hash out, touch
nothing outside its band, put nothing before a hit, and render a preview
window exactly as the full song, at 48 kHz and at 44.1 kHz.

Whether it passes the Step 6 rule (removal on the models, cost on real
songs, side effects, a blind round) is measured by scripts/efficacy_harness.py
and written up in docs/STEP6-FIXES.md, not here.

Most of these need the network's weights (testing/masknet3.npz, kept out of
git for now); without them they are skipped, and the tool's own "does
nothing without its weights" is tested instead.
"""
import os

import numpy as np
import pytest
from scipy import signal as ss

from shimmer import artifacts
from shimmer.core import Settings, Source, render
from shimmer.core.repair import hash_remover

SR = 48000
PARITY = os.path.join(os.path.dirname(hash_remover.WEIGHTS), "masknet3_parity.npz")

needs_weights = pytest.mark.skipif(not hash_remover.available(),
                                   reason="the network's weights are not here")


def _song(seconds=6.0, sr=SR, seed=1):
    """A small mix: a centred chord with harmonics to 8 kHz, a wide pad, and
    a bright hi-hat every eighth note, so there is real top end for the
    network to leave alone."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    chord = sum((0.5 / h) * np.sin(2 * np.pi * f * h * t)
                for f in (196.0, 247.0, 294.0) for h in range(1, 30) if f * h < 8000.0)
    chord = 0.2 * chord / np.max(np.abs(chord))
    pad = ss.sosfilt(ss.butter(2, [200.0, 3000.0], btype="bandpass", fs=sr, output="sos"),
                     rng.standard_normal((n, 2)), axis=0)
    hat = np.zeros((n, 2))
    L = int(0.04 * sr)
    for s0 in range(int(0.1 * sr), n - L, int(0.25 * sr)):
        hit = rng.standard_normal(L) * np.exp(-np.linspace(0.0, 8.0, L))
        hat[s0:s0 + L] += hit[:, None]
    hat = 0.08 * ss.sosfilt(ss.butter(4, 7000.0, btype="highpass", fs=sr, output="sos"), hat, axis=0)
    y = chord[:, None] + 0.03 * pad + hat
    r = int(0.02 * sr)
    y[:r] *= np.linspace(0.0, 1.0, r)[:, None]
    y[-r:] *= np.linspace(1.0, 0.0, r)[:, None]
    return y


def _band(x, lo, hi, sr=SR):
    sos = ss.butter(4, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return ss.sosfiltfilt(sos, np.asarray(x, dtype=np.float64), axis=0)


def _db(e):
    return 10.0 * np.log10(max(float(e), 1e-30))


def _run(x, amount=1.0, sr=SR):
    return hash_remover.apply(x, sr, hash_remover.plan(x, sr), amount)


@needs_weights
@pytest.mark.skipif(not os.path.exists(PARITY), reason="no saved torch output to compare")
def test_it_gives_the_trained_networks_gains():
    """The same gains as the network run in torch (scripts/hash_learn), on a
    real song's spectrogram saved from it."""
    with np.load(PARITY) as z:
        lm, mean, ref = z["lm"], float(z["mean"]), z["g"]
    net = hash_remover._net()
    g = hash_remover._mask((lm - mean).astype(np.float32), net)
    band = net["band"] > 0
    assert float(np.abs(g - ref)[band].max()) < 1e-4


@needs_weights
def test_a_long_song_in_pieces_gets_the_same_gains(monkeypatch):
    """The network runs CHUNK frames at a time with a HALO either side; the
    pieces must join into what one pass over the whole would give."""
    rng = np.random.default_rng(2)
    net = hash_remover._net()
    lm = rng.standard_normal((net["band"].size, 300)).astype(np.float32)
    whole = hash_remover._mask(lm, net)
    monkeypatch.setattr(hash_remover, "CHUNK", 70)
    pieces = hash_remover._gains(lm, net)
    band = net["band"] > 0
    assert float(np.abs(pieces - whole)[band].max()) < 1e-5


@needs_weights
def test_it_takes_modelled_hash_out():
    """The broadband hash measured on a real Suno song (artifacts.hash_wide):
    what is left of it after the fix is at least 2 dB down."""
    x = _song()
    h = artifacts.make("hash_wide", x.shape[0], SR).astype(np.float64)
    h *= 0.05 / np.max(np.abs(h))
    y, y0 = _run(x + h), _run(x)
    before = _db(np.sum(_band(h, 1500, 16000) ** 2))
    after = _db(np.sum(_band(y - y0, 1500, 16000) ** 2))
    assert before - after > 2.0, (before, after)


@needs_weights
def test_amount_sets_how_far():
    x = _song()
    x = x + 0.02 * artifacts.make("hash_wide", x.shape[0], SR)
    e = [_db(np.sum((x - _run(x, a)) ** 2)) for a in (0.25, 0.5, 1.0)]
    assert e[0] < e[1] < e[2]


@needs_weights
def test_nothing_below_its_band_moves():
    x = _song()
    x = x + 0.02 * artifacts.make("hash_wide", x.shape[0], SR)
    y = _run(x)
    lo_x, lo_y = _band(x, 60, 1000), _band(y, 60, 1000)
    assert _db(np.sum((lo_y - lo_x) ** 2)) - _db(np.sum(lo_x ** 2)) < -40.0


@needs_weights
def test_nothing_comes_before_a_hit():
    """A bright hit after silence: the fix only takes away, so nothing may
    appear more than one frame (21 ms) before it."""
    x = np.zeros((2 * SR, 2))
    t0 = SR
    L = int(0.05 * SR)
    hit = _band(np.random.default_rng(3).standard_normal(L), 2000, 14000) * np.exp(
        -np.linspace(0.0, 6.0, L))
    x[t0:t0 + L] = (0.5 * hit / np.max(np.abs(hit)))[:, None]
    x[t0:t0 + L, 1] *= 0.7
    y = _run(x)
    early = float(np.abs(y[:t0 - int(0.022 * SR)]).max())
    assert 20.0 * np.log10(max(early, 1e-12) / 0.5) <= -60.0


@pytest.mark.parametrize("sr", [48000, 44100])
@needs_weights
def test_the_preview_is_the_export_on_a_window(sr):
    x = _song(4.0, sr) + 0.02 * artifacts.make("hash_wide", int(4.0 * sr), sr)
    src = Source.from_array(x.astype(np.float32), sr)
    s = Settings(fixes={"shimmer": 1.0}, auto=False, mastering=False, preserve_volume=False)
    full = render(src, s).audio
    assert float(np.abs(full - x.astype(np.float32)).max()) > 1e-3     # it acted
    for w in ((0.0, 1.5), (1.337, 3.211), (2.5, 4.0)):
        part = render(src, s, window=w).audio
        a = int(round(w[0] * sr))
        ref = full[a:a + part.shape[0]]
        res = 10 * np.log10(np.sum((part - ref) ** 2.0) / np.sum(ref ** 2.0) + 1e-30)
        assert res < -60.0, (w, res)


@needs_weights
def test_render_reports_it():
    x = _song(3.0)
    src = Source.from_array(x.astype(np.float32), SR)
    r = render(src, Settings(fixes={"shimmer": 0.5}, auto=False, mastering=False,
                             preserve_volume=False))
    rep = r.report["fixes"]["shimmer"]
    assert rep["enabled"] and rep["tool"] == "hash_remover" and rep["amount"] == 0.5


@needs_weights
def test_a_mono_song_works():
    x = _song(3.0) + 0.02 * artifacts.make("hash_wide", 3 * SR, SR)
    y = _run(x[:, :1])
    assert y.shape == (x.shape[0], 1) and float(np.abs(y - x[:, :1]).max()) > 1e-3
    y1 = _run(x[:, 0])
    assert y1.shape == (x.shape[0],) and np.allclose(y1, y[:, 0])


@needs_weights
def test_a_new_amount_reuses_the_songs_gains(monkeypatch):
    """The network runs once per song, in plan(); a window or a new Amount
    only applies the kept gains."""
    x = _song(3.0) + 0.02 * artifacts.make("hash_wide", 3 * SR, SR)
    p = hash_remover.plan(x, SR)
    assert len(p.gains) == 2

    def no_second_pass(*a, **k):
        raise AssertionError("the network ran again")
    monkeypatch.setattr(hash_remover, "_gains", no_second_pass)
    for amount in (0.3, 1.0):
        assert float(np.abs(hash_remover.apply(x, SR, p, amount) - x).max()) > 1e-4
    hash_remover.apply(x[SR:2 * SR], SR, p, 0.5, offset=SR)


def test_bypass_is_bit_exact():
    x = _song(2.0)
    assert hash_remover.apply(x, SR, hash_remover.plan(x, SR), 0.0) is x


def test_without_its_weights_it_does_nothing(monkeypatch):
    monkeypatch.setattr(hash_remover, "WEIGHTS", os.path.join(os.path.dirname(__file__), "no-such.npz"))
    x = _song(2.0)
    p = hash_remover.plan(x, SR)
    assert p.mean_lm == ()
    assert hash_remover.apply(x, SR, p, 1.0) is x
    assert hash_remover.summary(p, 1.0)["available"] is False
