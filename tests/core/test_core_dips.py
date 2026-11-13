"""Level dips (shimmer/core/analyze/dips.py): the pin goes on the last low
moment of a drop the song comes back from."""
import numpy as np

from shimmer.core.analyze.dips import level_dips

SR = 48000


def _song(parts):
    """parts: [(seconds, amplitude)] of a 220 Hz tone, back to back."""
    out = []
    for secs, amp in parts:
        n = int(secs * SR)
        t = np.arange(n) / SR
        out.append(amp * np.sin(2 * np.pi * 220 * t))
    y = np.concatenate(out).astype(np.float32)
    return np.stack([y, y], axis=1)


def test_a_drop_the_song_comes_back_from_is_pinned_at_its_end():
    x = _song([(60, 0.5), (4, 0.02), (30, 0.5)])
    pts = level_dips(x, SR)
    assert len(pts) == 1
    assert 63.5 <= pts[0]["at_s"] <= 64.0
    assert pts[0]["rise_db"] >= 20


def test_a_drop_with_nothing_after_is_not_a_dip():
    x = _song([(60, 0.5), (10, 0.02)])
    assert level_dips(x, SR) == []


def test_a_break_in_the_first_quarter_is_ignored():
    x = _song([(10, 0.5), (3, 0.02), (60, 0.5)])
    assert level_dips(x, SR) == []


def test_at_most_three_deepest_first_and_spaced_apart():
    x = _song([(30, 0.5), (3, 0.1), (20, 0.5), (3, 0.01), (20, 0.5),
               (3, 0.05), (20, 0.5), (3, 0.03), (20, 0.5)])
    pts = level_dips(x, SR)
    assert len(pts) == 3
    dips = [p["dip_db"] for p in pts]
    assert dips == sorted(dips, reverse=True)
    times = sorted(p["at_s"] for p in pts)
    assert all(b - a >= 5 for a, b in zip(times, times[1:]))


def test_silence_and_tiny_files_do_not_fail():
    assert level_dips(np.zeros((SR * 30, 2), np.float32), SR) == []
    assert level_dips(np.zeros((100, 2), np.float32), SR) == []
