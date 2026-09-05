"""
Stem separation plumbing tests (no torch, no Demucs: the worker itself
is exercised by hand in the side venv).

Covers:
  1. stems.py — tiers, the per-model cache layout and the legacy
     migration, the worker's line protocol, residual + null test, the
     per-stem measurements and the loop hint.
  2. server routes — /api/stems/engine and /api/stems/library shapes,
     /api/stems/info, /api/stems/export (ZIP of 24-bit WAVs, as separated
     and through the mixer), and the remix preview/render with lanes
     beyond the classic four (6-stem model + residual).

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_stems.py -q
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import struct
import sys
import zipfile

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shimmer.server as server
import shimmer.stems as stems
from shimmer.jobs import JOB_STORE
from shimmer.preview_store import PREVIEW_STORE
from shimmer.stem_effects import remix_settings_from_json, render_remix, render_stems

SR = 44100


def _tone(freq: float, seconds: float, amp: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    x = amp * np.sin(2 * np.pi * freq * t) + 0.002 * rng.standard_normal(t.size)
    return np.stack([x, x * 0.9], axis=1).astype(np.float32)


# ── 1. stems.py ──────────────────────────────────────────────────────────

def test_tiers_name_real_models_and_default_is_valid():
    assert set(stems.TIERS) >= {"fast", "best", "six"}
    for t in stems.TIERS.values():
        assert t.model and t.shifts >= 0 and t.stems in (4, 6)
        assert t.download_mb > 0 and t.gpu_s_per_min > 0 and t.cpu_s_per_min > t.gpu_s_per_min
    assert stems.default_tier() in stems.TIERS
    assert stems.resolve_tier("nonsense").key == stems.default_tier()
    assert stems.resolve_tier("SIX").model == "htdemucs_6s"


def test_cache_layout_migrates_legacy_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(stems, "STEM_CACHE", tmp_path)
    digest = "a" * 40
    root = tmp_path / digest
    root.mkdir()
    for n in stems.STEM_NAMES:
        (root / f"{n}.wav").write_bytes(b"x")
    (root / "meta.json").write_text(json.dumps({"model": "htdemucs", "source": "input_song.wav"}))
    assert stems.cache_complete(digest, "htdemucs")
    # Migrated in place into the per-model folder.
    assert (root / "htdemucs" / "vocals.wav").is_file()
    assert not (root / "vocals.wav").exists()
    assert stems.cached_models(digest) == ["htdemucs"]
    assert stems.cached_tiers(digest) == ["fast"]
    assert not stems.cache_complete(digest, "htdemucs_ft")
    # A second model with a partial set does not count.
    (root / "htdemucs_ft").mkdir()
    (root / "htdemucs_ft" / "vocals.wav").write_bytes(b"x")
    assert stems.cached_models(digest) == ["htdemucs"]
    lib = stems.library()
    assert lib and lib[0]["digest"] == digest
    assert lib[0]["name"] == "song.wav" and lib[0]["models"] == ["htdemucs"]


def test_cache_complete_honours_meta_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(stems, "STEM_CACHE", tmp_path)
    digest = "b" * 40
    d = tmp_path / digest / "htdemucs_6s"
    d.mkdir(parents=True)
    srcs = ["drums", "bass", "other", "vocals", "guitar", "piano"]
    (d / "meta.json").write_text(json.dumps({"model": "htdemucs_6s", "sources": srcs}))
    for n in srcs[:-1]:
        (d / f"{n}.wav").write_bytes(b"x")
    assert not stems.cache_complete(digest, "htdemucs_6s")
    (d / "piano.wav").write_bytes(b"x")
    assert stems.cache_complete(digest, "htdemucs_6s")


def test_runner_line_protocol():
    assert stems._parse_runner_line('{"event": "progress", "fraction": 0.5}\n') == {
        "event": "progress", "fraction": 0.5}
    # tqdm redraws share a physical line; the last frame is the one that counts.
    assert stems._parse_runner_line(' 10%|#  \r 50%|##### \r{"event": "status", "message": "x"}\n')["message"] == "x"
    assert stems._parse_runner_line("Downloading: 100%|######|\n") is None
    assert stems._parse_runner_line('{"no_event": 1}') is None
    assert stems._parse_runner_line("{not json") is None


def test_residual_makes_the_sum_exact():
    mix = _tone(220, 2.0, 0.3, seed=1) + _tone(440, 2.0, 0.2, seed=2)
    vocals = _tone(440, 2.0, 0.2, seed=2)
    other = _tone(220, 2.0, 0.3, seed=1) * 0.97      # the separator lost 3 %
    residual, null_db = stems.add_residual({"vocals": vocals, "other": other}, mix)
    assert residual.shape == mix.shape
    np.testing.assert_allclose(vocals + other + residual, mix, atol=1e-6)
    # 3 % of one component ≈ −30 dB; comfortably below −20 and above −60.
    assert -45 < null_db < -20
    # A perfect split nulls very deep.
    _, perfect = stems.add_residual({"a": vocals, "b": mix - vocals}, mix)
    assert perfect < -80


def test_measure_stems_shares_peaks_and_loop_hint():
    quiet = _tone(220, 30.0, 0.05, seed=3)
    loud = _tone(330, 30.0, 0.15, seed=4)
    # Drums only play in the last 12 s: the busiest 10 s window is there.
    drums = np.zeros_like(loud)
    drums[int(18 * SR):] = _tone(80, 12.0, 0.2, seed=5)
    mix = quiet + loud + drums
    info = stems.measure_stems({"vocals": loud, "other": quiet, "drums": drums}, mix, SR,
                               columns=200, loop_s=10.0)
    assert info["order"] == ["vocals", "drums", "other"]
    by = {s["key"]: s for s in info["stems"]}
    assert len(by["vocals"]["peaks"]) == 200 and len(info["mix_peaks"]) == 200
    assert 0.99 < sum(s["share"] for s in info["stems"]) < 1.01
    assert by["vocals"]["share"] > by["other"]["share"]
    assert by["vocals"]["rms_db"] > by["other"]["rms_db"]
    assert by["drums"]["peak_db"] > by["other"]["peak_db"]
    assert 17.0 <= info["suggested_loop_s"] <= 20.0
    assert info["duration_s"] == pytest.approx(30.0, abs=0.01)
    assert "null_db" not in info   # no residual lane, no null figure
    res, null_db = stems.add_residual({"vocals": loud, "other": quiet, "drums": drums}, mix)
    info2 = stems.measure_stems({"vocals": loud, "other": quiet, "drums": drums,
                                 "residual": res}, mix, SR, columns=50)
    assert info2["order"][-1] == "residual"
    assert info2["null_db"] < -80


def test_engine_info_shape_without_a_venv(monkeypatch):
    monkeypatch.setattr(stems, "stems_python", lambda: None)
    info = stems.engine_info(check=True)
    assert info["installed"] is False and info["ready"] is None
    keys = {t["key"] for t in info["tiers"]}
    assert keys >= {"fast", "best", "six"}
    for t in info["tiers"]:
        assert t["downloaded"] is False
        assert {"model", "label", "blurb", "download_mb", "gpu_s_per_min"} <= set(t)
    assert info["default_tier"] in keys


# ── 2. Server routes ─────────────────────────────────────────────────────

@pytest.fixture()
def six_stem_session():
    names = ["vocals", "drums", "bass", "guitar", "piano", "other"]
    parts = {n: _tone(110 * (i + 1), 3.0, 0.08, seed=i) for i, n in enumerate(names)}
    mix = sum(parts.values()).astype(np.float32)
    sess = PREVIEW_STORE.create(samples=mix, sr=SR, original_path="unused",
                                original_name="six.wav")
    sess.digest = "c" * 40
    residual, null_db = stems.add_residual(parts, mix)
    parts["residual"] = residual
    sess.stems = parts
    sess.stems_info = {"tier": "six", "model": "htdemucs_6s",
                       **stems.measure_stems(parts, mix, SR, columns=40, null_db=null_db)}
    yield sess
    PREVIEW_STORE.drop(sess.id)


def _drive(coro_factory):
    async def _run():
        resp = await coro_factory()
        job_id = json.loads(resp.body)["job_id"]
        job = JOB_STORE.get(job_id)
        for _ in range(1200):
            if job.status in ("done", "error"):
                break
            await asyncio.sleep(0.05)
        return job
    return asyncio.run(_run())


def test_stems_engine_and_library_routes():
    info = json.loads(asyncio.run(server.api_stems_engine(False)).body)
    assert "tiers" in info and "installed" in info and "gpu" in info
    lib = json.loads(asyncio.run(server.api_stems_library()).body)
    assert isinstance(lib["items"], list)


def test_stems_info_route(six_stem_session):
    info = json.loads(asyncio.run(server.api_stems_info(six_stem_session.id)).body)
    assert info["order"] == ["vocals", "drums", "bass", "guitar", "piano", "other", "residual"]
    assert info["null_db"] < -80
    assert len(info["stems"]) == 7
    status = json.loads(asyncio.run(server.api_stems_status(six_stem_session.id)).body)
    assert status["ready"] is True and status["info"]["model"] == "htdemucs_6s"


def test_stems_info_requires_separation():
    from fastapi import HTTPException
    sess = PREVIEW_STORE.create(samples=_tone(220, 1.0, 0.1), sr=SR,
                                original_path="unused", original_name="x.wav")
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(server.api_stems_info(sess.id))
        assert exc.value.status_code == 409
    finally:
        PREVIEW_STORE.drop(sess.id)


def test_stems_export_as_separated_sums_to_the_mix(six_stem_session):
    sess = six_stem_session
    job = _drive(lambda: server.api_stems_export({"session_id": sess.id}))
    assert job.status == "done", job.error
    assert job.output_ext == ".zip" and os.path.isfile(job.processed_path)
    with zipfile.ZipFile(job.processed_path) as zf:
        names = sorted(zf.namelist())
        assert names == sorted(f"six_{n}.wav" for n in sess.stems)
        total = None
        for n in names:
            x, sr = sf.read(io.BytesIO(zf.read(n)), dtype="float32", always_2d=True)
            assert sr == SR
            total = x if total is None else total + x
    # 24-bit files: the sum matches the original mix to well under 1e-4.
    np.testing.assert_allclose(total, sess.samples[:total.shape[0]], atol=2e-4)
    assert job.metrics["processed"] is False and job.metrics["bit_depth"] == 24
    # The download name marks it as a stems bundle of that model.
    resp = asyncio.run(server.api_result(job.id, "processed"))
    assert resp.media_type == "application/zip"
    assert resp.headers["content-disposition"].endswith(f'six_stems_htdemucs_6s_{job.id[:8]}.zip"')


def test_stems_export_with_mix_applies_strips_and_drops_muted(six_stem_session):
    sess = six_stem_session
    job = _drive(lambda: server.api_stems_export({
        "session_id": sess.id, "processed": True,
        "stems": {"drums": {"mute": True}, "vocals": {"gain_db": -6.0}},
    }))
    assert job.status == "done", job.error
    with zipfile.ZipFile(job.processed_path) as zf:
        names = zf.namelist()
        assert "six_drums.wav" not in names and len(names) == 6
        v, _ = sf.read(io.BytesIO(zf.read("six_vocals.wav")), dtype="float32", always_2d=True)
    ratio = np.sqrt(np.mean(v ** 2)) / np.sqrt(np.mean(sess.stems["vocals"] ** 2))
    assert ratio == pytest.approx(10 ** (-6 / 20), rel=0.02)


def test_stems_export_all_muted_fails_cleanly(six_stem_session):
    sess = six_stem_session
    job = _drive(lambda: server.api_stems_export({
        "session_id": sess.id, "processed": True,
        "stems": {n: {"mute": True} for n in sess.stems},
    }))
    assert job.status == "error" and "muted" in job.error


def test_remix_preview_and_render_use_every_lane(six_stem_session):
    sess = six_stem_session
    resp = asyncio.run(server.api_remix_preview({
        "session_id": sess.id, "start_s": 0.0, "end_s": 2.0,
        "stems": {"residual": {"mute": True}, "guitar": {"gain_db": 6.0}},
    }))
    body = resp.body
    (jlen,) = struct.unpack_from("<I", body, 0)
    meta = json.loads(body[4:4 + jlen])
    assert meta["mastered"] is False and np.isfinite(meta["lufs_remix"])
    # Unity settings reproduce the original slice: residual included.
    resp2 = asyncio.run(server.api_remix_preview({
        "session_id": sess.id, "start_s": 0.5, "end_s": 1.5, "stems": {}}))
    (jlen2,) = struct.unpack_from("<I", resp2.body, 0)
    wav, sr = sf.read(io.BytesIO(resp2.body[4 + jlen2:]), dtype="float32", always_2d=True)
    n0 = int(0.5 * SR)
    np.testing.assert_allclose(wav, sess.samples[n0:n0 + wav.shape[0]], atol=1e-3)

    job = _drive(lambda: server.api_remix_render({
        "session_id": sess.id, "stems": {"piano": {"mute": True}},
        "output_format": "wav", "mastering": {"enabled": False},
        "cleaning": {"preset": "off"},
    }))
    assert job.status == "done", job.error
    assert os.path.isfile(job.processed_path)


def test_pan_is_a_balance_control():
    from shimmer.stem_effects import apply_gain_mute, pan_gains, stem_settings_from_json
    assert pan_gains(0.0) == (1.0, 1.0)
    assert pan_gains(-1.0) == (1.0, 0.0)
    assert pan_gains(0.5) == (0.5, 1.0)
    x = _tone(440, 0.5, 0.2)
    s = stem_settings_from_json({"pan": 0.5})
    assert s.pan == 0.5 and not s.is_identity()
    y = apply_gain_mute(x, s)
    np.testing.assert_allclose(y[:, 0], x[:, 0] * 0.5, atol=1e-6)   # left attenuated
    np.testing.assert_allclose(y[:, 1], x[:, 1], atol=1e-6)         # right untouched
    # Out-of-range and junk values clamp / default.
    assert stem_settings_from_json({"pan": 9}).pan == 1.0
    assert stem_settings_from_json({"pan": "x"}).pan == 0.0
    # Centre pan is the identity, so the untouched mix still nulls.
    centred = apply_gain_mute(x, stem_settings_from_json({"pan": 0.0}))
    assert centred is x


def test_stem_effects_accept_any_lane_names():
    stems_ = {"vocals": _tone(440, 1.0, 0.1), "guitar": _tone(330, 1.0, 0.1),
              "residual": _tone(220, 1.0, 0.01)}
    settings = remix_settings_from_json({"guitar": {"mute": True}}, stems_)
    assert set(settings) == set(stems_)
    out = render_stems(stems_, SR, settings)
    assert list(out) == ["vocals", "guitar", "residual"]
    assert not np.any(out["guitar"])
    mixed = render_remix(stems_, SR, settings)
    np.testing.assert_allclose(mixed, stems_["vocals"] + stems_["residual"], atol=1e-6)
