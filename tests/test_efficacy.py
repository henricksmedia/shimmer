"""
Efficacy tests: do the presets remove the artifact they are aimed at, and
what does it cost — measured against ground truth (a clean host plus a
modelled artifact), never against the detector's own prior.

Two layers:

  * the artifact models themselves (shimmer/artifacts.py): deterministic,
    in the band they claim, and audible to the hearing model and to the
    detector's evidence when injected loud enough;
  * relations over the committed harness result
    (docs/efficacy-harness.json, from scripts/efficacy_harness.py). These
    assert *relations* — inert presets read zero, the static repair removes
    a fixed line, Deep Scrub costs more than the surgical presets, cost on a
    clean host is no higher than on the render — not invented thresholds.
    They are skipped when the file is absent.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_efficacy.py -q
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest
from scipy import signal as ss

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer import artifacts as A               # noqa: E402
from shimmer.perceptual import measure_damage    # noqa: E402

SR = 48000
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HARNESS = os.path.join(ROOT, "docs", "efficacy-harness.json")
STRENGTH = os.path.join(ROOT, "docs", "efficacy-strength.json")


def _host(seconds: float = 4.0, seed: int = 0) -> np.ndarray:
    """Pink-ish stereo bed with a slow envelope: something for `shadow` to
    follow and for the ear model to be masked by."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    sos = ss.butter(2, [80.0, 6000.0], btype="bandpass", fs=SR, output="sos")
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 1.3 * t) ** 2
    x = np.stack([ss.sosfilt(sos, rng.standard_normal(n)) for _ in range(2)], axis=1)
    return (0.2 * x * env[:, None]).astype(np.float32)


def _band_share(x: np.ndarray, lo: float, hi: float) -> float:
    mono = x.mean(axis=1)
    f, P = ss.welch(mono, fs=SR, nperseg=2048)
    m = (f >= lo) & (f < hi)
    return float(P[m].sum() / P.sum())


class TestArtifactModels:
    @pytest.mark.parametrize("name", sorted(A.GENERATORS))
    def test_deterministic_and_stereo(self, name):
        h = _host()
        a = A.make(name, h.shape[0], SR, host=h)
        b = A.make(name, h.shape[0], SR, host=h)
        assert a.shape == (h.shape[0], 2) and a.dtype == np.float32
        assert np.array_equal(a, b)

    @pytest.mark.parametrize("name,lo,hi", [
        ("hash", 4500.0, 12000.0), ("fizz", 8000.0, 18000.0),
        ("shadow", 3000.0, 10000.0), ("sibilance", 5000.0, 9000.0),
    ])
    def test_noise_models_sit_in_their_band(self, name, lo, hi):
        h = _host()
        a = A.make(name, h.shape[0], SR, host=h)
        assert _band_share(a, lo, hi) > 0.9

    def test_line_is_at_its_frequency(self):
        a = A.make("line", SR * 2, SR)
        f, P = ss.welch(a[:, 0], fs=SR, nperseg=8192)
        assert abs(f[int(np.argmax(P))] - 16000.0) < 10.0

    def test_comb_teeth_are_evenly_spaced(self):
        a = A.make("comb", SR * 2, SR)
        f, P = ss.welch(a[:, 0], fs=SR, nperseg=16384)
        peaks, _ = ss.find_peaks(10 * np.log10(P + 1e-18), prominence=20.0)
        hz = f[peaks]
        hz = hz[(hz > 2400.0) & (hz < 18000.0)]
        assert len(hz) >= 10
        assert np.allclose(np.diff(hz), 600.0, atol=6.0)

    def test_shadow_is_silent_where_the_host_is(self):
        h = _host()
        h[SR:2 * SR] = 0.0
        a = A.make("shadow", h.shape[0], SR, host=h)
        assert float(np.abs(a[SR + 2000:2 * SR - 2000]).max()) < 1e-3 * float(np.abs(a).max())

    def test_hash_registers_on_the_hearing_model_and_the_detector(self):
        """Injected at a plainly audible level, the hash model must be seen
        by both instruments; otherwise the harness would be measuring the
        removal of something nobody can hear."""
        from shimmer.detect import evidence_scan
        import test_detect as T
        # The detector's music bed: a noise-only host flickers on its own
        # in the body band, which would hide the injection from a measure
        # that reads brilliance flicker against body flicker.
        h = T._music(6.0)
        a = A.make("hash", h.shape[0], T.SR, host=h)
        a = a / np.abs(a).max() * np.abs(h).max() * 0.3
        d = measure_damage(h, h + a, T.SR)
        assert d.added > 0.5, d.as_dict()
        before = evidence_scan(h, T.SR).evidence.flicker_excess_db
        after = evidence_scan(h + a, T.SR).evidence.flicker_excess_db
        assert after > before + 1.0, (before, after)


def _rows(path):
    if not os.path.exists(path):
        pytest.skip(f"{os.path.relpath(path, ROOT)} not present; run scripts/efficacy_harness.py")
    return json.load(open(path, encoding="utf-8"))["rows"]


def _mean(rows, key):
    return float(np.mean([r[key] for r in rows]))


@pytest.fixture(scope="module")
def rows():
    return [r for r in _rows(HARNESS) if r["strength"] == 1.0]


@pytest.fixture(scope="module")
def top(rows):
    return max(r["level"] for r in rows)


@pytest.fixture(scope="module")
def sweep_rows():
    return _rows(STRENGTH)


class TestHarnessRelations:
    """Relations over the committed harness result."""

    def test_static_repair_removes_a_fixed_line(self, rows, top):
        rs = [r for r in rows if r["preset"] == "static_repair" and r["artifact"] == "line"
              and r["level"] == top]
        assert rs and _mean(rs, "efficacy") > 0.8, [(r["host"], r["efficacy"]) for r in rs]

    def test_generic_is_the_inert_baseline(self, rows, top):
        """Generic runs a tone killer only, so on every noise-like model it
        must read as doing nothing: efficacy at zero, cost at zero. This is
        what an inert preset looks like; the aimed presets are read against
        it."""
        rs = [r for r in rows if r["preset"] == "generic" and r["level"] == top
              and r["artifact"] in ("hash", "fizz", "shadow", "sibilance")]
        assert rs
        assert abs(_mean(rs, "efficacy")) < 0.05, [(r["artifact"], r["efficacy"]) for r in rs]
        assert _mean(rs, "cost_missing") < 0.01

    @pytest.mark.parametrize("an", [
        "comb", "fizz", "hash", "line", "whistle",
        pytest.param("sibilance", marks=pytest.mark.xfail(
            strict=True,
            reason="Measured 2026-09-08: Sibilance Rattle reads -6% on centred "
                   "sibilant bursts at 2.0 sones (-3% at 0.5) while costing more "
                   "music than any other single preset. The bursts are centred, "
                   "as a vocal is, and Mid is cleaned at 0.2x; the de-esser's "
                   "depth is also scaled down by the transient weight the burst "
                   "itself trips (PRESET_REVIEW.md 2.4). Strict.")),
        # shadow passes, barely: the best aimed preset removes 7% of the
        # signal-following residue at 2.0 sones (Presence Haze), the others
        # 2-5%. The presets aimed at it learn a noise floor in quiet frames
        # and this residue has none. The size is in the checklist.
        "shadow",
    ])
    def test_some_aimed_preset_beats_the_inert_baseline(self, rows, top, an):
        """For each artifact, at least one preset aimed at it removes more
        of it than Generic does. This is the weakest claim a repair tool
        can make about itself; the sizes are in the harness output and the
        checklist, not here."""
        aimed = [r for r in rows if r["level"] == top and r["targeted"]
                 and r["artifact"] == an]
        gen = [r for r in rows if r["level"] == top and r["preset"] == "generic"
               and r["artifact"] == an]
        assert aimed and gen
        best = max(_mean([r for r in aimed if r["preset"] == pn], "efficacy")
                   for pn in {r["preset"] for r in aimed})
        assert best > _mean(gen, "efficacy") + 0.05, (an, best)

    def test_efficacy_never_exceeds_one(self, rows):
        assert max(r["efficacy"] for r in rows) <= 1.0 + 1e-6

    @pytest.mark.parametrize("pn", [
        "air_brittle", "broadband_fizz", "cymbal_chatter",
        "cymbal_sheen", "deep_scrub", "echo_sheen", "generic", "harsh_veil",
        "laser_whistle", "phantom_cymbal", "presence_haze", "sibilance_rattle",
        "suno_hash", "vocal_glaze", "vocal_glaze_plus",
        pytest.param("reverb_flutter", marks=pytest.mark.xfail(
            strict=True,
            reason="Measured 2026-09-08: Reverb Flutter takes 0.089 sones of "
                   "music from a render against 0.008 from the clean host. Its "
                   "random-phase resynth is keyed by flatness, and any "
                   "noise-like artifact opens it onto the music. Strict.")),
        pytest.param("checkerboard_grid", marks=pytest.mark.xfail(
            strict=True,
            reason="Measured 2026-09-08: on the comb it is aimed at, "
                   "Checkerboard Grid takes 0.146 sones of music against 0.004 "
                   "from the clean host, and removes -1% of the comb. The "
                   "per-frame comb suppressor fires on the teeth and cuts the "
                   "music between them. Strict.")),
    ])
    def test_the_artifact_does_not_make_a_preset_take_more_music(self, rows, top, pn):
        """Net cost on the render (music removed, with the artifact's own
        masking subtracted) must not exceed what the same preset takes from
        the clean host by more than a small margin. A preset whose music
        cost jumps when an artifact is present is being driven by the
        artifact into the music, which is the over-reach the assessment
        describes. Judged on the artifacts the preset is aimed at, where it
        is supposed to respond; on all artifacts for presets aimed at none."""
        rs = [r for r in rows if r["preset"] == pn and r["level"] == top and r["targeted"]]
        if not rs:
            rs = [r for r in rows if r["preset"] == pn and r["level"] == top]
        assert rs
        ctrl = float(np.mean([r["control"]["missing"] for r in rs]))
        net = _mean(rs, "cost_missing")
        assert net <= ctrl + 0.05, (pn, ctrl, net)

    def test_deep_scrub_costs_more_than_every_surgical_preset(self, rows, top):
        # reverb_flutter is not in this list: on renders it takes more music
        # than Deep Scrub does (see the strict xfail above).
        surgical = ("cymbal_sheen", "laser_whistle", "checkerboard_grid",
                    "cymbal_chatter", "air_brittle")
        rs = [r for r in rows if r["level"] == top]
        deep = _mean([r for r in rs if r["preset"] == "deep_scrub"], "cost_missing")
        for pn in surgical:
            assert _mean([r for r in rs if r["preset"] == pn], "cost_missing") < deep, pn

    def test_cost_is_measured_against_the_host_not_the_artifact(self, rows, top):
        """Removing the artifact alone must not register as cost: on a row
        where a preset removed most of the artifact, its cost against the
        host is bounded by what the same preset does to the clean host plus
        the residue, not by the artifact's size."""
        rs = [r for r in rows if r["level"] == top and r["efficacy"] > 0.6
              and r["preset"] != "static_repair"]
        if not rs:
            pytest.skip("no preset removed more than 60% of any artifact")
        for r in rs:
            assert r["cost_missing"] < 0.5 * r["injected_added"] + r["control"]["missing"] + 0.05, r


class TestStrengthRelations:
    def test_tilt_cost_rises_with_strength(self, sweep_rows):
        """More strength, more tilt: the one cost every preset pays as it
        is turned up. Asserted on the clean-host control, where no artifact
        confounds it (on a render the artifact's own tilt shrinks as it is
        removed, so the raw figure can fall). Audible-content cost is not
        monotonic for every preset — a de-esser's is not — so it is not
        asserted."""
        rows = sweep_rows
        for pn in sorted({r["preset"] for r in rows if r["preset"] != "static_repair"}):
            by = {}
            for r in rows:
                if r["preset"] == pn:
                    by.setdefault(r["strength"], []).append(r["control"]["lin_dist"])
            s = sorted(by)
            tilt = [float(np.mean(by[k])) for k in s]
            assert tilt == sorted(tilt), (pn, dict(zip(s, tilt)))
