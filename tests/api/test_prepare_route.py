"""POST /api/prepare: a fix that must read the whole song first (Shimmer's
spectral de-noise) gets it ready as a job the screen follows on
/api/progress, once per song, and a request that no longer needs it stops
the job.
"""
import io
import json

import numpy as np
import pytest

from shimmer.core.repair import hash_remover

SR = 48000

needs_weights = pytest.mark.skipif(not hash_remover.available(),
                                   reason="the network's weights are not here")


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


def _events(client, job):
    events = []
    with client.stream("GET", f"/api/progress/{job}") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if events[-1].get("done"):
                    break
    return events


def test_an_unknown_session(client):
    assert client.post("/api/prepare", json={"session_id": "nope"}).status_code == 404


def test_nothing_slow_on_is_ready_at_once(client):
    sid = _upload(client)
    r = client.post("/api/prepare", json={"session_id": sid, "fixes": {"sibilance": 0.5}})
    assert r.json() == {"ready": True}


@needs_weights
def test_shimmer_is_got_ready_once_as_a_job(client):
    sid = _upload(client)
    body = {"session_id": sid, "fixes": {"shimmer": 1.0}, "auto": False}
    first = client.post("/api/prepare", json=body).json()
    assert first["ready"] is False and first["cards"] == ["shimmer"]
    # Asked again while it runs: the same job, not a second one.
    again = client.post("/api/prepare", json=body).json()
    assert again.get("job_id") in (first["job_id"], None)
    ev = _events(client, first["job_id"])
    assert ev[-1].get("done") and not ev[-1].get("error")
    assert any((e.get("detail") or "").startswith("reading the whole song once") for e in ev)
    assert client.post("/api/prepare", json=body).json() == {"ready": True}


@needs_weights
def test_turning_the_card_off_stops_the_job(client):
    sid = _upload(client)
    first = client.post("/api/prepare", json={"session_id": sid, "fixes": {"shimmer": 1.0}}).json()
    assert client.post("/api/prepare", json={"session_id": sid, "fixes": {}}).json() == {"ready": True}
    last = _events(client, first["job_id"])[-1]
    # Stopped, unless it had already finished.
    assert last.get("done") and (last.get("cancelled") or not last.get("error"))
