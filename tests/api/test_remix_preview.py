"""The Remix preview, Option A (REBUILD-TRACKER, chosen 2026-09-12): the loop
plays at once from its own mix, marked approximate, while the whole remix is
worked out in the background. Once it lands, the preview is render() on a
window of it: the export, level included.

The 1.x preview fields are held by tests/test_remix_master.py.
"""
import asyncio
import io
import json
import struct
import time

import numpy as np
import pytest

import shimmer.server as server
from shimmer.jobs import JOB_STORE
from shimmer.preview_store import PREVIEW_STORE

SR = 44100
MASTER = {"enabled": True, "target": "loud"}


def _signal(seconds=6.0, seed=0):
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


def _preview(sess, **extra):
    payload = {"session_id": sess.id, "start_s": 1.0, "end_s": 3.0, "stems": {}, **extra}
    body = asyncio.run(server.api_remix_preview(payload)).body
    (n,) = struct.unpack_from("<I", body, 0)
    return json.loads(body[4:4 + n].decode("utf-8")), body[4 + n:]


def _until_exact(sess, timeout=60.0, **extra):
    t0 = time.time()
    while time.time() - t0 < timeout:
        meta, wav = _preview(sess, **extra)
        if meta["exact"]:
            return meta, wav
        assert meta["building"], meta
        time.sleep(0.2)
    raise AssertionError("the whole mix never landed")


def test_the_first_preview_is_approximate_then_exact(sess):
    meta, _ = _preview(sess, mastering=MASTER)
    assert meta["exact"] is False and meta["building"] is True
    meta, _ = _until_exact(sess, mastering=MASTER)
    assert meta["exact"] is True and meta["mastered"] is True


def test_the_exact_preview_is_the_export_on_a_window(sess):
    soundfile = pytest.importorskip("soundfile")
    from shimmer import core
    from shimmer.stem_effects import remix_settings_from_json, render_remix
    stems = {"vocals": {"gain_db": -4.0}}
    _, wav = _until_exact(sess, mastering=MASTER, stems=stems)
    got, sr = soundfile.read(io.BytesIO(wav), dtype="float32", always_2d=True)
    order = server._stem_order(sess)
    mix = render_remix({n: sess.stems[n] for n in order}, SR,
                       remix_settings_from_json(stems, order))
    full = core.render(core.Source.from_array(mix, SR),
                       core.Settings(auto=False, loudness_target="loud"))
    span = full.audio[int(round(1.0 * SR)):int(round(3.0 * SR))]
    assert sr == SR and got.shape == span.shape
    err = float(np.max(np.abs(got - span))) / float(np.max(np.abs(span)))
    assert 20.0 * np.log10(err + 1e-12) < -60.0


def test_a_lane_change_is_approximate_until_its_mix_lands(sess):
    _until_exact(sess, mastering=MASTER)
    meta, _ = _preview(sess, mastering=MASTER, stems={"drums": {"gain_db": -6.0}})
    assert meta["exact"] is False and meta["building"] is True
    _until_exact(sess, mastering=MASTER, stems={"drums": {"gain_db": -6.0}})


def test_the_export_uses_the_mix_the_preview_built(sess, monkeypatch):
    _until_exact(sess, mastering=MASTER)

    def mixed_again(*a, **k):
        raise AssertionError("the export mixed the stems again")
    monkeypatch.setattr(server, "render_remix", mixed_again)

    async def drive():
        resp = await server.api_remix_render({
            "session_id": sess.id, "stems": {}, "output_format": "wav",
            "mastering": MASTER, "cleaning": {"preset": "off"}})
        job = JOB_STORE.get(json.loads(resp.body)["job_id"])
        for _ in range(2400):
            if job.status in ("done", "error"):
                break
            await asyncio.sleep(0.05)
        return job
    job = asyncio.run(drive())
    assert job.status == "done", job.error
