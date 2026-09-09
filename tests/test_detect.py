"""
Auto-detect (detect.py) tests.

The old scorer recommended the same presence-band presets for every
file and did not respond when a clip was cleaned with its own pick.
These tests inject known artifact shapes into a music-like signal and
check that:

  * the ranking changes with the artifact that is actually present,
  * the evidence scan measures that artifact in calibrated units,
  * a recommended strength comes back with the pick,
  * the hot window lands where the artifact lives,
  * the verification split behaves on trivial inputs,
  * the verified score is net audible benefit: a preset cannot score by
    removing a lot, and finished masters get no recommendation.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_detect.py -q
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer import detect  # noqa: E402

SR = 44100

TONAL = {"cymbal_sheen", "laser_whistle"}
HASH = {"suno_hash", "vocal_glaze_plus", "deep_scrub", "harsh_veil",
        "phantom_cymbal", "echo_sheen", "presence_haze", "vocal_glaze",
        "sibilance_rattle", "broadband_fizz"}

# A small candidate list keeps each verification under a few seconds.
FAST = dict(candidates=["cymbal_sheen", "laser_whistle", "suno_hash",
                        "broadband_fizz", "presence_haze", "harsh_veil"],
            window_s=4.0, tune_top=1, follow_up=False)


def _music(seconds: float, seed: int = 0, hits: bool = True) -> np.ndarray:
    """Stereo music-ish bed: bass, a chord that changes every half second,
    drum-like hits (optional), and low-level decorrelated HF noise."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    bass = 0.25 * np.sin(2 * np.pi * 82.4 * t)
    chord = np.zeros(n)
    roots = [220.0, 261.6, 329.6, 293.7]
    for i in range(int(seconds * 2)):
        s0, s1 = int(i * SR / 2), int((i + 1) * SR / 2)
        f0 = roots[i % len(roots)]
        seg_t = t[s0:s1]
        for h in range(1, 12):
            chord[s0:s1] += (0.12 / h) * np.sin(2 * np.pi * f0 * h * seg_t)
    hits_sig = np.zeros(n)
    if hits:
        for i in range(int(seconds * 4)):
            s0 = int(i * SR / 4)
            dur = int(0.03 * SR)
            env = np.exp(-np.arange(dur) / (0.008 * SR))
            hits_sig[s0:s0 + dur] += 0.5 * env * rng.standard_normal(dur)
    # Continuous top-end texture (cymbal wash / room) so the high band is
    # occupied between hits, as in a real mix, with a slow random level
    # drift rather than a flat floor.
    from scipy import signal as ss
    sos = ss.butter(2, [2500.0, 16000.0], btype="bandpass", fs=SR, output="sos")
    drift = 1.0 + 0.3 * np.sin(2 * np.pi * 0.7 * t)
    hf = np.stack([ss.sosfilt(sos, rng.standard_normal(n)) for _ in range(2)], axis=1)
    hf *= 0.03 * drift[:, None]
    left = bass + chord + hits_sig + hf[:, 0]
    right = bass + chord + hits_sig + hf[:, 1]
    return np.stack([left, right], axis=1).astype(np.float32)


def _tone(seconds: float, hz: float, level: float, seed: int = 1) -> np.ndarray:
    n = int(SR * seconds)
    t = np.arange(n) / SR
    s = level * np.sin(2 * np.pi * hz * t)
    return np.stack([s, 0.7 * s], axis=1).astype(np.float32)


def _hash(seconds: float, level: float, seed: int = 2) -> np.ndarray:
    """Amplitude-flickering narrowband noise in 5-9 kHz (Suno hash).

    20 Hz flicker sits inside the 10-50 Hz range Suno hash modulates
    at; the detector measures it on a short 1024/256 grid because it
    averages out inside the engine's 93 ms frames."""
    from scipy import signal as ss
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    sos = ss.butter(4, [5000.0, 9000.0], btype="bandpass", fs=SR, output="sos")
    out = np.zeros((n, 2), dtype=np.float32)
    for c in range(2):
        nz = ss.sosfilt(sos, rng.standard_normal(n))
        am = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 20.0 * t + c))
        out[:, c] = level * nz * am
    return out


@pytest.fixture(scope="module")
def bed():
    return _music(6.0)


@pytest.fixture(scope="module")
def tonal_result(bed):
    x = bed + _tone(6.0, 11200.0, 0.02)
    return detect.suggest_array(x, SR, **FAST)


@pytest.fixture(scope="module")
def hash_result(bed):
    # Level puts the hash a few dB above the bed's own 5-9 kHz texture,
    # as audible Suno hash does in quieter passages.
    x = bed + _hash(6.0, 0.09)
    return detect.suggest_array(x, SR, **FAST)


@pytest.fixture(scope="module")
def clean_result(bed):
    return detect.suggest_array(bed, SR, **FAST)


class TestEvidence:
    def test_steady_tone_is_measured(self, tonal_result):
        ev = tonal_result["evidence"]
        best = max(ev["tones"], key=lambda t: t["excess_db"], default=None)
        assert best is not None
        assert abs(best["hz"] - 11200.0) < 60.0
        assert best["excess_db"] > 6.0
        assert best["duty"] > 0.8

    def test_clean_bed_has_no_eligible_tone(self, clean_result):
        # The bed's chords share a partial near 2.6 kHz that is present
        # most of the time; it may appear in the raw list, but it must
        # never qualify as a generator line (below 3 kHz the rule needs
        # >= 10 dB and >= 90 % duty) and must not be notched.
        ev = clean_result["evidence"]
        tones = [detect.Tone(t["hz"], t["excess_db"], t["duty"], t.get("kind", "line"))
                 for t in ev["tones"]]
        assert detect.eligible_tones(tones) == []
        assert clean_result["repair_plan"]["notches"] == []
        assert clean_result["metrics"]["repair_notches"] == 0

    def test_flicker_is_measured(self, hash_result, clean_result):
        fh = hash_result["evidence"]["flicker_excess_db"]
        fc = clean_result["evidence"]["flicker_excess_db"]
        assert fh > fc + 1.0

    def test_timeline_shape(self, tonal_result):
        tl = tonal_result["timeline"]["intensity"]
        assert len(tl) == 6
        assert all(0.0 <= v <= 1.0 for v in tl)


class TestRanking:
    def test_fixed_line_goes_to_static_repair(self, tonal_result):
        # Since Phase 1 a fixed line is not a preset's job: the whole-file
        # scan puts it in the static-repair plan, the trial cleans run on
        # the repaired clip, and the pick is about whatever residue is
        # left. The plan must carry the line at a useful depth.
        plan = tonal_result["repair_plan"]
        assert plan["enabled"] is True
        hit = [n for n in plan["notches"] if abs(n["hz"] - 11200.0) < 40.0]
        assert len(hit) == 1
        assert hit[0]["depth_db"] >= 5.0
        assert tonal_result["metrics"]["repair_notches"] >= 1
        assert any("Static Notches will cut" in n for n in tonal_result["notes"])

    def test_hash_does_not_rank_tonal_preset_first(self, hash_result):
        assert hash_result["preset"] not in TONAL
        assert hash_result["preset"] in HASH

    def test_rankings_differ_between_artifacts(self, tonal_result, hash_result):
        top_t = [e["name"] for e in tonal_result["ranked"][:3]]
        top_h = [e["name"] for e in hash_result["ranked"][:3]]
        assert top_t != top_h

    def test_ranked_carries_verification_fields(self, hash_result):
        e = hash_result["ranked"][0]
        for key in ("strength", "artifact_db", "collateral_db", "missing",
                    "lin_dist", "added", "net_db", "reason", "confidence",
                    "score"):
            assert key in e
        assert e["missing"] >= 0.0 and e["lin_dist"] >= 0.0
        assert "noise, not music" not in e["reason"]
        assert hash_result["metrics"]["verified"] is True
        assert hash_result["metrics"]["verify_runs"] >= len(FAST["candidates"])

    def test_up_to_six_matches(self, tonal_result):
        assert 1 <= len(tonal_result["ranked"]) <= 6

    def test_clean_bed_has_no_tone_term(self, clean_result, tonal_result):
        # No steady tone in the bed -> the tone-kill term is switched off
        # and no tonal preset can win on tone evidence.
        assert clean_result["metrics"].get("tone_weight", 0.0) == 0.0
        assert clean_result["ranked"][0]["name"] not in TONAL
        # The tonal bed's line is notched before the trial cleans, so no
        # tone term is needed there either; the plan carries it instead.
        assert tonal_result["metrics"].get("tone_weight", 0.0) == 0.0
        assert tonal_result["metrics"]["repair_notches"] >= 1

    def test_confidences_descend(self, hash_result):
        confs = [e["confidence"] for e in hash_result["ranked"]]
        assert confs == sorted(confs, reverse=True)


class TestStrength:
    def test_strength_is_recommended_and_bounded(self, hash_result):
        s = hash_result["strength"]
        assert detect.STRENGTH_MIN <= s <= detect.STRENGTH_MAX
        assert abs(s / detect.STRENGTH_STEP - round(s / detect.STRENGTH_STEP)) < 1e-6
        assert hash_result["ranked"][0]["strength"] == s

    def test_sweep_is_reported_for_top_pick(self, hash_result):
        sweep = hash_result["ranked"][0].get("strength_sweep")
        assert sweep is not None
        assert len(sweep) >= 4
        assert "1.00" in sweep

    def test_pick_prefers_gentlest_within_tolerance(self):
        M = detect.Measure
        base = M(-20.0, -30.0, -21.0, missing=0.05, lin_dist=0.3)
        results = {
            0.5: M(-22.0, -32.0, -23.0, missing=0.03, lin_dist=0.2),
            1.0: base,
            1.5: M(-19.0, -29.0, -20.5, missing=0.052, lin_dist=0.31),  # within tolerance
            2.0: M(-18.0, -26.0, -20.0, missing=0.08, lin_dist=0.5),    # more removed, more tilt
        }
        assert detect._pick_strength(results, base, prior=1.0) == 1.0

    def test_pick_rejects_collateral_jump(self):
        M = detect.Measure
        base = M(-20.0, -30.0, -21.0, missing=0.05, lin_dist=0.3)
        results = {
            1.0: base,
            2.0: M(-15.0, -22.0, -15.0, missing=0.09, lin_dist=0.3),   # better score, +8 dB collateral
        }
        assert detect._pick_strength(results, base, prior=1.0) == 1.0


class TestWindow:
    def test_hot_window_finds_the_artifact(self):
        x = _music(10.0)
        burst = _hash(10.0, 0.12)
        burst[: int(6.0 * SR)] = 0.0          # artifact only in seconds 6-10
        r = detect.suggest_array(x + burst, SR, verify=False, window_s=3.0)
        assert r["metrics"]["window_start_s"] >= 5.0


class TestVerificationSplit:
    def test_sustained_runs(self):
        m = np.array([[1, 1, 1, 1, 0, 1, 1, 0, 1, 1, 1, 1, 1]], dtype=bool)
        out = detect._sustained_runs(m, 4)
        assert out.tolist() == [[1, 1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1]]

    def test_zero_removal_scores_nothing(self, bed):
        clip = bed[: int(3.0 * SR)]
        masks = detect.build_masks(clip, SR)
        meas = detect.measure_removed(np.zeros_like(clip), SR, masks, processed=clip)
        assert meas.artifact_db < -100.0
        assert meas.missing < 0.01 and meas.lin_dist < 0.01
        assert detect.verified_score(meas, prior=1.0) == 0.0

    def test_removing_everything_is_all_cost(self, bed):
        # Silence out of a full clip: the energy measure says collateral, the
        # hearing model says a lot went missing, and the score is zero even
        # with full evidence, because nothing audible was kept.
        clip = bed[: int(3.0 * SR)]
        masks = detect.build_masks(clip, SR)
        meas = detect.measure_removed(clip, SR, masks, processed=np.zeros_like(clip))
        assert meas.collateral_db > -20.0
        assert meas.missing > detect.MISSING_FULL_SONES
        assert detect.verified_score(meas, prior=1.0) == 0.0


class TestVerifiedScore:
    """The score is net audible benefit. Each case is a Measure built by
    hand so the arithmetic is visible; the corpus checks are below."""

    def test_no_evidence_earns_nothing_however_much_is_removed(self):
        meas = detect.Measure(-15.0, -40.0, -16.0, missing=0.5, lin_dist=0.0)
        assert detect.verified_score(meas, prior=0.0) == 0.0
        assert detect.verified_score(meas, prior=0.5) == 0.0

    def test_removing_a_lot_does_not_score_well(self):
        # Same evidence; more audible removal with the tilt that comes with
        # it scores lower, not higher, once the tilt ceiling is reached.
        modest = detect.Measure(-25.0, -40.0, -26.0, missing=0.05, lin_dist=0.3)
        greedy = detect.Measure(-12.0, -30.0, -14.0, missing=0.5, lin_dist=4.0)
        assert detect.verified_score(modest, prior=1.0) > 0.0
        assert detect.verified_score(greedy, prior=1.0) == 0.0

    def test_tilt_is_always_a_cost(self):
        flat = detect.Measure(-20.0, -40.0, -21.0, missing=0.08, lin_dist=0.0)
        tilted = detect.Measure(-20.0, -40.0, -21.0, missing=0.08, lin_dist=1.5)
        assert detect.verified_score(tilted, prior=1.0) < detect.verified_score(flat, prior=1.0)

    def test_inaudible_removal_scores_nothing(self):
        # Energy went from the eligible cells but the hearing model saw
        # nothing go: the old purity score would have credited this.
        meas = detect.Measure(-22.0, -60.0, -22.0, missing=0.0, lin_dist=0.0)
        assert detect.verified_score(meas, prior=1.0) == 0.0

    def test_tone_kill_is_benefit(self):
        meas = detect.Measure(-40.0, -60.0, -40.0, missing=0.0, lin_dist=0.0,
                              tone_removed=0.9)
        assert detect.verified_score(meas, prior=0.0, tone_weight=0.4) == pytest.approx(0.36)

    def test_score_is_bounded(self):
        meas = detect.Measure(-10.0, -30.0, -12.0, missing=5.0, lin_dist=0.0,
                              tone_removed=1.0)
        assert detect.verified_score(meas, prior=1.0, tone_weight=0.4) == 1.0


REFERENCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "assets", "reference")
REFERENCE_FILES = sorted(
    os.path.join(REFERENCE_DIR, f) for f in os.listdir(REFERENCE_DIR)
    if f.lower().endswith(".wav")) if os.path.isdir(REFERENCE_DIR) else []


@pytest.mark.skipif(not REFERENCE_FILES, reason="assets/reference/*.wav not present")
@pytest.mark.parametrize("path", REFERENCE_FILES, ids=os.path.basename)
def test_finished_master_gets_no_recommendation(path):
    """A finished commercial master has nothing for a cleaning preset to
    do. The old score recommended one on every file here at 0.56-0.69
    confidence. Whole-file, all candidates, so the check is the product's."""
    r = detect.suggest(path)
    assert r["metrics"]["verified"] is True
    top = r["ranked"][0]
    assert r["preset"] == "generic", (r["preset"], top)
    assert top["confidence"] == 0.0

    def test_no_verify_falls_back_to_priors(self, bed):
        x = bed + _tone(6.0, 11200.0, 0.02)
        r = detect.suggest_array(x, SR, verify=False)
        assert r["metrics"]["verified"] is False
        assert r["ranked"][0]["name"] in TONAL
        assert r["strength"] == 1.0


def test_the_automated_flow_is_one_pass_by_default():
    """The routine second pass is retired (checklist item 8): the default
    is one pass, and a result produced with the default carries no
    follow-up. It can still be asked for."""
    import inspect
    assert inspect.signature(detect.suggest_array).parameters["follow_up"].default is False
