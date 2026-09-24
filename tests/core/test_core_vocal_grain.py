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
    r = vocal_grain.removed(song, SR, _plan(song), 1.0)[:, 0]
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


# ── Vocal only: the fix on the split-out vocal ──────────────────────────

def _cymbal(n, seed=9):
    """A steady, centred hiss in 4-8 kHz that is not part of the voice (a
    ride cymbal, say), for the vocal-only mode to leave alone."""
    rng = np.random.default_rng(seed)
    c = _band(rng.standard_normal(n), 4000.0, 8000.0)
    return 0.01 * c / np.std(c)


def test_vocal_mode_takes_from_the_vocal_and_leaves_the_cymbal():
    song, voice, hiss = _song()
    cym = _cymbal(song.shape[0])
    mix = song + cym[:, None]
    vocal = np.repeat((voice + hiss)[:, None], 2, axis=1)
    p = vocal_grain.plan(mix, SR, vocal=vocal)
    assert p.mode == "vocal" and len(p.cut_db) == 2
    r = vocal_grain.removed(mix, SR, p, 1.0)
    edge = int(0.2 * SR)
    # What it takes is the vocal's own hiss, with none of the cymbal in it:
    # it lines up with the hiss, not with the cymbal.
    took = _band(r[:, 0], 4000.0, 8000.0)[edge:-edge]
    h = hiss[edge:-edge]
    c = cym[edge:-edge]
    assert abs(np.dot(took, c)) / (np.linalg.norm(took) * np.linalg.norm(c)) < 0.05
    assert np.dot(took, h) / (np.linalg.norm(took) * np.linalg.norm(h)) > 0.3


def test_vocal_mode_window_matches_the_full_song():
    song, voice, hiss = _song()
    vocal = np.repeat((voice + hiss)[:, None], 2, axis=1)
    p = vocal_grain.plan(song, SR, vocal=vocal)
    full = vocal_grain.apply(song, SR, p, 0.8)
    # A lead-in and a tail, as render() gives a preview window.
    a, b, lead, tail = int(3.0 * SR), int(5.0 * SR), int(1.0 * SR), int(0.5 * SR)
    part = vocal_grain.apply(song[a - lead:b + tail], SR, p, 0.8, offset=a - lead)
    assert np.max(np.abs(part[lead:lead + b - a] - full[a:b])) < 1e-6


def test_vocal_mode_without_a_file_falls_back_to_the_centre_and_says_so():
    song, _, _ = _song(seconds=4.0)
    s = Settings(fixes={"grain": 0.5}, fix_modes={"grain": "vocal"}, auto=False,
                 mastering=False, preserve_volume=False)
    rep = render(Source.from_array(song, SR), s).report["fixes"]["grain"]
    assert rep["mode"] == "centre" and "no file" in rep["note"]


def test_the_mode_is_kept_and_checked_in_settings():
    s = Settings(fix_modes={"grain": "vocal", "sibilance": "vocal", "nope": "x"})
    assert s.fix_modes == {"grain": "vocal"}
    assert Settings.from_dict(s.to_dict()).fix_modes == {"grain": "vocal"}
    # The default mode, or one the card does not have, is not stored.
    assert Settings(fix_modes={"grain": "centre"}).fix_modes == {}
    assert Settings(fix_modes={"grain": "sideways"}).fix_modes == {}
