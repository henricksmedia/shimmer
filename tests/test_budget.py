"""Tests for the artifact budget.

The property that matters: a track with no artifact earns no removal, so a
preset cannot strip a finished master. That is the failure this module exists
to prevent, and it is the first test here.
"""
import numpy as np
import pytest

from shimmer import budget as B


SR = 48000


def _music(secs=3.0, sr=SR, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(int(secs * sr)) / sr
    x = sum(0.3 / k * np.sin(2 * np.pi * 220 * k * t) for k in range(1, 12))
    x += 0.02 * rng.standard_normal(t.size)
    return (0.4 * x / np.max(np.abs(x)))[:, None]


# ── The budget itself ──────────────────────────────────────────────────

def test_no_hash_signature_earns_nothing():
    b = B.estimate_budget(None, SR, flicker_excess_db=-0.28)
    assert b.sones == 0.0
    assert "nothing to remove" in b.reason


def test_signature_below_the_floor_earns_nothing():
    assert B.estimate_budget(None, SR,
                             flicker_excess_db=B.EXCESS_FLOOR_DB - 0.01
                             ).sones == 0.0


def test_a_real_signature_earns_a_budget():
    b = B.estimate_budget(None, SR, flicker_excess_db=1.14)
    assert b.sones > 0.0
    assert "excess flicker" in b.reason


def test_budget_never_runs_away_on_a_badly_hashed_render():
    assert B.estimate_budget(None, SR,
                             flicker_excess_db=50.0
                             ).sones == B.MAX_BUDGET_SONES


def test_budget_is_monotonic_in_measured_artifact():
    got = [B.estimate_budget(None, SR, flicker_excess_db=e).sones
           for e in (0.6, 1.5, 4.0, 10.0)]
    assert got == sorted(got)


# ── Enforcement ────────────────────────────────────────────────────────

def test_a_clean_track_is_returned_untouched():
    """The headline case: Deep Scrub took 6.5 dB out of a finished master
    that had no artifact in it. With a zero budget it must take nothing."""
    x = _music()
    stripped = x * 0.5                        # stand-in for heavy processing
    zero = B.estimate_budget(None, SR, flicker_excess_db=-0.28)
    y, rep = B.apply_within_budget(x, stripped, SR, zero)
    assert rep.mix == 0.0
    assert rep.held_back
    assert np.allclose(y, x, atol=1e-6)


def test_cleaning_inside_the_budget_passes_through_unchanged():
    x = _music()
    barely = x.copy()
    barely[::1000] *= 0.999                   # inaudible
    b = B.estimate_budget(None, SR, flicker_excess_db=3.0)
    y, rep = B.apply_within_budget(x, barely, SR, b)
    assert rep.mix == 1.0
    assert not rep.held_back
    assert np.allclose(y, barely)


def test_over_budget_cleaning_is_pulled_back_towards_the_original():
    from shimmer.eq import EqBand, EqParams, apply_eq
    x = _music()
    heavy = apply_eq(x, SR, EqParams(
        enabled=True, bands=[EqBand("high_shelf", 3000.0, -12.0, 0.7, True)]))
    b = B.estimate_budget(None, SR, flicker_excess_db=1.0)
    y, rep = B.apply_within_budget(x, heavy, SR, b)
    assert rep.held_back
    assert 0.0 <= rep.mix < 1.0
    assert rep.damage_after["missing"] <= b.sones + 1e-6
    assert rep.damage_after["missing"] < rep.damage_before["missing"]


def test_the_held_back_result_lies_between_original_and_cleaned():
    """Mix-back must be a blend, never something newly synthesised."""
    from shimmer.eq import EqBand, EqParams, apply_eq
    x = _music()
    heavy = apply_eq(x, SR, EqParams(
        enabled=True, bands=[EqBand("high_shelf", 3000.0, -12.0, 0.7, True)]))
    b = B.estimate_budget(None, SR, flicker_excess_db=1.0)
    y, rep = B.apply_within_budget(x, heavy, SR, b)
    expected = x + rep.mix * (heavy[:x.shape[0]] - x)
    assert np.allclose(y, expected, atol=1e-5)


def test_report_explains_itself_in_plain_words():
    x = _music()
    zero = B.estimate_budget(None, SR, flicker_excess_db=-0.28)
    _, rep = B.apply_within_budget(x, x * 0.5, SR, zero)
    assert rep.reason and rep.reason[0].isupper() and rep.reason.endswith(".")
    assert "sones" not in rep.reason.split(".")[0]   # lead with the meaning
