"""Render and export on the new engine: preview, process, progress, metrics,
result and cancel (docs/API.md §4), with the 1.x fields still accepted
(the transition rule, API.md §0)."""
import io
import json
import re
import struct
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from shimmer.api import jobs as jobs_mod
from shimmer.server import app

SR = 48000


@pytest.fixture(scope="module")
def client():
    # Entered as a context, so its event loop stays up between requests and
    # the export jobs started in the background keep running.
    with TestClient(app) as c:
        yield c


def _song(seconds=8.0, seed=2):
    """Dense, sustained stereo like a mix before mastering: held chords that
    change every second, a bass, a soft kick, and a fixed 16 kHz tone for
    the Fixed tones card to find. (A sparse, decaying signal cannot reach
    -9 LUFS cleanly, and the engine rightly stops short on one.)"""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    x = np.zeros(n)
    for i in range(int(seconds)):
        s, e = i * SR, (i + 1) * SR
        root = 110.0 * 2 ** (rng.integers(0, 12) / 12.0)
        seg = t[s:e] - t[s]
        for ratio in (1.0, 1.26, 1.5, 2.0):
            for h in range(1, 4):
                x[s:e] += (0.06 / h) * np.sin(2 * np.pi * root * ratio * h * seg + rng.uniform(0, 6.28))
    x += 0.2 * np.sin(2 * np.pi * 55.0 * t)
    kt = np.arange(3840) / SR
    kick = np.sin(2 * np.pi * (60 * kt + 10 * (1 - np.exp(-kt * 40)))) * np.exp(-kt * 30)
    for s in range(0, n - 3840, SR // 2):
        x[s:s + 3840] += 0.3 * kick
    x += 10 ** (-40 / 20) * np.sin(2 * np.pi * 16000.0 * t)
    y = np.stack([x, 0.9 * x], axis=1)
    return (y * 10 ** (-8 / 20) / np.max(np.abs(y))).astype(np.float32)


def _wav_bytes(y):
    buf = io.BytesIO()
    sf.write(buf, y, SR, format="WAV", subtype="PCM_24")
    return buf.getvalue()


def _upload(client, y, name="the_song.wav"):
    r = client.post("/api/upload", files={"file": (name, _wav_bytes(y), "audio/wav")})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _wait(client, job_id, timeout=120.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/metrics/{job_id}")
        if r.status_code != 202:
            return r
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def _process(client, sid, params, output_format="wav", **form):
    data = {"session_id": sid, "params": json.dumps(params), "output_format": output_format}
    data.update({k: str(v) for k, v in form.items()})
    r = client.post("/api/process", data=data)
    assert r.status_code == 200, r.text
    return r.json()["job_id"]


MASTER_CD = {"mastering": {"enabled": True, "target": "cd"}}


def test_process_by_session_reaches_the_target_and_reports_it(client):
    sid = _upload(client, _song())
    job = _process(client, sid, MASTER_CD)
    r = _wait(client, job)
    assert r.status_code == 200, r.text
    m = r.json()["metrics"]
    assert abs(m["mastering"]["after"]["lufs_i"] - (-9.0)) <= 0.6
    assert m["mastering"]["after"]["true_peak_dbtp"] <= -1.0 + 0.05
    assert m["repair"]["enabled"] and any(abs(ln["hz"] - 16000.0) < 60 for ln in m["repair"]["lines"])
    assert m["release"]["status"] in ("pass", "warn", "fail")
    assert re.fullmatch(r"the_song_processed_[0-9a-f]{8}\.wav", m["export"]["name"])
    for key in ("spectra", "loudness", "input", "output", "edge_trim", "trim", "eq", "cutoff_hz"):
        assert key in m


def test_results_download_with_2_0_names(client):
    sid = _upload(client, _song())
    job = _process(client, sid, MASTER_CD)
    _wait(client, job)
    r = client.get(f"/api/result/{job}")
    assert r.status_code == 200
    assert f"the_song_processed_{job[:8]}.wav" in r.headers["content-disposition"]
    assert client.get(f"/api/result/{job}", params={"kind": "diff"}).status_code == 200
    assert client.get(f"/api/result/{job}", params={"kind": "original"}).status_code == 404


def test_an_unfinished_result_answers_409(client):
    job = jobs_mod.JOB_STORE.create()
    job.status = "running"
    r = client.get(f"/api/result/{job.id}")
    assert r.status_code == 409 and r.headers["content-type"].startswith("application/json")


def test_an_expired_session_asks_for_the_file_again(client):
    r = client.post("/api/process", data={"session_id": "gone", "params": "{}"})
    assert r.status_code == 404


def test_the_1x_fields_still_work(client):
    y = _song()
    r = client.post("/api/process", files={"file": ("old.wav", _wav_bytes(y), "audio/wav")},
                    data={"params": json.dumps({"preset": "cymbal_sheen", "preset_strength": 1.0,
                                                "overrides": {"thr_db": 7.0}, **MASTER_CD})})
    assert r.status_code == 200
    m = _wait(client, r.json()["job_id"]).json()["metrics"]
    assert m["fixes"]["tones"]["enabled"]


def test_static_repair_off_turns_fixed_tones_off(client):
    sid = _upload(client, _song())
    job = _process(client, sid, {**MASTER_CD, "repair": {"enabled": False}})
    m = _wait(client, job).json()["metrics"]
    assert m["repair"]["enabled"] is False


def test_every_listener_gets_every_event(client):
    sid = _upload(client, _song())
    job = _process(client, sid, MASTER_CD)
    _wait(client, job)

    def listen():
        events = []
        with client.stream("GET", f"/api/progress/{job}") as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
                    if events[-1].get("done"):
                        break
        return events

    first, second = listen(), listen()
    assert first[-1]["done"] and second[-1]["done"]
    stages = [e["stage"] for e in first if "stage" in e]
    assert "master" in stages and "export" in stages
    assert [e.get("stage") for e in first] == [e.get("stage") for e in second]


def test_cancel_reaches_a_new_engine_job_and_says_no_to_an_old_one(client):
    import asyncio
    job = jobs_mod.JOB_STORE.create()
    job.status = "running"
    jobs_mod.pusher(job, asyncio.new_event_loop())
    assert client.post(f"/api/cancel/{job.id}").json() == {"cancelled": True}
    assert job.run.cancelled
    old = jobs_mod.JOB_STORE.create()
    old.status = "running"
    body = client.post(f"/api/cancel/{old.id}").json()
    assert body["cancelled"] is False and body["reason"]


def _preview(client, sid, payload):
    r = client.post("/api/preview", json={"session_id": sid, **payload})
    assert r.status_code == 200, r.text
    b = r.content
    n = struct.unpack("<I", b[:4])[0]
    meta = json.loads(b[4:4 + n])
    m = struct.unpack("<I", b[4 + n:8 + n])[0]
    processed, _ = sf.read(io.BytesIO(b[8 + n:8 + n + m]), always_2d=True)
    removed, _ = sf.read(io.BytesIO(b[8 + n + m:]), always_2d=True)
    return meta, processed, removed


def test_the_preview_is_the_export_on_a_window(client):
    y = _song()
    sid = _upload(client, y)
    meta, processed, removed = _preview(client, sid, {"start_s": 2.0, "end_s": 5.0, **MASTER_CD})
    assert meta["sample_rate"] == SR and processed.shape == (3 * SR, 2)
    job = _process(client, sid, MASTER_CD)
    _wait(client, job)
    exported, _ = sf.read(io.BytesIO(client.get(f"/api/result/{job}").content), always_2d=True)
    ref = exported[2 * SR:5 * SR]
    d = processed - ref
    residual_db = 10 * np.log10(np.mean(ref ** 2) / max(np.mean(d ** 2), 1e-30))
    assert residual_db >= 60.0                    # 16-bit preview vs 24-bit export
    assert np.max(np.abs(removed)) > 0            # the notch took the 16 kHz tone out
