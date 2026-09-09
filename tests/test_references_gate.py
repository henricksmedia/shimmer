"""The reference library's validity gate and its report.

The library published "the captured music is 8.4 dB darker than the tone
target" from a median over fifteen rows, two of which were broken recordings
reading -50 dB at 10 kHz, and with no statement of how far that median could
move. These tests pin the three things that fixes:

  * a gate that rejects a recording no master could produce,
  * derived from real masters and NOT from the tone target, so a capture is
    never rejected merely for disagreeing with the thing under test,
  * and a report that separates commercial evidence from control captures,
    states n, and gives an interval rather than a bare number.
"""
import numpy as np
import pytest

from shimmer import references as R
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB, relative_band_levels

F = np.asarray(_REF_FREQS, dtype=np.float64)


def row(curve, seconds=60.0, label="a track"):
    return {"label": label, "heard_seconds": seconds,
            "rel_db": [float(v) for v in curve]}


def realistic():
    """A curve shaped like music: falls smoothly, no cliff."""
    return relative_band_levels(-4.5 * np.log2(F / 1000.0)
                                + 10.0 * np.log10(0.2316 * F))


# ── every band must have real content behind it ─────────────────────────

def test_the_analysis_window_resolves_every_band():
    """A band with no FFT bin in it returns a sentinel that reads as data.

    The capture analysed 4096-sample blocks. At 48 kHz that is 11.7 Hz per
    bin, and the 40 Hz third-octave band spans 35.6-44.9 Hz, so no bin landed
    inside it: `analyze_spectrum` returned -120 dB and every capture recorded
    about -155 dB there. Thirteen of thirteen carried it and nobody saw it
    until a tone target was derived from them.
    """
    edges_lo = F / 2.0 ** (1.0 / 6.0)
    edges_hi = F * 2.0 ** (1.0 / 6.0)
    bins = np.fft.rfftfreq(R.ANALYSIS, 1.0 / R.SR)
    for lo, hi, centre in zip(edges_lo, edges_hi, F):
        if centre > R.SR / 2:
            continue
        inside = int(((bins >= lo) & (bins <= hi)).sum())
        assert inside >= 1, f"{centre:.0f} Hz band has no FFT bin in it"


def test_the_old_block_size_would_have_failed_this():
    """Guards the guard: if the assertion above cannot fail it proves nothing."""
    bins = np.fft.rfftfreq(4096, 1.0 / R.SR)
    empty = [float(c) for c in F
             if c <= R.SR / 2 and not ((bins >= c / 2 ** (1 / 6))
                                       & (bins <= c * 2 ** (1 / 6))).any()]
    assert empty, "expected the old 4096-sample window to leave a band empty"


# ── the gate itself ─────────────────────────────────────────────────────

def test_gate_comes_from_real_masters_not_from_the_target():
    """If the gate were derived from the target it would beg the question."""
    g = R.gate()
    assert g["n"] >= 30, "gate should be measured from the shipped corpus"
    # The target sits far above the gate's floor, so the gate is plainly not
    # a restatement of it.
    i10 = int(np.argmin(np.abs(F - 10000.0)))
    assert g["hz10_db"] < _REF_SHAPE_DB[i10] - 15.0


def test_a_normal_master_passes():
    assert R.rejection(row(realistic())) == ""


def test_a_curve_that_disagrees_with_the_target_still_passes():
    """The one failure mode that would make the library useless.

    A capture 8 dB darker than the target across the top is exactly what the
    library exists to be able to report. If the gate rejected it, the tool
    could only ever confirm the target.
    """
    c = realistic()
    top = F >= 2500.0
    c = np.asarray(c, dtype=np.float64).copy()
    c[top] -= 8.0
    assert R.rejection(row(c)) == ""


def test_a_cliff_at_10k_is_rejected():
    c = np.asarray(realistic(), dtype=np.float64).copy()
    c[F >= 8000.0] -= 45.0
    why = R.rejection(row(c))
    assert why and "10 kHz" in why


def test_a_short_capture_is_rejected():
    why = R.rejection(row(realistic(), seconds=8.0))
    assert why and "8s" in why


def test_rejection_reasons_are_plain_language():
    c = np.asarray(realistic(), dtype=np.float64).copy()
    c[F >= 8000.0] -= 45.0
    why = R.rejection(row(c))
    assert why.endswith(".") and why[0].isupper()
    for jargon in ("rel_db", "percentile", "None", "traceback"):
        assert jargon not in why


# ── controls must not be pooled with evidence ───────────────────────────

def test_a_capture_of_a_local_file_is_a_control():
    """Playing our own files back is chain validation, not new evidence.

    Most files in sources/ are masters from the same service the tone target
    was built from. Counting them as commercial music pulls the median toward
    the target and hides the difference being measured.
    """
    import glob
    import os
    have = glob.glob(os.path.join(R.SOURCES, "*.wav"))
    if not have:
        pytest.skip("no source files on this machine")
    name = os.path.splitext(os.path.basename(have[0]))[0]
    assert R.is_control({"label": name})
    assert not R.is_control({"label": "Some Band - Some Song"})


# ── the report ──────────────────────────────────────────────────────────

def test_report_states_n_and_an_interval(monkeypatch):
    """A difference without an interval is not a measurement."""
    curves = []
    rng = np.random.default_rng(7)
    for i in range(12):
        c = np.asarray(realistic(), dtype=np.float64).copy()
        c[F >= 2500.0] -= 8.0 + rng.normal(0.0, 1.0)
        curves.append(row(c, label=f"track {i}"))
    monkeypatch.setattr(R, "load", lambda: {"tracks": curves})

    rep = R.report()
    assert rep["n"] == 12
    lo, hi = rep["presence_ci"]
    assert lo < rep["presence_corrected"] < hi
    assert rep["presence_se"] > 0.0
    assert str(rep["n"]) in rep["headline"]


def test_a_difference_inside_the_interval_is_not_called_a_finding(monkeypatch):
    """With few tracks and wide spread the honest answer is 'not yet'."""
    rng = np.random.default_rng(3)
    curves = []
    for i in range(3):
        c = np.asarray(realistic(), dtype=np.float64).copy()
        c[F >= 2500.0] += rng.normal(0.0, 4.0)
        curves.append(row(c, label=f"track {i}"))
    monkeypatch.setattr(R, "load", lambda: {"tracks": curves})

    rep = R.report()
    if rep["presence_ci"][0] <= 0.0 <= rep["presence_ci"][1]:
        assert rep["verdict"] == "unclear"
        assert "not enough" in rep["headline"].lower()


def test_broken_captures_are_excluded_and_explained(monkeypatch):
    good = [row(realistic(), label=f"good {i}") for i in range(6)]
    broken = np.asarray(realistic(), dtype=np.float64).copy()
    broken[F >= 8000.0] -= 45.0
    monkeypatch.setattr(R, "load",
                        lambda: {"tracks": good + [row(broken, label="broken")]})

    rep = R.report()
    assert rep["captured"] == 7
    assert rep["n"] == 6
    assert len(rep["rejected"]) == 1
    assert rep["rejected"][0]["label"] == "broken"
    assert rep["rejected"][0]["why"]
    assert any("broken" in c for c in rep["caveats"])


def test_listed_tracks_stay_aligned_with_the_file(monkeypatch):
    """The remove button sends a row's position; delete() indexes the file.

    Filtering the list shown while indexing the unfiltered file removes the
    wrong track. This happened the moment controls and broken rows were split
    out of the listing, and it is silent: the page looks right and deletes
    someone else's row.
    """
    broken = np.asarray(realistic(), dtype=np.float64).copy()
    broken[F >= 8000.0] -= 45.0
    rows = [row(realistic(), label="keep one"),
            row(broken, label="broken"),
            row(realistic(), label="keep two")]
    monkeypatch.setattr(R, "load", lambda: {"tracks": rows})

    s = R.summary()
    assert len(s["tracks"]) == len(rows)
    for shown, actual in zip(s["tracks"], rows):
        assert shown["label"] == actual["label"]
    assert s["count"] == 2                      # stats still exclude the bad row
    assert [t["status"] for t in s["tracks"]] == ["ok", "rejected", "ok"]


def test_everything_rejected_does_not_read_as_nothing_captured(monkeypatch):
    broken = np.asarray(realistic(), dtype=np.float64).copy()
    broken[F >= 8000.0] -= 45.0
    monkeypatch.setattr(R, "load", lambda: {"tracks": [row(broken, label="b")]})

    rep = R.report()
    assert rep["n"] == 0
    assert "broken" in rep["headline"].lower()
    assert "nothing captured" not in rep["headline"].lower()
