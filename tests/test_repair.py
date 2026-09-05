"""
Phase 1 deterministic repairs (repair.py) and their place in the chain.

  * Static repair: the whole-file scan finds a centered steady tone and
    comb teeth, the plan notches them at full depth on both channels,
    neighbours are untouched, musical partials are never notched, and
    the pipeline output (Mid-scaled engine and all) loses the tone.
  * De-click: injected clicks are found and repaired on the high band,
    the low band is untouched, drum hits are not mistaken for clicks.
  * Cutoff: a brick-wall render is measured, a full-band one is not, and
    the tone curve never boosts above the cutoff.
  * Chain: the new stages sit between Trim and the tone curve.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_repair.py -q
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest
from scipy import signal as ss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer import detect, repair  # noqa: E402
from shimmer.chain import build_chain  # noqa: E402
from shimmer.mastering import compute_tone_curve, master_params_from_json  # noqa: E402
from shimmer.params import Params  # noqa: E402
from shimmer.pipeline import clean_and_master  # noqa: E402
from shimmer.presets import get_preset  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_detect import SR, _music, _tone  # noqa: E402


def _bin_level_db(x: np.ndarray, sr: int, hz: float, n_fft: int = 8192) -> float:
    """Long-term level of one narrow bin (median over frames), dB."""
    mono = x.mean(axis=1) if x.ndim > 1 else x
    f, _, Z = ss.stft(mono, fs=sr, nperseg=n_fft, noverlap=n_fft // 2)
    b = int(np.argmin(np.abs(f - hz)))
    return float(np.median(20.0 * np.log10(np.abs(Z[b]) + 1e-12)))


@pytest.fixture(scope="module")
def bed():
    return _music(8.0)


@pytest.fixture(scope="module")
def toned(bed):
    # Centered (L = R) steady tone: exactly the case the M/S engine
    # could only reach at 20-25 %.
    t = _tone(8.0, 11200.0, 0.02)
    t[:, 1] = t[:, 0]
    return (bed + t).astype(np.float32)


class TestStaticRepairPlan:
    def test_scan_finds_the_tone_and_plan_notches_it(self, toned):
        lines = detect.scan_fixed_lines(toned, SR)
        assert any(abs(L["hz"] - 11200.0) < 40.0 and L["excess_db"] > 6.0 for L in lines)
        plan = repair.plan_from_lines(lines, SR)
        assert any(abs(n.hz - 11200.0) < 40.0 for n in plan.notches)
        n = next(n for n in plan.notches if abs(n.hz - 11200.0) < 40.0)
        assert 5.0 <= n.depth_db <= repair.MAX_NOTCH_DEPTH_DB

    def test_clean_bed_has_no_notches(self, bed):
        # The bed's chord changes every half second: partials come and go
        # and must never qualify as fixed lines.
        plan = repair.plan_from_lines(detect.scan_fixed_lines(bed, SR), SR)
        assert plan.notches == []

    def test_comb_teeth_are_found(self, bed):
        n = bed.shape[0]
        t = np.arange(n) / SR
        comb = np.zeros(n)
        for k in range(10, 16):                  # 6000..9000 Hz, 600 Hz spacing
            comb += 0.006 * np.sin(2 * np.pi * (600.0 * k) * t + k)
        x = (bed + np.stack([comb, comb], axis=1)).astype(np.float32)
        lines = detect.scan_fixed_lines(x, SR)
        teeth = [L for L in lines if L["kind"] == "comb"]
        assert len(teeth) >= 4
        plan = repair.plan_from_lines(lines, SR)
        assert sum(1 for m in plan.notches if m.kind == "comb") >= 4

    def test_from_dict_validates(self):
        plan = repair.NotchPlan.from_dict({"enabled": True, "notches": [
            {"hz": 12000.0, "depth_db": 80.0},      # depth clamped
            {"hz": 500.0, "depth_db": 10.0},        # below the floor: dropped
            {"hz": "bad", "depth_db": 10.0},        # garbage: dropped
        ]}, sr=SR)
        assert len(plan.notches) == 1
        assert plan.notches[0].depth_db == repair.MAX_NOTCH_DEPTH_DB


class TestStaticRepairFilter:
    def test_notch_depth_and_selectivity(self, toned):
        plan = repair.plan_from_lines(detect.scan_fixed_lines(toned, SR), SR)
        y, rep = repair.apply_static_repair(toned, SR, plan)
        assert rep["enabled"] and rep["notches"] >= 1
        drop = _bin_level_db(toned, SR, 11200.0) - _bin_level_db(y, SR, 11200.0)
        assert drop >= 15.0
        # Music 300 Hz away is untouched, and so is the low band.
        near = _bin_level_db(toned, SR, 10900.0) - _bin_level_db(y, SR, 10900.0)
        assert abs(near) < 0.6
        lo_in = np.sqrt(np.mean(toned[:, 0] ** 2))
        lo_out = np.sqrt(np.mean(y[:, 0] ** 2))
        assert abs(20 * np.log10(lo_out / lo_in)) < 0.2
        assert y.shape == toned.shape

    def test_pipeline_reaches_the_centered_tone(self, toned):
        # Without the plan the Mid-scaled engine barely touches it.
        p = get_preset("generic")
        y0, _, _ = clean_and_master(toned, SR, p, master_params=None)
        plan = repair.plan_from_lines(detect.scan_fixed_lines(toned, SR), SR)
        y1, removed, rep = clean_and_master(toned, SR, get_preset("generic"),
                                            master_params=None, repair=plan)
        before = _bin_level_db(toned, SR, 11200.0)
        assert before - _bin_level_db(y1, SR, 11200.0) >= 15.0
        assert (before - _bin_level_db(y0, SR, 11200.0)) < 6.0
        assert rep["static_repair"]["notches"] >= 1
        # And the tone shows up in Removed.
        assert _bin_level_db(removed, SR, 11200.0) > _bin_level_db(removed, SR, 10900.0) + 10.0


class TestDeclick:
    def _clicks(self, x, n_clicks=40, amp=0.6, seed=3):
        rng = np.random.default_rng(seed)
        y = x.copy()
        n = x.shape[0]
        pos = np.sort(rng.integers(int(0.2 * SR), n - int(0.2 * SR), n_clicks))
        for p_ in pos:
            y[p_, :] += amp * rng.choice([-1.0, 1.0])
            y[p_ + 1, :] -= 0.5 * amp
        return y.astype(np.float32), pos

    def _hf_energy_at(self, x, pos, width=6):
        h = repair.apply_highpass(x, SR, 2000.0, order=4)
        e = 0.0
        for p_ in pos:
            seg = h[max(0, p_ - width):p_ + width, 0]
            e += float(np.sum(seg ** 2))
        return e

    def test_clicks_are_found_and_repaired(self, bed):
        x, pos = self._clicks(bed)
        y, rep = repair.declick(x, SR, 0.7)
        assert rep["enabled"]
        assert rep["clicks"] >= 0.9 * len(pos)
        e_before = self._hf_energy_at(x, pos)
        e_after = self._hf_energy_at(y, pos)
        assert 10 * np.log10(e_before / max(e_after, 1e-12)) >= 12.0
        assert y.shape == x.shape

    def test_low_band_untouched_and_hits_spared(self, bed):
        x, _ = self._clicks(bed)
        y, rep = repair.declick(x, SR, 0.7)
        lo_x = repair.apply_highpass(x, SR, 1.0)  # no-op HP just to share dtype
        lo_in = np.sqrt(np.mean((x - repair.apply_highpass(x, SR, 2000.0, order=4)) ** 2))
        lo_out = np.sqrt(np.mean((y - repair.apply_highpass(y, SR, 2000.0, order=4)) ** 2))
        assert abs(20 * np.log10(lo_out / lo_in)) < 0.05
        # The bed's drum hits (30 ms bursts, four per second) are not clicks.
        _, rep_clean = repair.declick(bed, SR, 0.7)
        assert rep_clean["clicks_per_s"] <= 1.0

    def test_off_at_zero(self, bed):
        y, rep = repair.declick(bed, SR, 0.0)
        assert rep["enabled"] is False
        assert np.array_equal(y, bed)


class TestCutoff:
    def test_brick_wall_is_measured(self, bed):
        sos = ss.butter(10, 12000.0, btype="lowpass", fs=SR, output="sos")
        x = ss.sosfiltfilt(sos, bed, axis=0).astype(np.float32)
        r = repair.estimate_cutoff_hz(x, SR)
        assert r["cutoff_hz"] is not None
        assert abs(r["cutoff_hz"] - 12000.0) < 1200.0

    def test_full_band_is_none(self, bed):
        assert repair.estimate_cutoff_hz(bed, SR)["cutoff_hz"] is None

    def test_tone_curve_never_boosts_above_cutoff(self, bed):
        # A dark spectrum asks for top-end boost; the cutoff must veto it.
        dark = {"band_db": [-40.0] * 30}
        from shimmer.mastering import _REF_FREQS
        dark["band_db"] = [-60.0 if f_ >= 8000 else -20.0 for f_ in _REF_FREQS]
        delta = np.array(compute_tone_curve(bed, SR, strength=1.0,
                                            raw_spectrum=dark, cutoff_hz=12000.0))
        above = _REF_FREQS >= 0.9 * 12000.0
        assert np.all(delta[above] <= 1e-9)
        assert np.any(delta[~above] > 0.0)

    def test_post_filter_lift_is_capped(self):
        from shimmer.engine import apply_post_filters
        rng = np.random.default_rng(0)
        x = (0.05 * rng.standard_normal((SR * 4, 2))).astype(np.float32)
        p = Params(high_shelf_hz=9000.0, high_shelf_db=2.5)
        y_free = apply_post_filters(x, SR, p)
        p.cutoff_hz = 13000.0
        y_cap = apply_post_filters(x, SR, p)
        assert _bin_level_db(y_cap, SR, 18000.0) < _bin_level_db(y_free, SR, 18000.0) - 3.0


class TestChainPlacement:
    def test_repairs_sit_between_trim_and_tone_curve(self):
        mp = master_params_from_json({"enabled": True})
        chain = build_chain(get_preset("sibilance_rattle"), mp,
                            repair={"enabled": True, "notches": [
                                {"hz": 17700.0, "depth_db": 12.0},
                                {"hz": 19945.0, "depth_db": 9.0}]})
        ids = [m["id"] for m in chain["modules"]]
        assert ids[:4] == ["trim", "declick", "repair", "tone"]
        mods = {m["id"]: m for m in chain["modules"]}
        assert mods["declick"]["active"] is True
        assert "2 tones" in mods["repair"]["badges"]
        assert mods["repair"]["active"] is True
        chain2 = build_chain(get_preset("generic"), mp, repair={"enabled": False})
        m2 = {m["id"]: m for m in chain2["modules"]}
        assert m2["declick"]["active"] is False
        assert m2["repair"]["active"] is False
