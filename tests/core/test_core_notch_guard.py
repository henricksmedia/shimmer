"""The notch plan leaves held notes alone (shimmer/core/repair/notch.py).

On "Alive Again" the scan found A7 (3514 Hz) and the plan cut it by 15.8 dB
(docs/CHAIN-AUDIT.md section 3). The generator's own lines sit on a 200 Hz
grid (14.2, 16.0, 17.6 and 19.2 kHz on five songs), and they must still be
cut.
"""
from shimmer.core.repair import notch

SR = 48000


def _line(hz, excess=7.4, duty=0.58):
    return {"hz": hz, "excess_db": excess, "excess_hi_db": excess + 2.0, "duty": duty}


def test_a_held_note_is_left_alone():
    assert notch.looks_like_a_note(3513.9)                 # A7, 3 cents flat
    assert notch.plan_from_lines([_line(3513.9)], SR).notches == []


def test_the_generators_grid_lines_are_still_cut():
    lines = [_line(hz) for hz in (14200.5, 15999.3, 17600.5, 19199.5, 4000.0)]
    kept = sorted(round(n.hz) for n in notch.plan_from_lines(lines, SR).notches)
    assert kept == [4000, 14200, 15999, 17600, 19200]


def test_an_off_grid_line_between_notes_is_still_cut():
    # 3650 Hz: 63 cents above A7 and 37 under A#7, and off the grid.
    assert not notch.looks_like_a_note(3650.0)
    assert [round(n.hz) for n in notch.plan_from_lines([_line(3650.0)], SR).notches] == [3650]
