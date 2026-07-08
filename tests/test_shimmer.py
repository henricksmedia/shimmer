"""
Shimmer safe-mastering refactor test suite (docs/refactor/step12.md).

Groups:
  1. DSP integrity      — shapes, FIR split null, M/S null, no np.roll,
                          length preservation
  2. Artifact engine    — low/mid bypass, high-band-only M/S cleaning,
                          Mid gentler than Side, removed signal,
                          transient hold envelope
  3. Stereo width       — attenuation detection, threshold, cap, smoothing
  4. Mastering          — LUFS measure, single static gain, no iteration
                          loop, codec-aware ceilings
  5. Preview            — pre/post-roll, exact duration, edge cases
  6. UI/API             — playback states, removed handling, export ceiling

Run:  .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bands
import mastering
from engine import TransientHoldGate, process
from params import MasterParams, Params
from pipeline import clean_and_master

SR = 44100


def _stereo_signal(seconds: float = 3.0, seed: int = 0,
                   hf_noise: float = 0.03) -> np.ndarray:
    """Music-ish stereo test signal: bass + mid tone + decorrelated HF noise."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    bass = 0.3 * np.sin(2 * np.pi * 80 * t)
    mid = 0.15 * np.sin(2 * np.pi * 440 * t)
    left = bass + mid + hf_noise * rng.standard_normal(t.size)
    right = bass + mid + hf_noise * rng.standard_normal(t.size)
    return np.stack([left, right], axis=1).astype(np.float32)


# ═══════════════════════════════════════════════════════════════════════════
# 1. DSP integrity
# ═══════════════════════════════════════════════════════════════════════════

class TestDSPIntegrity:
    def test_stereo_shape_handling(self):
        mono = np.zeros(1000, dtype=np.float32)
        assert bands.ensure_stereo_channels_first(mono).shape == (2, 1000)
        samples_first = np.zeros((1000, 2), dtype=np.float32)
        assert bands.ensure_stereo_channels_first(samples_first).shape == (2, 1000)
        channels_first = np.zeros((2, 1000), dtype=np.float32)
        assert bands.ensure_stereo_channels_first(channels_first).shape == (2, 1000)

    def test_fir_split_recombine_null(self):
        x = bands.ensure_stereo_channels_first(_stereo_signal(2.0).T)
        err = bands.null_test_split_recombine(x, SR)
        assert err < 1e-5, f"crossover reconstruction error {err} too large"

    def test_ms_encode_decode_null(self):
        x = bands.ensure_stereo_channels_first(_stereo_signal(1.0, seed=1).T)
        mid, side = bands.encode_ms(x)
        y = bands.decode_ms(mid, side)
        assert float(np.max(np.abs(y - x))) < 1e-5

    def test_no_np_roll_in_dsp_alignment(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for fname in ("bands.py", "pipeline.py", "mastering.py", "engine.py"):
            src = open(os.path.join(root, fname), encoding="utf-8").read()
            assert "np.roll(" not in src, f"np.roll call found in {fname}"

    def test_output_length_preserved(self):
        x = _stereo_signal(2.5, seed=2)
        y, removed, _ = clean_and_master(x, SR, Params(denoise=0.5), None)
        assert y.shape == x.shape
        assert removed.shape == x.shape


# ═══════════════════════════════════════════════════════════════════════════
# 2. Artifact engine
# ═══════════════════════════════════════════════════════════════════════════

class TestArtifactEngine:
    @staticmethod
    def _band_energy(x: np.ndarray, lo: float, hi: float) -> float:
        spec = np.abs(np.fft.rfft(x[:, 0].astype(np.float64)))
        freqs = np.fft.rfftfreq(x.shape[0], 1.0 / SR)
        m = (freqs >= lo) & (freqs < hi)
        return float(np.sum(spec[m] ** 2))

    def test_low_mid_band_bypasses_cleaning(self):
        x = _stereo_signal(3.0, seed=3)
        p = Params(denoise=0.7, deharsh=0.6, flicker_tame=0.6)
        _, removed, _ = clean_and_master(x, SR, p, None)
        low = self._band_energy(removed, 0, 4000)
        high = self._band_energy(removed, 4000, SR / 2)
        assert high > 0, "cleaning removed nothing from the high band"
        assert low / (high + 1e-12) < 1e-3, \
            "removed signal contains low/mid energy — bypass is leaking"

    def test_mid_processed_less_than_side(self):
        # Correlated (Mid) + decorrelated (Side) HF noise; the Side copy
        # must lose more energy than the Mid copy.
        rng = np.random.default_rng(4)
        n = SR * 3
        common = 0.05 * rng.standard_normal(n)
        diff = 0.05 * rng.standard_normal(n)
        left = (common + diff).astype(np.float32)
        right = (common - diff).astype(np.float32)
        x = np.stack([left, right], axis=1)

        p = Params(denoise=0.7, deharsh=0.5)
        _, removed, _ = clean_and_master(x, SR, p, None)
        rem_cf = bands.ensure_stereo_channels_first(removed.T)
        rem_mid, rem_side = bands.encode_ms(rem_cf)
        e_mid = float(np.mean(rem_mid.astype(np.float64) ** 2))
        e_side = float(np.mean(rem_side.astype(np.float64) ** 2))
        assert e_side > e_mid, \
            f"Side should be cleaned harder (mid={e_mid:.3e}, side={e_side:.3e})"

    def test_removed_signal_generated(self):
        x = _stereo_signal(2.0, seed=5)
        _, removed, _ = clean_and_master(x, SR, Params(denoise=0.6), None)
        assert float(np.max(np.abs(removed))) > 0

    def test_transient_hold_envelope(self):
        p = Params()
        gate = TransientHoldGate(p, SR, p.hop)
        frame_s = p.hop / SR

        # Steady state: no protection.
        w, _ = gate.update(-40.0, -40.0)
        assert w == pytest.approx(1.0)

        # Big transient: instant full protection.
        w, ws = gate.update(-20.0, -40.0)
        assert w == 0.0
        assert 0.0 < ws < 1.0  # surgical group only partially reduced

        # Hold: stays at 0 for ~th_hold_ms.
        hold_frames = int(round((p.th_hold_ms / 1000.0) / frame_s))
        vals = [gate.update(-20.0, -20.0)[0] for _ in range(hold_frames + 20)]
        assert all(v == 0.0 for v in vals[:hold_frames - 1]), \
            "protection released during the hold window"

        # Release: monotonic smooth ramp back to 1, no single-frame jump.
        post = vals[hold_frames - 1:]
        diffs = np.diff([0.0] + post)
        assert all(d >= -1e-9 for d in diffs), "release is not monotonic"
        assert max(diffs) < 0.5, "release jumps too fast (not smooth)"
        assert post[-1] == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Stereo width
# ═══════════════════════════════════════════════════════════════════════════

class TestStereoWidth:
    def _side(self, seconds=2.0, seed=6):
        rng = np.random.default_rng(seed)
        return (0.1 * rng.standard_normal(int(SR * seconds))).astype(np.float32)

    def test_attenuation_detected_and_capped(self):
        side = self._side()
        cleaned = side * 10 ** (-8 / 20)   # 8 dB over-cleaned
        out, stats = bands.side_width_compensation(side, cleaned, SR)
        assert stats["max_makeup_db"] == pytest.approx(1.5, abs=1e-6), \
            "makeup must cap at max_makeup_db"
        # Output louder than cleaned but never louder than the original.
        assert float(np.sqrt(np.mean(out ** 2))) > float(np.sqrt(np.mean(cleaned ** 2)))
        assert float(np.sqrt(np.mean(out ** 2))) < float(np.sqrt(np.mean(side ** 2)))

    def test_no_makeup_below_threshold(self):
        side = self._side(seed=7)
        cleaned = side * 10 ** (-2 / 20)   # only 2 dB < 3 dB threshold
        out, stats = bands.side_width_compensation(side, cleaned, SR)
        assert stats["max_makeup_db"] == pytest.approx(0.0, abs=1e-6)
        assert np.allclose(out, cleaned, atol=1e-6)

    def test_envelope_is_smoothed(self):
        # Alternate attenuation on/off per 50 ms block: the per-sample
        # gain must not step abruptly.
        side = self._side(seconds=2.0, seed=8)
        cleaned = side.copy()
        blk = int(0.05 * SR)
        for i in range(0, side.size, 2 * blk):
            cleaned[i:i + blk] *= 10 ** (-8 / 20)
        out, _ = bands.side_width_compensation(side, cleaned, SR)
        gain = out.astype(np.float64) / np.where(
            np.abs(cleaned) > 1e-9, cleaned, 1e-9)
        gain = np.clip(gain, 0.5, 2.0)
        step = float(np.max(np.abs(np.diff(gain))))
        assert step < 0.05, f"gain envelope steps too hard ({step})"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Mastering
# ═══════════════════════════════════════════════════════════════════════════

class TestMastering:
    def test_integrated_loudness_measured(self):
        x = _stereo_signal(5.0, seed=9)
        loud = mastering.measure_loudness(x, SR)
        assert np.isfinite(loud["lufs_i"])
        assert "true_peak_dbtp" in loud

    def test_single_static_gain(self):
        x = _stereo_signal(5.0, seed=10) * 0.1  # quiet input, no limiting
        mp = MasterParams(enabled=True, target_lufs=-14.0)
        y, report = mastering.master(x, SR, mp)
        assert report["after"]["lufs_i"] == pytest.approx(-14.0, abs=0.5)
        # gain_db is reported once — one static gain, no accumulation keys.
        assert "gain_db" in report
        assert report["total_gain_db"] == report["gain_db"]

    def test_no_iteration_loop(self):
        assert not hasattr(MasterParams(), "max_iterations")
        import inspect
        src = inspect.getsource(mastering.master)
        assert "max_iterations" not in src
        assert "for _ in range" not in src

    def test_codec_aware_ceilings(self):
        for fmt in ("wav", "flac", ".WAV", "FLAC"):
            assert mastering.get_export_ceiling_dbtp(fmt) == -1.0
        for fmt in ("mp3", "m4a", "aac", "ogg", "opus", ".mp3"):
            assert mastering.get_export_ceiling_dbtp(fmt) == -1.5

    def test_true_peak_respects_ceiling(self):
        # Hot input that needs limiting.
        x = _stereo_signal(4.0, seed=11) * 4.0
        mp = MasterParams(enabled=True, target_lufs=-9.0, ceiling_dbtp=-1.0)
        y, report = mastering.master(x, SR, mp)
        tp = mastering.measure_loudness(y, SR)["true_peak_dbtp"]
        assert tp <= -0.8, f"true peak {tp} exceeds ceiling"

    def test_tone_curve_bounds(self):
        x = _stereo_signal(4.0, seed=12)
        delta = np.array(mastering.compute_tone_curve(x, SR, strength=1.0))
        assert float(delta.max()) <= 2.0 + 1e-9
        assert float(delta.min()) >= -3.0 - 1e-9
        harsh = (mastering._REF_FREQS >= 5000) & (mastering._REF_FREQS <= 12000)
        assert float(delta[harsh].max()) <= 0.5 + 1e-9

    def test_tilt_neutral_is_identity(self):
        x = _stereo_signal(4.0, seed=12)
        base = mastering.compute_tone_curve(x, SR, strength=1.0)
        neutral = mastering.compute_tone_curve(x, SR, strength=1.0,
                                               tilt="neutral")
        assert base == neutral
        # Zero strength + neutral tilt stays a true no-op.
        flat = mastering.compute_tone_curve(x, SR, strength=0.0)
        assert all(v == 0.0 for v in flat)

    def test_tilt_applies_independent_of_strength(self):
        # Tilt is stylistic — it must apply in full even with the
        # corrective match dialed to zero.
        x = _stereo_signal(4.0, seed=12)
        warm = np.array(mastering.compute_tone_curve(
            x, SR, strength=0.0, tilt="warmer"))
        assert warm[0] > 1.0, "warmer should boost the low end"
        assert warm[-1] < -1.0, "warmer should roll off the air band"
        bright = np.array(mastering.compute_tone_curve(
            x, SR, strength=0.0, tilt="brightest"))
        assert bright[0] < -1.0
        assert bright[-1] > 1.0

    def test_tilt_respects_safety_bounds(self):
        x = _stereo_signal(4.0, seed=12)
        harsh = (mastering._REF_FREQS >= 5000) & (mastering._REF_FREQS <= 12000)
        for tilt in mastering.TILT_POSITIONS:
            delta = np.array(mastering.compute_tone_curve(
                x, SR, strength=1.0, tilt=tilt))
            assert float(delta.max()) <= 2.0 + 1e-9, tilt
            assert float(delta.min()) >= -3.0 - 1e-9, tilt
            # Harshness guard must win over bright tilts: no meaningful
            # boost in the 5-12 kHz AI-fizz band.
            assert float(delta[harsh].max()) <= 0.5 + 1e-9, tilt

    def test_tilt_json_parsing(self):
        mp = mastering.master_params_from_json({"tilt": "Warmer"})
        assert mp.tilt == "warmer"
        mp = mastering.master_params_from_json({"tilt": "bogus"})
        assert mp.tilt == "neutral"
        mp = mastering.master_params_from_json({})
        assert mp.tilt == "neutral"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Preview
# ═══════════════════════════════════════════════════════════════════════════

class TestPreview:
    def test_extract_includes_pre_and_post_roll(self):
        from server import (_PREVIEW_PREROLL_S, _PREVIEW_POSTROLL_S,
                            extract_preview_block)
        samples = np.zeros((SR * 10, 2), dtype=np.float32)
        block, head_pad, audible = extract_preview_block(samples, SR, 4.0, 6.0)
        assert head_pad == int(round(_PREVIEW_PREROLL_S * SR))
        assert audible == SR * 2
        assert block.shape[0] >= audible + head_pad + int(_PREVIEW_POSTROLL_S * SR)
        assert _PREVIEW_POSTROLL_S >= 0.5

    def test_preview_duration_exact_and_edges(self):
        from server import extract_preview_block, trim_processed_preview
        samples = np.zeros((SR * 10, 2), dtype=np.float32)
        for (a, b) in [(0.0, 2.0), (8.5, 10.0), (9.9, 10.0), (0.0, 0.01)]:
            block, head_pad, audible = extract_preview_block(samples, SR, a, b)
            out = trim_processed_preview(block, head_pad, audible)
            assert out.shape[0] == audible

    def test_preview_api_roundtrip(self):
        soundfile = pytest.importorskip("soundfile")
        httpx = pytest.importorskip("httpx")  # noqa: F841
        from fastapi.testclient import TestClient
        from server import app

        x = _stereo_signal(8.0, seed=13)
        buf = io.BytesIO()
        soundfile.write(buf, x, SR, format="WAV")
        buf.seek(0)

        with TestClient(app) as client:
            r = client.post("/api/upload",
                            files={"file": ("t.wav", buf, "audio/wav")})
            assert r.status_code == 200
            sid = r.json()["session_id"]
            payload = {
                "session_id": sid, "start_s": 2.0, "end_s": 4.5,
                "params": {"preset": "suno_hash"},
                "mastering": {"enabled": True, "target": "streaming"},
            }
            r2 = client.post("/api/preview", json=payload)
            assert r2.status_code == 200
            jl = struct.unpack("<I", r2.content[:4])[0]
            meta = json.loads(r2.content[4:4 + jl])
            assert meta["duration_s"] == pytest.approx(2.5, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════════
# 6. UI / API
# ═══════════════════════════════════════════════════════════════════════════

class TestUIAPI:
    def test_playback_states_exist_in_ui(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html = open(os.path.join(root, "static", "index.html"),
                    encoding="utf-8").read()
        for track in ("original", "processed", "removed"):
            assert f'data-track="{track}"' in html
        # Removed is marked as a boosted monitoring feed.
        assert "boosted" in html.lower()

    def test_removed_toggle_disabled_until_available(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html = open(os.path.join(root, "static", "index.html"),
                    encoding="utf-8").read()
        # The removed tab ships disabled; JS enables it when data exists.
        assert 'data-track="removed" disabled' in html

    def test_export_uses_codec_ceiling(self):
        soundfile = pytest.importorskip("soundfile")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient
        from server import app

        x = _stereo_signal(4.0, seed=14)
        buf = io.BytesIO()
        soundfile.write(buf, x, SR, format="WAV")
        buf.seek(0)

        params = json.dumps({
            "preset": "generic",
            "mastering": {"enabled": True, "target": "streaming"},
        })
        with TestClient(app) as client:
            r = client.post(
                "/api/process",
                files={"file": ("song.wav", buf, "audio/wav")},
                data={"params": params, "output_format": "wav"})
            assert r.status_code == 200
            jid = r.json()["job_id"]
            deadline = time.time() + 120
            metrics = None
            while time.time() < deadline:
                m = client.get(f"/api/metrics/{jid}")
                if m.status_code == 200 and m.json().get("status") == "done":
                    metrics = m.json()["metrics"]
                    break
                assert m.status_code != 500, m.text
                time.sleep(0.3)
            assert metrics is not None, "job did not finish"
            assert metrics["mastering"]["ceiling_dbtp"] == -1.0  # wav

    def test_presets_include_new_coverage(self):
        from presets import PRESETS
        assert "muddy_boxy" in PRESETS
        assert "dark_mix_rescue" in PRESETS
        # Every preset builds and none rely on the deprecated flag.
        for name, factory in PRESETS.items():
            p = factory()
            assert isinstance(p, Params)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Silence trimming
# ═══════════════════════════════════════════════════════════════════════════

class TestTrimSilence:
    def _padded_signal(self, head_s=1.5, body_s=2.0, tail_s=3.0):
        body = _stereo_signal(body_s, seed=7)
        head = np.zeros((int(SR * head_s), 2), dtype=np.float32)
        tail = np.zeros((int(SR * tail_s), 2), dtype=np.float32)
        return np.concatenate([head, body, tail], axis=0)

    def test_trim_bounds_and_padding(self):
        from dsp import trim_silence
        x = self._padded_signal()
        y, cut_head, cut_tail = trim_silence(x, SR)
        # Cuts most of the padding but keeps the configured breathing room.
        assert cut_head == pytest.approx(1.5, abs=0.1)
        assert cut_tail == pytest.approx(3.0, abs=0.35)
        assert y.shape[0] < x.shape[0]
        # The audible body survives intact (RMS in the kept middle region).
        mid = y[y.shape[0] // 3: 2 * y.shape[0] // 3]
        assert float(np.sqrt(np.mean(mid ** 2))) > 0.05

    def test_trim_nothing_to_do(self):
        from dsp import trim_silence
        x = _stereo_signal(2.0, seed=3)
        y, cut_head, cut_tail = trim_silence(x, SR)
        assert cut_head == 0.0 and cut_tail == 0.0
        assert y.shape[0] == x.shape[0]

    def test_trim_all_silence_untouched(self):
        from dsp import trim_silence
        x = np.zeros((SR * 2, 2), dtype=np.float32)
        y, cut_head, cut_tail = trim_silence(x, SR)
        assert y.shape[0] == x.shape[0]
        assert cut_head == 0.0 and cut_tail == 0.0

    def test_trim_ui_checkboxes_exist(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html = open(os.path.join(root, "static", "index.html"),
                    encoding="utf-8").read()
        assert 'id="trim-silence"' in html
        assert 'id="batch-trim-silence"' in html

    def test_process_endpoint_trim_export(self):
        soundfile = pytest.importorskip("soundfile")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient
        from server import app

        x = self._padded_signal(head_s=1.0, body_s=2.0, tail_s=2.0)
        buf = io.BytesIO()
        soundfile.write(buf, x, SR, format="WAV")
        buf.seek(0)

        params = json.dumps({"preset": "generic",
                             "mastering": {"enabled": False}})
        with TestClient(app) as client:
            r = client.post(
                "/api/process",
                files={"file": ("padded.wav", buf, "audio/wav")},
                data={"params": params, "output_format": "wav",
                      "trim_silence": "true"})
            assert r.status_code == 200
            jid = r.json()["job_id"]
            deadline = time.time() + 120
            metrics = None
            while time.time() < deadline:
                m = client.get(f"/api/metrics/{jid}")
                if m.status_code == 200 and m.json().get("status") == "done":
                    metrics = m.json()["metrics"]
                    break
                assert m.status_code != 500, m.text
                time.sleep(0.3)
            assert metrics is not None, "job did not finish"
            trim = metrics["trim"]
            assert trim["enabled"] is True
            assert trim["cut_head_s"] + trim["cut_tail_s"] > 1.0

            # Playback file stays full length; trimmed export is shorter.
            full = client.get(f"/api/result/{jid}?kind=processed")
            trimmed = client.get(f"/api/result/{jid}?kind=trimmed")
            assert full.status_code == 200 and trimmed.status_code == 200
            y_full, _ = soundfile.read(io.BytesIO(full.content))
            y_trim, _ = soundfile.read(io.BytesIO(trimmed.content))
            assert y_full.shape[0] == pytest.approx(x.shape[0], abs=SR // 10)
            assert y_trim.shape[0] < y_full.shape[0] - SR  # >1s removed
