"""
Golden values for the BS.1387 damage model.

Why this file exists: an audit's mutation testing changed eight of the
standard's constants one at a time and the suite stayed green every time.
The relation tests in test_perceptual.py check that the model behaves like
a hearing model; they do not check that it is *this* hearing model. These
tests do, two ways:

  1. Every constant the standard mandates is pinned to its cited value, with
     the citation. Kabal, "An Examination and Interpretation of ITU-R
     BS.1387: PEAQ", McGill 2002 (the report perceptual.py is written
     against; page and equation numbers refer to it).
  2. The model's outputs on fixed, seeded signals are pinned to the values
     the audited implementation produced on 2026-09-08. A change to any
     stage moves them. If a change is deliberate, re-derive the numbers
     with the script in the docstring below and say why in the commit.

Golden values were produced by:

    python - <<EOF   (see scratch/golden.py in the session that added this)
    x = test_perceptual._music(); shelves via test_perceptual._shelf(x, g)
    noise = x + _noise(secs, amp=0.02, seed=7); gain = x * 10**(-3/20)
    EOF

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_perceptual_golden.py -q
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shimmer import perceptual as P   # noqa: E402
import test_perceptual as T          # noqa: E402


# ── 1. Constants, each to its citation ─────────────────────────────────

CONSTANTS = [
    # (name, value, where Kabal states it)
    ("SR_MODEL", 48000, "§2, the model is defined at 48 kHz"),
    ("NF", 2048, "§2.3, frame length 2048 samples"),
    ("NADV", 1024, "§2.3, 50 % overlap"),
    ("LP_SPL", 92.0, "§2.4 / Appendix A: Lp = 92 dB SPL for a full-scale sine"),
    ("FCAL", 1019.5, "§2.4: calibration sine at 1019.5 Hz"),
    ("F_LO", 80.0, "§2.6: bands start at 80 Hz"),
    ("F_HI", 18000.0, "§2.6: bands stop at 18 kHz"),
    ("DZ_BASIC", 0.25, "§2.6: dz = 1/4 Bark for the Basic version"),
    ("TAU_MIN", 0.008, "§2.9.1 eq. 32: tau_min = 0.008 s"),
    ("TAU_100_EXC", 0.030, "§2.9.1 eq. 32: tau_100 = 0.030 s (excitation smearing)"),
    ("TAU_100_ADAPT", 0.050, "§4.1 eq. 55: tau_100 = 0.050 s (adaptation and modulation)"),
    ("M1_BASIC", 3, "Appendix G.1, PQ_M1M2: M1 = 3 for the Basic version"),
    ("M2_BASIC", 4, "Appendix G.1, PQ_M1M2: M2 = 4 for the Basic version"),
    ("E0", 1e4, "§4.3 p. 28 and G.3 PQloud: E0 = 1e4 (40 dB re 0 dB SPL)"),
    ("C_FFT", 1.07664, "§4.3 p. 28 and G.3 PQloud: c = 1.07664 for the FFT-based ear model"),
    ("E_LOUD", 0.23, "G.3 PQloud and H.2 PQmovNLoudB: exponent e = 0.23"),
    ("ALPHA", 1.5, "eq. 99 / H.2: alpha = 1.5"),
    ("TF0", 0.15, "eq. 98 / H.2: T0 = 0.15"),
    ("S0_ADDED", 0.5, "H.2 PQmovNLoudB: S0 = 0.5 for RmsNoiseLoud (Basic)"),
    ("S0_MISSING", 1.0, "eq. 98-99, p. 38: S0 = 1 for RmsMissingComponents"),
    ("S0_LINDIST", 1.0, "eq. 105-106, p. 39: S0 = 1 for AvgLinDist"),
    ("DELAY_S", 0.5, "§5.2.1: delayed averaging, 0.5 s"),
    ("N_THRES_SONE", 0.1, "§5.3.1: loudness threshold 0.1 sone"),
    ("GATE_DELAY_S", 0.05, "§5.3.1: 50 ms after the threshold is crossed"),
]


@pytest.mark.parametrize("name,value,cite", CONSTANTS, ids=[c[0] for c in CONSTANTS])
def test_constant_is_the_cited_value(name, value, cite):
    assert getattr(P, name) == value, f"{name}: {cite}"


def test_spreading_skirts_are_the_standard_ones():
    """Lower skirt -27 dB/Bark; upper skirt -24 - 230/fc dB/Bark with a
    level dependence; energies combine with exponent 0.4 (Kabal §2.8
    Frequency Spreading). Checked on the normalisation vector, which is the
    spreading of unit energy in every band."""
    b = P.bands()
    norm = P._spread_norm(b)
    assert norm.shape == (b.n,)
    # Unit energy in every band spreads to more than one unit everywhere
    # (neighbours leak in), and the edge bands receive less than the middle.
    assert np.all(norm > 1.0)
    assert norm[-1] < norm[b.n // 2] and norm[0] < norm[b.n // 2]
    # Pin the values at three bands (computed 2026-09-08 from the audited
    # implementation): any skirt change moves them.
    assert norm[0] == pytest.approx(4.874, abs=2e-3)
    assert norm[b.n // 2] == pytest.approx(14.3927, abs=2e-3)
    assert norm[-1] == pytest.approx(5.9643, abs=2e-3)


def test_critical_band_table_is_the_published_one():
    b = P.bands()
    assert b.n == 109
    assert b.fc[0] == pytest.approx(91.7081, abs=1e-3)
    assert b.fc[-1] == pytest.approx(17690.0436, abs=1e-3)


# ── 2. Golden outputs on fixed signals ─────────────────────────────────

@pytest.fixture(scope="module")
def music():
    return T._music()


def _close(got, want, rel=2e-3, abs_=2e-4):
    return got == pytest.approx(want, rel=rel, abs=abs_)


def test_calibration_tone_loudness_is_pinned():
    """A full-scale 1019.5 Hz sine is 92 dB SPL by definition; its loudness
    through the whole FFT ear model is a single number that every stage up
    to `loudness` feeds into."""
    tone = T._tone(1019.5, secs=1.0, amp=1.0)
    _, es = P.excitation_patterns(tone, T.SR)
    assert float(np.median(P.loudness(es))) == pytest.approx(30.2884, rel=1e-3)
    assert int(np.argmax(es[20])) == 31
    assert float(es[20].max()) == pytest.approx(1.259962e8, rel=1e-3)


@pytest.mark.parametrize("gain_db,lin,missing,added", [
    (-6.0, 19.3987, 0.29987, 0.15739),
    (-12.0, 48.8856, 0.34144, 0.20644),
])
def test_high_shelf_damage_is_pinned(music, gain_db, lin, missing, added):
    d = P.measure_damage(music, T._shelf(music, gain_db), T.SR)
    assert d.frames == 139 and d.gated_frames == 115
    assert _close(d.lin_dist, lin)
    assert _close(d.missing, missing)
    assert _close(d.added, added)


def test_added_noise_damage_is_pinned(music):
    y = music + T._noise(secs=len(music) / T.SR, amp=0.02, seed=7)[:len(music)]
    d = P.measure_damage(music, y, T.SR)
    assert _close(d.lin_dist, 1.9938)
    assert _close(d.missing, 0.37122)
    assert _close(d.added, 10.3351)


def test_a_pure_gain_change_is_no_damage(music):
    """Level-matched inputs: a -3 dB gain with no spectral change must read
    as nothing. Before level matching it read 13.6 on lin_dist."""
    d = P.measure_damage(music, music * 10 ** (-3 / 20), T.SR)
    assert d.level_gain_db == pytest.approx(3.0, abs=1e-6)
    # Rounding from the gain multiply leaves ~1e-7; anything audible is
    # orders of magnitude above this.
    assert d.lin_dist == pytest.approx(0.0, abs=1e-5)
    assert d.missing == pytest.approx(0.0, abs=1e-5)
    assert d.added == pytest.approx(0.0, abs=1e-5)


def test_level_matching_can_be_switched_off(music):
    d = P.measure_damage(music, music * 10 ** (-3 / 20), T.SR, level_match=False)
    assert d.level_gain_db == 0.0
    assert d.lin_dist > 10.0
