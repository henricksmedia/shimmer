"""POST /api/size: every format's file size for the loaded song, before the
run (the size limit). And each export reports every format's size for the
master it wrote.
"""
import io
import json
import time

import numpy as np
import pytest

SR = 48000


def _song(seconds=40.0, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    x = 0.3 * np.sin(2 * np.pi * 110 * t) + 0.1 * rng.standard_normal(t.size)
    return (0.5 * np.stack([x, x], axis=1) / np.max(np.abs(x))).astype(np.float32)


@pytest.fixture()
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from shimmer.server import app
    with TestClient(app) as c:
        yield c


def _upload(client):
    soundfile = pytest.importorskip("soundfile")
    buf = io.BytesIO()
    soundfile.write(buf, _song(), SR, format="WAV", subtype="PCM_16")
    buf.seek(0)
    r = client.post("/api/upload", files={"file": ("song.wav", buf, "audio/wav")})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def test_the_size_route_answers_every_format(client):
    from shimmer.core import catalog
    sid = _upload(client)
    r = client.post("/api/size", json={"session_id": sid,
                                       "mastering": {"enabled": True, "target": "cd"}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert abs(d["duration_s"] - 40.0) < 0.01
    assert set(d["sizes"]) == {f.key for f in catalog.FORMATS}
    wav16 = d["sizes"]["wav16"]
    assert wav16["exact"] and abs(wav16["bytes"] - (44 + round(40.0 * 44100) * 4)) <= 8
    flac16 = d["sizes"]["flac16"]
    assert flac16["low"] < flac16["high"] < wav16["bytes"]


def test_an_unknown_session_is_404(client):
    assert client.post("/api/size", json={"session_id": "nope"}).status_code == 404


def test_the_export_reports_every_formats_size(client):
    sid = _upload(client)
    params = json.dumps({"mastering": {"enabled": True, "target": "cd"}})
    r = client.post("/api/process", data={"session_id": sid, "params": params,
                                          "output_format": "flac16"})
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    for _ in range(600):
        m = client.get(f"/api/metrics/{jid}")
        if m.status_code == 200 and m.json().get("status") == "done":
            break
        time.sleep(0.1)
    ex = m.json()["metrics"]["export"]
    est = ex["sizes"]["flac16"]
    assert est["low"] <= ex["size_bytes"] <= est["high"], (est, ex["size_bytes"])
    assert ex["format_key"] == "flac16" and ex["sample_rate"] == 44100
