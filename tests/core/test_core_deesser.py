"""The de-esser (shimmer/core/repair/deesser.py), the Sibilance card's fix.

What it must do, and what it must not (docs/GOALS.md, "Never damage the
music"): take the consonants down, leave the song alone between them, touch
nothing outside its band, put nothing before a hit, keep a wide cymbal
wide, and render a preview window exactly as the full song.

The consonants come from shimmer/artifacts.py, built from the complaint
("s", "sh", "t", "ch" at their own pitches), not from this tool's detector.
"""
import numpy as np
import pytest
from scipy import signal as ss

from shimmer import artifacts
from shimmer.core import Settings, Source, render
from shimmer.core.repair import deesser

SR = 48000


def _vowels(seconds=6.0, seed=1):
    """A sung line: a centred voice at 180-260 Hz with harmonics to 4 kHz
    falling 6 dB an octave and a little vibrato, over a quiet wide pad and a
    faint wide air band, so the song has real sides."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    f0 = 220.0 * (1.0 + 0.1 * np.sin(2 * np.pi * 0.3 * t)) * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * t))
    ph = 2 * np.pi * np.cumsum(f0) / SR
    v = sum((1.0 / h) * np.sin(h * ph) for h in range(1, 19))
    v = 0.25 * v / np.max(np.abs(v))
    pad = ss.sosfilt(ss.butter(2, [150.0, 2500.0], btype="bandpass", fs=SR, output="sos"),
                     rng.standard_normal((n, 2)), axis=0)
    air = ss.sosfilt(ss.butter(2, [4000.0, 12000.0], btype="bandpass", fs=SR, output="sos"),
                     rng.standard_normal((n, 2)), axis=0)
    y = v[:, None] + 0.02 * pad + 0.002 * air
    # Fade in and out: a voice that starts at full level on its first sample
    # is a click, and a click is what a de-esser is for.
    r = int(0.02 * SR)
    y[:r] *= np.linspace(0.0, 1.0, r)[:, None]
    y[-r:] *= np.linspace(1.0, 0.0, r)[:, None]
    return y


def test_a_dark_voice_alone_is_left_alone():
    """No consonants: a dark voice whose top harmonics move with its vibrato
    is not sibilance, however far they move against its usual level."""
    v = _vowels()
    edge = int(0.05 * SR)
    assert float(np.abs(_run(v) - v)[edge:-edge].max()) < 1e-9


def _song(level_db=-6.0):
    v = _vowels()
    c = artifacts.consonants(v.shape[0], SR).astype(np.float64)
    c *= 10.0 ** (level_db / 20.0) * np.max(np.abs(v)) / np.max(np.abs(c))
    return v, c, v + c


def _band(x, lo, hi):
    sos = ss.butter(4, [lo, hi], btype="bandpass", fs=SR, output="sos")
    return ss.sosfiltfilt(sos, np.asarray(x, dtype=np.float64), axis=0)


def _db(e):
    return 10.0 * np.log10(max(float(e), 1e-30))


def _run(x, amount=1.0):
    return deesser.apply(x, SR, deesser.plan(x, SR), amount)


def test_it_takes_the_consonants_down():
    v, c, x = _song()
    y = _run(x)
    # What is left of the consonants: the output less what the voice alone
    # comes out as. At full Amount they lose at least 4 dB.
    yv = _run(v)
    before = _db(np.sum(_band(c, 4500, 10000) ** 2))
    after = _db(np.sum(_band(y - yv, 4500, 10000) ** 2))
    assert before - after > 4.0, (before, after)


def test_amount_sets_how_far():
    _, c, x = _song()
    e = [_db(np.sum(_band(x - _run(x, a), 4500, 10000) ** 2)) for a in (0.25, 0.5, 1.0)]
    assert e[0] < e[1] < e[2]


def test_it_leaves_the_song_alone_between_consonants():
    _, c, x = _song()
    y = _run(x)
    busy = ndi_dilate(np.abs(c).max(axis=1) > 1e-6, int(0.1 * SR))
    quiet = ~busy
    assert quiet.sum() > SR
    diff = _db(np.sum((y - x)[quiet] ** 2)) - _db(np.sum(x[quiet] ** 2))
    assert diff < -60.0, diff


def ndi_dilate(mask, k):
    from scipy import ndimage
    return ndimage.binary_dilation(mask, iterations=1, structure=np.ones(2 * k + 1, dtype=bool))


def test_nothing_below_its_band_moves():
    _, _, x = _song(level_db=-6.0)
    y = _run(x)
    lo_x, lo_y = _band(x, 100, 2500), _band(y, 100, 2500)
    assert _db(np.sum((lo_y - lo_x) ** 2)) - _db(np.sum(lo_x ** 2)) < -30.0


def test_nothing_comes_before_a_hit():
    """A sharp, bright "t" after a stretch of voice: nothing the de-esser
    changes may reach more than 20 ms before it (-60 dB)."""
    v = _vowels(2.0)
    t0 = SR
    rng = np.random.default_rng(3)
    L = int(0.03 * SR)
    hit = _band(rng.standard_normal(L), 5000, 9000) * np.exp(-np.linspace(0, 5, L))
    x = v.copy()
    x[t0:t0 + L] += (0.5 * hit / np.max(np.abs(hit)))[:, None]
    y = _run(x)
    d = np.abs(y - x)
    assert float(d.max()) > 1e-3                       # it did act on the hit
    early = float(d[:t0 - int(0.020 * SR)].max())
    assert 20.0 * np.log10(max(early, 1e-12) / float(np.abs(x).max())) <= -60.0


def test_a_wide_cymbal_is_left_alone():
    """Bright bursts only in the sides (left = -right): the centre has no
    consonant, so nothing is cut."""
    v = _vowels()
    rng = np.random.default_rng(4)
    burst = np.zeros(v.shape[0])
    for s0 in range(SR // 2, v.shape[0] - SR // 10, SR // 2):
        burst[s0:s0 + SR // 20] = rng.standard_normal(SR // 20)
    burst = 0.2 * _band(burst, 5000, 12000)
    x = v + np.stack([burst, -burst], axis=1)
    # The fade-in's first corner is itself a tiny click; judge the song
    # between its first and last 50 ms.
    edge = int(0.05 * SR)
    assert float(np.abs(_run(x) - x)[edge:-edge].max()) < 1e-9


def test_the_sides_get_half_the_cut():
    v, c, _ = _song(level_db=-6.0)
    # The voice's own top would water down the centre's measured cut; take
    # it away, so the band holds the consonants and the faint wide air.
    x = ss.sosfiltfilt(ss.butter(6, 3000.0, fs=SR, output="sos"), v, axis=0)
    x += 0.002 * _band(np.random.default_rng(9).standard_normal(x.shape), 4000, 12000)
    # Mostly centred, a little to the left: the sides carry some of them.
    x[:, 0] += c[:, 0]
    x[:, 1] += 0.6 * c[:, 1]
    y = _run(x)
    m = lambda a: 0.5 * (a[:, 0] + a[:, 1])
    s = lambda a: 0.5 * (a[:, 0] - a[:, 1])
    cut_m = _db(np.sum(_band(m(x), 4500, 10000) ** 2)) - _db(np.sum(_band(m(y), 4500, 10000) ** 2))
    cut_s = _db(np.sum(_band(s(x), 4500, 10000) ** 2)) - _db(np.sum(_band(s(y), 4500, 10000) ** 2))
    assert cut_m > 1.0 and 0.25 < cut_s / cut_m < 0.75, (cut_m, cut_s)


def test_a_mono_song_works():
    _, _, x = _song()
    y = deesser.apply(x[:, :1], SR, deesser.plan(x[:, :1], SR), 1.0)
    assert y.shape == (x.shape[0], 1) and float(np.abs(y - x[:, :1]).max()) > 1e-3


def test_the_preview_is_the_export_on_a_window():
    _, _, x = _song()
    src = Source.from_array(x.astype(np.float32), SR)
    s = Settings(fixes={"sibilance": 1.0}, auto=False, mastering=False, preserve_volume=False)
    full = render(src, s).audio
    for w in ((0.0, 2.0), (1.337, 3.911), (4.5, 6.0)):
        part = render(src, s, window=w).audio
        a = int(round(w[0] * SR))
        ref = full[a:a + part.shape[0]]
        res = 10 * np.log10(np.sum((part - ref) ** 2.0) / np.sum(ref ** 2.0) + 1e-30)
        assert res < -60.0, (w, res)


def test_render_reports_it_and_the_removed_track_holds_the_consonants():
    _, c, x = _song()
    src = Source.from_array(x.astype(np.float32), SR)
    r = render(src, Settings(fixes={"sibilance": 0.5}, auto=False, mastering=False,
                             preserve_volume=False), with_removed=True)
    rep = r.report["fixes"]["sibilance"]
    assert rep["enabled"] and rep["tool"] == "deesser"
    assert rep["max_cut_db"] == round(deesser.MAX_CUT_DB * 0.5, 1)
    removed = _band(r.removed, 4500, 10000)
    assert float(np.corrcoef(removed[:, 0], _band(c, 4500, 10000)[:, 0])[0, 1]) > 0.5


def test_bypass_is_bit_exact():
    _, _, x = _song()
    assert deesser.apply(x, SR, deesser.plan(x, SR), 0.0) is x
