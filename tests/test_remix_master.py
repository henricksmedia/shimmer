"""
Remix mastering-parity tests.

Covers the Tier-1 workflow unification:
  1. /api/remix/preview — optional mastering on the summed slice,
     per-slice LUFS meta for loudness-matched A/B, back-compat when no
     mastering block is sent.
  2. /api/remix/render — optional artifact cleanup (full safe pipeline)
     and mastering stages, cleaning/mastering/loudness metrics.
  3. CLI — codec-aware true-peak ceiling derived from the output extension.

Run:  .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import struct
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shimmer.server as server
from shimmer.jobs import JOB_STORE
from shimmer.preview_store import PREVIEW_STORE
from shimmer.cli import _resolve_master_params

SR = 44100


def _stereo_signal(seconds: float = 3.0, seed: int = 0) -> np.ndarray:
    """Quiet music-ish stereo signal with headroom for mastering gain."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    base = 0.2 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 880 * t)
    left = base + 0.02 * rng.standard_normal(t.size)
    right = base + 0.02 * rng.standard_normal(t.size)
    return (0.4 * np.stack([left, right], axis=1)).astype(np.float32)


@pytest.fixture()
def session_with_stems():
    x = _stereo_signal()
    sess = PREVIEW_STORE.create(samples=x, sr=SR,
                                original_path="unused",
                                original_name="test.wav")
    quarter = (x / 4.0).astype(np.float32)
    sess.stems = {name: quarter.copy()
                  for name in ("vocals", "drums", "bass", "other")}
    yield sess
    PREVIEW_STORE.drop(sess.id)


def _preview(sess, extra: dict) -> tuple[dict, bytes]:
    payload = {"session_id": sess.id, "start_s": 0.0, "end_s": 2.0,
               "stems": {}, **extra}
    resp = asyncio.run(server.api_remix_preview(payload))
    body = resp.body
    (jlen,) = struct.unpack_from("<I", body, 0)
    meta = json.loads(body[4:4 + jlen].decode("utf-8"))
    return meta, body[4 + jlen:]


def _render_job(payload):
    async def _drive():
        resp = await server.api_remix_render(payload)
        job_id = json.loads(resp.body)["job_id"]
        job = JOB_STORE.get(job_id)
        for _ in range(2400):  # up to 2 minutes
            if job.status in ("done", "error"):
                break
            await asyncio.sleep(0.05)
        return job
    return asyncio.run(_drive())


# ── 1. Remix preview ─────────────────────────────────────────────────────

def test_preview_no_mastering_block_is_unmastered(session_with_stems):
    """Old clients that send no mastering block get the legacy behavior."""
    meta, wav = _preview(session_with_stems, {})
    assert meta["mastered"] is False
    assert np.isfinite(meta["lufs_original"])
    assert np.isfinite(meta["lufs_remix"])
    assert len(wav) > 1000


def test_preview_master_disabled_is_unmastered(session_with_stems):
    meta, _ = _preview(session_with_stems,
                       {"mastering": {"enabled": False}})
    assert meta["mastered"] is False


def test_preview_mastering_raises_slice_loudness(session_with_stems):
    """Mastered preview must actually pass through the LUFS gain stage:
    the quiet stem sum should come back much louder, near the target."""
    meta_dry, _ = _preview(session_with_stems, {})
    meta_m, _ = _preview(session_with_stems, {"mastering": {
        "enabled": True, "target": "streaming",
        "intensity": "med", "tilt": "neutral",
    }})
    assert meta_m["mastered"] is True
    assert meta_m["lufs_remix"] > meta_dry["lufs_remix"] + 3.0
    # Slice-level gating differs from full-file, so allow a wide band.
    assert abs(meta_m["lufs_remix"] - (-14.0)) < 3.0
    # Original-mix loudness must be unaffected by mastering the remix.
    assert abs(meta_m["lufs_original"] - meta_dry["lufs_original"]) < 0.1


def test_preview_all_muted_ships_silence(session_with_stems):
    muted = {name: {"mute": True} for name in
             ("vocals", "drums", "bass", "other")}
    meta, wav = _preview(session_with_stems, {
        "stems": muted, "mastering": {"enabled": True}})
    assert meta["mastered"] is False
    assert meta["lufs_remix"] <= -100.0
    assert len(wav) > 44


# ── 2. Remix render ──────────────────────────────────────────────────────

def test_render_mastered_report_and_loudness(session_with_stems):
    job = _render_job({
        "session_id": session_with_stems.id,
        "stems": {},
        "output_format": "wav",
        "mastering": {"enabled": True, "target": "loud",
                      "intensity": "med", "tilt": "neutral"},
        "cleaning": {"preset": "off"},
    })
    assert job.status == "done", job.error
    m = job.metrics
    assert m["cleaning"]["enabled"] is False
    assert m["mastering"]["enabled"] is True
    assert abs(m["mastering"]["target_lufs"] - (-11.0)) < 1e-6
    after = m["mastering"]["after"]
    assert abs(after["lufs_i"] - (-11.0)) < 1.5
    assert after["true_peak_dbtp"] <= -0.9  # ceiling -1.0 for wav
    assert m["loudness"]["output_lufs_i"] == pytest.approx(
        after["lufs_i"], abs=1e-6)
    assert os.path.isfile(job.processed_path)


def test_render_with_cleaning_preset_runs_full_pipeline(session_with_stems):
    job = _render_job({
        "session_id": session_with_stems.id,
        "stems": {},
        "output_format": "wav",
        "mastering": {"enabled": True, "target": "streaming",
                      "intensity": "med", "tilt": "neutral"},
        "cleaning": {"preset": "generic"},
    })
    assert job.status == "done", job.error
    m = job.metrics
    assert m["cleaning"]["enabled"] is True
    assert m["cleaning"]["preset"] == "generic"
    assert m["cleaning"]["label"]
    # Mastering ran inside the pipeline, not the bare master() path.
    assert m["mastering"]["enabled"] is True
    assert np.isfinite(m["mastering"]["after"]["lufs_i"])


def test_render_unmastered_uncleaned_reports_loudness(session_with_stems):
    job = _render_job({
        "session_id": session_with_stems.id,
        "stems": {},
        "output_format": "wav",
        "mastering": {"enabled": False},
        "cleaning": {"preset": "off"},
    })
    assert job.status == "done", job.error
    m = job.metrics
    assert m["mastering"] == {"enabled": False}
    assert m["loudness"]["output_lufs_i"] is not None


def test_render_rejects_unknown_cleaning_preset(session_with_stems):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        asyncio.run(server.api_remix_render({
            "session_id": session_with_stems.id,
            "stems": {},
            "output_format": "wav",
            "mastering": {"enabled": False},
            "cleaning": {"preset": "definitely_not_a_preset"},
        }))
    assert exc.value.status_code == 400


# ── 3. CLI codec-aware ceiling ───────────────────────────────────────────

def _cli_args(**overrides):
    base = dict(no_master=False, master=True, target=None, target_lufs=None,
                ceiling=None, master_intensity=None, master_tilt=None,
                output="out.wav")
    base.update(overrides)
    return argparse.Namespace(**base)


def test_cli_ceiling_defaults_are_codec_aware():
    assert _resolve_master_params(_cli_args(output="a.wav")).ceiling_dbtp == -1.0
    assert _resolve_master_params(_cli_args(output="a.flac")).ceiling_dbtp == -1.0
    assert _resolve_master_params(_cli_args(output="a.mp3")).ceiling_dbtp == -1.5
    assert _resolve_master_params(_cli_args(output="a.m4a")).ceiling_dbtp == -1.5
    assert _resolve_master_params(_cli_args(output="a.ogg")).ceiling_dbtp == -1.5


def test_cli_explicit_ceiling_wins():
    mp = _resolve_master_params(_cli_args(output="a.mp3", ceiling=-2.0))
    assert mp.ceiling_dbtp == -2.0


def test_cli_no_master_returns_none():
    assert _resolve_master_params(_cli_args(no_master=True)) is None
