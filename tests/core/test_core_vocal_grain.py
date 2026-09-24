"""The voice de-noise (shimmer/core/repair/vocal_grain.py), the Vocal grain
card's fix.

What it must do, and what it must not (docs/GOALS.md, "Never damage the
music"): take out a grainy hiss that rides on a centred voice, touch
nothing below its band and nothing in the sides, change nothing at Amount
0, and render a preview window exactly as the same span of the full song.

Not tested here, because it needs real songs and a hearing model: its cost
on clean music, which sets the top of its Amount slider (CHAIN-AUDIT §6).
"""
import numpy as np
from scipy import signal as ss

from shimmer.core import Settings, Source, render
from shimmer.core.repair import vocal_grain

SR = 48000


def _band(y, lo, hi):
    sos = ss.butter(6, [lo, hi], btype="bandpass", fs=SR, output="sos")
    return ss.sosfiltfilt(sos, y, axis=0)


def _db(v):
    return 10.0 * np.log10(np.mean(np.asarray(v, dtype=np.float64) ** 2) + 1e-30)


def _song(seconds=8.0, seed=3):
    """A centred voice (220 Hz, harmonics to 3 kHz, phrases that come and
    go), a grainy hiss in 4-8 kHz that follows the voice, and a quiet wide
    pad so the song has real sides. Returns (song, voice, hiss)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ph = 2 * np.pi * np.cumsum(220.0 * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * t))) / SR
    voice = sum((1.0 / h) * np.sin(h * ph) for h in range(1, 14))
    phrase = 0.55 + 0.45 * np.sin(2 * np.pi * 0.4 * t)
    voice = 0.2 * phrase * voice / np.max(np.abs(voice))
    grain = _band(rng.standard_normal(n) * (rng.random(n) < 0.3), 4000.0, 8000.0)
    hiss = 0.02 * phrase * grain / np.std(grain)
    pad = _band(rng.standard_normal((n, 2)), 150.0, 2500.0)
    song = (voice + hiss)[:, None] + 0.01 * pad / np.std(pad)
    r = int(0.02 * SR)
    song[:r] *= np.linspace(0.0, 1.0, r)[:, None]
    song[-r:] *= np.linspace(1.0, 0.0, r)[:, None]
    return song, voice, hiss


def _plan(song):
    return vocal_grain.plan(song, SR)


def test_amount_zero_changes_nothing():
    song, _, _ = _song()
    assert vocal_grain.apply(song, SR, _plan(song), 0.0) is song


def test_the_sides_are_never_touched():
    song, _, _ = _song()
    y = vocal_grain.apply(song, SR, _plan(song), 1.0)
    assert np.max(np.abs((y[:, 0] - y[:, 1]) - (song[:, 0] - song[:, 1]))) < 1e-9


def test_it_takes_the_hiss_and_leaves_the_voice_below_its_band():
    song, voice, hiss = _song()
    r = vocal_grain.removed(song, SR, _plan(song), 1.0)
    edge = int(0.2 * SR)
    hiss_band = _band(hiss, 4000.0, 8000.0)[edge:-edge]
    left = _band((song.mean(axis=1) - r), 4000.0, 8000.0)[edge:-edge]
    # At least half the hiss's power in 4-8 kHz is gone.
    assert _db(left) < _db(hiss_band) - 3.0
    # Below 2.5 kHz, where the voice is, it takes nothing.
    assert _db(_band(r, 60.0, 2500.0)[edge:-edge]) < _db(voice) - 80.0


def test_a_mono_song_works():
    song, _, _ = _song()
    mono = song[:, 0].copy()
    y = vocal_grain.apply(mono, SR, _plan(mono), 0.5)
    assert y.shape == mono.shape and not np.allclose(y, mono)


def test_a_preview_window_matches_the_full_render():
    song, _, _ = _song()
    src = Source.from_array(song, SR)
    s = Settings(fixes={"grain": 1.0}, auto=False, mastering=False, preserve_volume=False)
    full = render(src, s).audio
    part = render(src, s, window=(3.0, 5.0)).audio
    a, b = int(3.0 * SR), int(5.0 * SR)
    assert part.shape == full[a:b].shape
    assert np.max(np.abs(part - full[a:b])) < 1e-5


def test_the_render_reports_it():
    song, _, _ = _song(seconds=4.0)
    s = Settings(fixes={"grain": 0.5}, auto=False, mastering=False, preserve_volume=False)
    rep = render(Source.from_array(song, SR), s).report["fixes"]["grain"]
    assert rep["enabled"] and rep["tool"] == "voice_denoise" and rep["amount"] == 0.5
