"""
Edge-artifact detection (edges.py) test suite.

Covers:
  1. The signature case — a short quiet burst, a gap, then program.
  2. Rejection — clean fade-ins, musical intro notes, and pure silence
     must not be flagged. False positives are worse than misses here:
     a wrong cut removes music.
  3. Tail detection and its mirrored timings.
  4. The suggested cut lands inside the gap, on a zero crossing.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_edges.py -q
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.edges import apply_trim, detect_edge_artifacts

SR = 48000


def _tone(dur_s: float, hz: float = 220.0, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(dur_s * SR)) / SR
    return (amp * np.sin(2 * np.pi * hz * t)).astype(np.float32)[:, None] * np.ones((1, 2), np.float32)


def _silence(dur_s: float) -> np.ndarray:
    return np.zeros((int(dur_s * SR), 2), dtype=np.float32)


def _burst(dur_ms: float, peak: float) -> np.ndarray:
    """Short decaying noise burst — the shape a render glitch actually has."""
    n = int(dur_ms / 1000.0 * SR)
    rng = np.random.default_rng(7)
    env = np.exp(-np.linspace(0, 5, n, dtype=np.float32))
    x = rng.standard_normal((n, 2)).astype(np.float32) * env[:, None]
    return (x / np.abs(x).max() * peak).astype(np.float32)


# ── 1. The signature case ────────────────────────────────────────────────

def test_detects_head_burst_before_program():
    x = np.concatenate([_burst(25, 0.003), _silence(0.15), _tone(3.0)])
    r = detect_edge_artifacts(x, SR)

    assert r["found"] and r["head"] is not None
    h = r["head"]
    # Measured length is the audible part, so a decaying 25 ms burst
    # reads shorter than its nominal length.
    assert 10.0 < h["artifact_ms"] < 60.0
    assert -60.0 < h["artifact_peak_db"] < -40.0
    assert h["gap_ms"] > 100.0
    # Suggested cut sits after the burst and before the music.
    assert h["artifact_end_s"] <= h["suggested_s"] < h["program_s"]


def test_burst_above_silence_gate_still_detected():
    """The whole point: -49 dBFS is above a -60 dBFS trim gate, so plain
    silence trimming keeps it. Detection must not use that gate."""
    x = np.concatenate([_burst(25, 0.0035), _silence(0.15), _tone(3.0)])
    h = detect_edge_artifacts(x, SR)["head"]
    assert h is not None and h["artifact_peak_db"] > -60.0


# ── 2. Rejection ─────────────────────────────────────────────────────────

def test_clean_fade_in_not_flagged():
    y = _tone(3.0)
    ramp = np.linspace(0.0, 1.0, int(0.5 * SR), dtype=np.float32)[:, None]
    y[:ramp.shape[0]] *= ramp
    assert detect_edge_artifacts(np.concatenate([_silence(0.2), y]), SR)["head"] is None


def test_musical_intro_note_not_flagged():
    """A long note that decays into a short gap is arrangement, not a
    glitch — the gap is shorter than the note that precedes it."""
    note = _tone(0.4, hz=110.0, amp=0.2)
    note *= np.linspace(1.0, 0.0, note.shape[0], dtype=np.float32)[:, None]
    x = np.concatenate([note, _silence(0.05), _tone(3.0)])
    assert detect_edge_artifacts(x, SR)["head"] is None


def test_silence_only_not_flagged():
    r = detect_edge_artifacts(_silence(4.0), SR)
    assert not r["found"]


def test_inaudible_burst_not_flagged():
    x = np.concatenate([_burst(25, 1e-5), _silence(0.15), _tone(3.0)])
    assert detect_edge_artifacts(x, SR)["head"] is None


def test_continuous_music_not_flagged():
    assert not detect_edge_artifacts(_tone(4.0), SR)["found"]


# ── 3. Tail ──────────────────────────────────────────────────────────────

def test_detects_tail_burst_with_mirrored_timings():
    x = np.concatenate([_tone(3.0), _silence(0.4), _burst(25, 0.003)])
    r = detect_edge_artifacts(x, SR)
    t = r["tail"]

    assert t is not None
    dur = r["duration_s"]
    assert 10.0 < t["artifact_ms"] < 60.0
    # Timings are real positions near the end, and ordered start < end.
    assert t["artifact_start_s"] < t["artifact_end_s"] <= dur
    assert t["artifact_start_s"] > dur - 0.2
    # The cut sits after the music ends and before the burst begins.
    assert t["program_s"] < t["suggested_s"] <= t["artifact_start_s"]


# ── 4. Cut placement ─────────────────────────────────────────────────────

def test_suggested_cut_is_quiet():
    """Cutting on a near-zero sample is what keeps the edit from clicking."""
    x = np.concatenate([_burst(25, 0.003), _silence(0.15), _tone(3.0)])
    h = detect_edge_artifacts(x, SR)["head"]
    i = int(h["suggested_s"] * SR)
    assert np.abs(x[i]).max() < 1e-3


# ── 5. apply_trim ────────────────────────────────────────────────────────

def test_apply_trim_removes_the_artifact():
    x = np.concatenate([_burst(25, 0.003), _silence(0.15), _tone(3.0)])
    h = detect_edge_artifacts(x, SR)["head"]
    y, rep = apply_trim(x, SR, h["suggested_s"])

    assert rep["applied"]
    assert y.shape[0] == x.shape[0] - int(round(h["suggested_s"] * SR))
    # Re-scanning the result finds nothing: the burst is gone.
    assert detect_edge_artifacts(y, SR)["head"] is None


def test_apply_trim_no_op_reports_untouched():
    x = _tone(2.0)
    y, rep = apply_trim(x, SR, 0.0, None)
    assert not rep["applied"] and np.array_equal(y, x)


def test_apply_trim_fades_both_new_edges():
    x = _tone(3.0, amp=0.5)
    y, _ = apply_trim(x, SR, 0.5, 2.5)
    # A raw cut through a sine leaves a step; the fade must start near zero.
    assert abs(float(y[0].max())) < 0.05
    assert abs(float(y[-1].max())) < 0.05


def test_apply_trim_clamps_inverted_points():
    """A bad marker degrades to no edit rather than an empty export."""
    x = _tone(2.0)
    y, rep = apply_trim(x, SR, 1.5, 0.5)
    assert not rep["applied"] and y.shape[0] == x.shape[0]


def test_apply_trim_out_point_only():
    x = _tone(3.0)
    y, rep = apply_trim(x, SR, 0.0, 2.0)
    assert rep["applied"] and rep["cut_head_s"] == 0.0
    assert abs(rep["cut_tail_s"] - 1.0) < 0.01
