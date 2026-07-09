"""
Parametric EQ (eq.py) test suite.

Covers:
  1. Response accuracy — zero-phase double pass lands exactly on the
     user's dB at band centers (the half-gain design contract).
  2. JSON parsing — clamping, junk tolerance, enable semantics.
  3. Pipeline integration — EQ audibly changes clean_and_master output
     and reports itself; disabled EQ is a bit-exact no-op.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_eq.py -q
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eq import (
    EqBand, EqParams, apply_eq, compile_sos, eq_params_from_json,
    response_db,
)

SR = 44100


def _one_band(**kw) -> EqParams:
    return EqParams(enabled=True, bands=[EqBand(**kw)])


# ── 1. Response accuracy ─────────────────────────────────────────────────

@pytest.mark.parametrize("gain", [-12.0, -6.0, -2.5, 2.5, 6.0, 12.0])
def test_bell_center_gain_exact(gain):
    eq = _one_band(type="bell", freq_hz=1000.0, gain_db=gain, q=1.0)
    r = response_db(eq, np.array([1000.0]), SR)
    assert abs(r[0] - gain) < 0.05


@pytest.mark.parametrize("btype,probe_hz", [
    ("low_shelf", 40.0),      # deep in the shelf's plateau
    ("high_shelf", 18000.0),
])
def test_shelf_plateau_gain_exact(btype, probe_hz):
    eq = _one_band(type=btype, freq_hz=1000.0, gain_db=-4.0, q=0.707)
    r = response_db(eq, np.array([probe_hz]), SR)
    assert abs(r[0] - (-4.0)) < 0.3


def test_sine_through_bell_measures_designed_gain():
    """End-to-end: a 1 kHz sine through a +6 dB bell gains 6.0 dB."""
    eq = _one_band(type="bell", freq_hz=1000.0, gain_db=6.0, q=1.0)
    t = np.arange(SR) / SR
    x = (0.1 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)[:, None]
    y = apply_eq(x, SR, eq)
    core = slice(SR // 4, -SR // 4)  # skip filter edge transients
    gain = 20 * np.log10(
        np.sqrt(np.mean(y[core] ** 2)) / np.sqrt(np.mean(x[core] ** 2)))
    assert abs(gain - 6.0) < 0.1


def test_highpass_attenuates_below_cutoff():
    eq = _one_band(type="highpass", freq_hz=100.0, q=0.707)
    r = response_db(eq, np.array([25.0, 1000.0]), SR)
    assert r[0] < -20.0          # 2 octaves below cutoff, doubled slope
    assert abs(r[1]) < 0.2       # passband untouched


def test_notch_is_deep_and_narrow():
    eq = _one_band(type="notch", freq_hz=4000.0, q=8.0)
    r = response_db(eq, np.array([4000.0, 2000.0, 8000.0]), SR)
    assert r[0] < -40.0
    assert abs(r[1]) < 0.5
    assert abs(r[2]) < 0.5


def test_zero_phase_no_delay():
    """An impulse stays centered: zero-phase filtering must not shift it."""
    eq = _one_band(type="bell", freq_hz=2000.0, gain_db=8.0, q=2.0)
    n = SR // 2
    x = np.zeros((n, 1), dtype=np.float32)
    x[n // 2, 0] = 1.0
    y = apply_eq(x, SR, eq)
    assert abs(int(np.argmax(np.abs(y[:, 0]))) - n // 2) <= 1


def test_multiband_cascade_sums():
    eq = EqParams(enabled=True, bands=[
        EqBand("bell", 1000.0, 3.0, 1.0),
        EqBand("bell", 1000.0, 2.0, 1.0),
    ])
    r = response_db(eq, np.array([1000.0]), SR)
    assert abs(r[0] - 5.0) < 0.1


# ── 2. Parsing & gating ──────────────────────────────────────────────────

def test_from_json_clamps_and_skips_junk():
    eq = eq_params_from_json({"enabled": True, "bands": [
        {"type": "bell", "freq_hz": 5, "gain_db": 99, "q": 0.001},
        {"type": "bogus", "freq_hz": 1000},
        "garbage",
        {"type": "notch", "freq_hz": 16000, "q": 8},
    ]})
    assert len(eq.bands) == 2
    b = eq.bands[0]
    assert b.freq_hz == 20.0 and b.gain_db == 18.0 and b.q == 0.1


def test_from_json_band_cap():
    bands = [{"type": "bell", "freq_hz": 100 + i, "gain_db": 1}
             for i in range(40)]
    eq = eq_params_from_json({"enabled": True, "bands": bands})
    assert len(eq.bands) == 12


def test_disabled_or_empty_is_inactive():
    assert not eq_params_from_json({}).is_active(SR)
    assert not eq_params_from_json(
        {"bands": [{"type": "bell", "gain_db": 3}]}).is_active(SR)  # no enable
    assert not eq_params_from_json(
        {"enabled": True, "bands": []}).is_active(SR)
    # Zero-gain bell counts as inactive; a highpass never does.
    assert not eq_params_from_json(
        {"enabled": True,
         "bands": [{"type": "bell", "gain_db": 0.0}]}).is_active(SR)
    assert eq_params_from_json(
        {"enabled": True, "bands": [{"type": "highpass",
                                     "freq_hz": 30}]}).is_active(SR)


def test_band_above_nyquist_skipped():
    eq = _one_band(type="bell", freq_hz=19000.0, gain_db=6.0, q=1.0)
    assert compile_sos(eq, 22050) is None  # 19 kHz > 0.49 * 22050


def test_apply_eq_disabled_is_identity():
    x = np.random.default_rng(0).standard_normal((SR, 2)).astype(np.float32)
    eq = EqParams(enabled=False,
                  bands=[EqBand("bell", 1000.0, 12.0, 1.0)])
    assert apply_eq(x, SR, eq) is x


# ── 3. Pipeline integration ──────────────────────────────────────────────

def _noise(seconds=2.0, ch=2):
    rng = np.random.default_rng(42)
    return (0.1 * rng.standard_normal(
        (int(SR * seconds), ch))).astype(np.float32)


def test_pipeline_applies_eq_and_reports():
    from params import Params
    from pipeline import clean_and_master

    x = _noise()
    p = Params()
    eq = _one_band(type="bell", freq_hz=500.0, gain_db=-10.0, q=1.0)

    y_off, _, rep_off = clean_and_master(x, SR, p, eq_params=None)
    y_on, _, rep_on = clean_and_master(x, SR, p, eq_params=eq)

    assert rep_off["eq"] == {"enabled": False}
    assert rep_on["eq"] == {"enabled": True, "bands": 1}

    # 500 Hz is below the 4500 Hz crossover: cleaning leaves it alone,
    # so the EQ cut must show up as a level drop around 500 Hz.
    from scipy.signal import welch
    f, pxx_off = welch(y_off[:, 0], SR, nperseg=4096)
    _, pxx_on = welch(y_on[:, 0], SR, nperseg=4096)
    band = (f > 400) & (f < 620)
    drop_db = 10 * np.log10(np.mean(pxx_on[band]) / np.mean(pxx_off[band]))
    assert drop_db < -6.0
