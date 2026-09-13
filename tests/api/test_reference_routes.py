"""Reference-track matching through the routes: load a reference into the
song's session, read what the match will do, and hear it in the preview and
the export when the mastering block's tone target is "reference".
"""
import io
import json
import struct
import time

import numpy as np
import pytest

SR = 44100


def _noise(db_per_octave, seconds=20.0, seed=0):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.maximum(np.fft.rfftfreq(n, 1.0 / SR), 20.0)
    x = np.fft.irfft(spec * 10.0 ** (db_per_octave * np.log2(f / 1000.0) / 20.0), n)
    x = 0.1 * x / np.std(x)
    return np.stack([x, x], axis=1).astype(np.float32)


def _wav(x):
    soundfile = pytest.importorskip("soundfile")
    buf = io.BytesIO()
    soundfile.write(buf, x, SR, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf


@pytest.fixture()
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from shimmer.server import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sid(client):
    r = client.post("/api/upload", files={"file": ("song.wav", _wav(_noise(-2.0)), "audio/wav")})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _load_reference(client, sid):
    r = client.post("/api/reference", data={"session_id": sid},
                    files={"file": ("bright.wav", _wav(_noise(0.5, seed=1)), "audio/wav")})
    assert r.status_code == 200, r.text
    return r.json()["reference"]


MASTER_REF = {"enabled": True, "target": "cd", "tone_target": "reference", "match_amount": 0.5}


def test_load_view_and_remove_a_reference(client, sid):
    info = _load_reference(client, sid)
    assert info["name"] == "bright.wav" and abs(info["duration_s"] - 20.0) < 0.01
    view = client.post("/api/reference/view", json={"session_id": sid, "mastering": MASTER_REF})
    assert view.status_code == 200, view.text
    v = view.json()
    assert len(v["curve_db"]) == 29 and v["reference"]["name"] == "bright.wav"
    # The reference is brighter, so the match lifts the top.
    assert v["curve_db"][24] > 0.5
    assert client.delete(f"/api/reference/{sid}").status_code == 200
    assert client.post("/api/reference/view", json={"session_id": sid}).status_code == 409


def _preview_audio(client, sid, mastering):
    r = client.post("/api/preview", json={"session_id": sid, "start_s": 5.0, "end_s": 8.0,
                                          "mastering": mastering})
    assert r.status_code == 200, r.text
    body = r.content
    (n,) = struct.unpack_from("<I", body, 0)
    (wav_len,) = struct.unpack_from("<I", body, 4 + n)
    return body[8 + n:8 + n + wav_len]


def test_the_preview_hears_the_reference_only_when_asked(client, sid):
    _load_reference(client, sid)
    built_in = _preview_audio(client, sid, {"enabled": True, "target": "cd"})
    matched = _preview_audio(client, sid, MASTER_REF)
    assert built_in != matched
    assert _preview_audio(client, sid, {"enabled": True, "target": "cd"}) == built_in


def test_the_export_uses_the_reference(client, sid):
    _load_reference(client, sid)
    r = client.post("/api/process", data={"session_id": sid, "output_format": "wav",
                                          "params": json.dumps({"mastering": MASTER_REF})})
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    for _ in range(600):
        m = client.get(f"/api/metrics/{jid}")
        if m.status_code == 200 and m.json().get("status") == "done":
            break
        time.sleep(0.1)
    mastering = m.json()["metrics"]["mastering"]
    assert mastering["tone_target"] == "reference" and mastering["match_amount"] == 0.5


def test_a_reference_needs_a_live_session(client):
    r = client.post("/api/reference", data={"session_id": "nope"},
                    files={"file": ("x.wav", _wav(_noise(0.0, seconds=2.0)), "audio/wav")})
    assert r.status_code == 404
