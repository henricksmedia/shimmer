"""The Remix export on the new engine: each stem's effects and the sum,
then core.render() and core.export(), the Master tab's own path.

The 1.x report fields the Remix screen reads are held by
tests/test_remix_master.py.
"""
import asyncio
import json

import numpy as np
import pytest

import shimmer.server as server
from shimmer.jobs import JOB_STORE
from shimmer.preview_store import PREVIEW_STORE

SR = 44100


def _signal(seconds=3.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    base = 0.2 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 880 * t)
    x = np.stack([base + 0.02 * rng.standard_normal(t.size),
                  base + 0.02 * rng.standard_normal(t.size)], axis=1)
    return (0.4 * x).astype(np.float32)


@pytest.fixture()
def sess():
    x = _signal()
    s = PREVIEW_STORE.create(samples=x, sr=SR, original_path="unused", original_name="song.wav")
    s.stems = {name: (x / 4.0).astype(np.float32) for name in ("vocals", "drums", "bass", "other")}
    yield s
    PREVIEW_STORE.drop(s.id)


def _run(payload):
    async def drive():
        resp = await server.api_remix_render(payload)
        job = JOB_STORE.get(json.loads(resp.body)["job_id"])
        for _ in range(2400):
            if job.status in ("done", "error"):
                break
            await asyncio.sleep(0.05)
        return job
    return asyncio.run(drive())


def test_the_remix_export_is_the_engines_render_of_the_mix(sess):
    from shimmer import core
    from shimmer.stem_effects import remix_settings_from_json, render_remix
    stems = {"vocals": {"gain_db": -3.0}}
    job = _run({"session_id": sess.id, "stems": stems, "output_format": "wav",
                "mastering": {"enabled": True, "target": "loud"}, "cleaning": {"preset": "off"}})
    assert job.status == "done", job.error
    order = server._stem_order(sess)
    mix = render_remix({n: sess.stems[n] for n in order}, SR,
                       remix_settings_from_json(stems, order))
    expected = core.render(core.Source.from_array(mix, SR),
                           core.Settings(auto=False, loudness_target="loud"))
    got, sr = core.load_audio(job.processed_path)
    assert sr == expected.sr
    # Written at 24 bits: within one step of the render.
    assert float(np.max(np.abs(got - expected.audio))) < 2.0 ** -22


def test_the_cleanup_report_says_what_the_engine_did(sess):
    job = _run({"session_id": sess.id, "stems": {}, "output_format": "wav",
                "mastering": {"enabled": False}, "cleaning": {"preset": "auto"}})
    assert job.status == "done", job.error
    c = job.metrics["cleaning"]
    assert c["enabled"] is True and c["preset"] == "auto" and c["label"]
    assert "detected_strength" not in c and "detected_confidence" not in c
    assert job.metrics["mastering"] == {"enabled": False}


def test_a_preset_whose_card_has_no_tool_says_so(sess):
    job = _run({"session_id": sess.id, "stems": {}, "output_format": "wav",
                "mastering": {"enabled": False}, "cleaning": {"preset": "harsh_veil"}})
    assert job.status == "done", job.error
    assert "not built yet" in job.metrics["cleaning"]["label"]


def test_a_mastered_remix_carries_the_release_check(sess):
    job = _run({"session_id": sess.id, "stems": {}, "output_format": "wav",
                "mastering": {"enabled": True, "target": "loud"}, "cleaning": {"preset": "off"}})
    assert job.status == "done", job.error
    rel = job.metrics["release"]
    rows = {c["key"]: c for c in rel["checks"]}
    assert {"loudness", "true_peak", "format", "low_end", "source_clipping"} <= set(rows)
    assert rows["loudness"]["status"] == "pass"
    assert rows["source_clipping"]["status"] == "pass"
    # The test session's upload is not on disk, so there is nothing to take
    # tags from, and the release check says no tags were written.
    assert job.metrics["tags_written"] is False
