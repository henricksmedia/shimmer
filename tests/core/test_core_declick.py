"""The de-click (shimmer/core/repair/declick.py), the Clicks and crackle
card's fix, rebuilt.

1.x's de-clicker took drum hits for clicks (450-870 found per 8 s clip with
about 12 planted), left the pops' energy where it was, and took 0.10 sones
of music (docs/HANDOFF-CHECKLIST.md item 17). This one must find the pops,
fill them from the sound on both sides, and leave drum hits and clean music
alone.
"""
import numpy as np
import pytest
from scipy import signal as ss

from shimmer.core import Settings, Source, render
from shimmer.core.repair import declick as DC

SR = 48000


def _music(seconds=4.0, seed=0, drums=False):
    """Chords that change every half second over a bass and a faint noise
    floor; with `drums`, noise-burst hits every quarter second. Stereo."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    x = np.zeros(n)
    step = int(0.5 * SR)
    for i in range(n // step + 1):
        s, e = i * step, min(n, (i + 1) * step)
        t = np.arange(e - s) / SR
        f0 = 220.0 * 2 ** (rng.integers(0, 12) / 12.0)
        env = 0.6 + 0.4 * np.exp(-2.0 * t)
        for h in range(1, 9):
            x[s:e] += (0.2 / h) * env * np.sin(2 * np.pi * f0 * h * t + h)
        x[s:e] += 0.25 * np.sin(2 * np.pi * f0 / 4.0 * t)
    if drums:
        hit = int(0.03 * SR)
        for s in range(int(0.1 * SR), n - hit, int(0.25 * SR)):
            x[s:s + hit] += 0.6 * rng.standard_normal(hit) * np.exp(-np.linspace(0, 6, hit))
    x += 1e-3 * rng.standard_normal(n)
    r = int(0.02 * SR)
    x[:r] *= np.linspace(0.0, 1.0, r)
    y = np.stack([x, 0.9 * x], axis=1)
    return y * 10 ** (-6 / 20) / np.max(np.abs(y))


POPS_S = (0.61, 1.23, 1.97, 2.64, 3.33)


def _pops(x, times=POPS_S, level=0.4, ms=0.8, seed=3):
    """Short decaying bursts at `times`, in both channels (right at 0.8)."""
    rng = np.random.default_rng(seed)
    p = np.zeros_like(x)
    L = max(2, int(ms * 1e-3 * SR))
    for t in times:
        i = int(t * SR)
        b = rng.standard_normal(L) * np.exp(-np.linspace(0.0, 4.0, L))
        b *= level * float(np.max(np.abs(x))) / float(np.max(np.abs(b)))
        p[i:i + L, 0] += b
        p[i:i + L, 1] += 0.8 * b
    return p


def test_it_finds_the_pops():
    x = _music()
    spans = DC.find((x + _pops(x))[:, 0], SR, 1.0)
    for t in POPS_S:
        i = int(t * SR)
        assert any(s <= i + 4 and e >= i for s, e in spans), (t, spans)
    assert len(spans) <= len(POPS_S) + 1, spans


NOT_PASSING = pytest.mark.xfail(
    strict=True, reason="The de-click does not pass yet: it misses most moderate pops in "
                        "dense music (docs/STEP6-FIXES.md).")


def test_it_fills_them_from_both_sides():
    """Each pop's top band is replaced by a fill from the music on both
    sides: the pops must lose at least 3 dB overall, most of them 5 dB or
    more, and none may come out louder. Steady chords over a strong bass are
    the hardest case for a fill; filling only above 2 kHz keeps the bass."""
    x = _music()
    p = _pops(x)
    y = DC.apply(x + p, SR, DC.plan(x + p, SR), 1.0)
    removed, pe_all, left_all = [], 0.0, 0.0
    for t in POPS_S:
        i = int(t * SR)
        w = slice(i - 48, i + 96)
        pe, left = float(np.sum(p[w] ** 2)), float(np.sum((y[w] - x[w]) ** 2))
        removed.append(10 * np.log10(pe / max(left, 1e-12)))
        pe_all, left_all = pe_all + pe, left_all + left
    assert 10 * np.log10(pe_all / left_all) > 3.0, removed
    assert sum(r >= 5.0 for r in removed) >= 3, removed
    assert min(removed) > -1.0, removed


def test_a_click_length_gap_in_a_tone_is_filled_cleanly():
    """A 20-sample gap (0.4 ms, a typical click) in two steady tones comes
    back within -40 dB (measured: -63 dB)."""
    t = np.arange(SR // 10) / SR
    true = 0.5 * np.sin(2 * np.pi * 1000.0 * t) + 0.2 * np.sin(2 * np.pi * 2700.0 * t)
    x = true.copy()
    s, e = 2000, 2020
    x[s:e] = 0.0
    DC._fill(x, s, e, SR)
    err = float(np.sum((x[s:e] - true[s:e]) ** 2)) / float(np.sum(true[s:e] ** 2))
    assert 10 * np.log10(err) < -40.0


@NOT_PASSING
def test_it_finds_most_pops_in_a_dense_real_song():
    """Five pops planted at known times in six seconds of "Hey", a bright,
    dense master, at 30 % of its peak, with their bass taken out as in the
    pop model (shimmer/artifacts.py): at least 4 of the 5 found on each
    channel, and their energy at least halved."""
    import os
    import soundfile as sf
    path = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "reference",
                        "reference-hey.wav")
    if not os.path.exists(path):
        pytest.skip("reference-hey.wav is not in this checkout")
    x0, sr = sf.read(path, always_2d=True, dtype="float32")
    x = x0[int(40 * sr):int(46 * sr)].astype(np.float64)
    art = _pops(x, level=0.3)
    art = ss.sosfilt(ss.butter(2, 200.0, btype="highpass", fs=sr, output="sos"), art, axis=0)
    xp = x + art
    for c in range(2):
        spans = DC.find(xp[:, c], sr, 1.0)
        hit = sum(any(s <= int(t * sr) + 40 and e >= int(t * sr) for s, e in spans) for t in POPS_S)
        assert hit >= 4, (c, hit, spans)
    y = DC.apply(xp, sr, DC.plan(xp, sr), 1.0)
    assert float(np.sum((y - x) ** 2)) < 0.5 * float(np.sum(art ** 2))


@pytest.mark.parametrize("drums", [False, True])
def test_clean_music_and_drum_hits_are_left_alone(drums):
    x = _music(drums=drums)
    for c in range(2):
        assert DC.find(x[:, c], SR, 1.0) == [], (drums, c)
    assert DC.apply(x, SR, DC.plan(x, SR), 1.0) is x


def test_only_the_found_clicks_change():
    x = _music()
    xp = x + _pops(x)
    y = DC.apply(xp, SR, DC.plan(xp, SR), 1.0)
    changed = np.any(y != xp, axis=1)
    inside = np.zeros(x.shape[0], dtype=bool)
    for c in range(2):
        for s, e in DC.find(xp[:, c], SR, 1.0):
            inside[s:e] = True
    assert changed.any() and not np.any(changed & ~inside)


def test_the_preview_is_the_export_on_a_window():
    x = _music()
    xp = (x + _pops(x)).astype(np.float32)
    src = Source.from_array(xp, SR)
    s = Settings(fixes={"clicks": 1.0}, auto=False, mastering=False, preserve_volume=False)
    full = render(src, s).audio
    for w in ((0.0, 1.5), (1.137, 2.911), (2.5, 4.0)):
        part = render(src, s, window=w).audio
        a = int(round(w[0] * SR))
        ref = full[a:a + part.shape[0]]
        res = 10 * np.log10(np.sum((part - ref) ** 2.0) / np.sum(ref ** 2.0) + 1e-30)
        assert res < -60.0, (w, res)


def test_render_runs_it_before_the_notch_and_reports_it():
    x = _music()
    xp = (x + _pops(x)).astype(np.float32)
    r = render(Source.from_array(xp, SR),
               Settings(fixes={"clicks": 1.0}, auto=False, mastering=False, preserve_volume=False),
               with_removed=True)
    assert r.report["fixes"]["clicks"]["tool"] == "declick"
    # The Removed track holds the pops.
    assert float(np.sum(r.removed ** 2)) > 0.5 * float(np.sum(_pops(x) ** 2))


def test_bypass_is_bit_exact():
    x = _music()
    assert DC.apply(x, SR, DC.plan(x, SR), 0.0) is x
