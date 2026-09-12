"""The song is uploaded once and every tab reuses it (docs/API.md §2).

Upload, envelope and drop run on the new engine (shimmer.api.sessions);
the 1.x routes that still read sessions (preview, stems, Remix) must see the
same store.
"""
import hashlib
import io
import os

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from shimmer.api import sessions
from shimmer.server import app

SR = 48000


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _wav(seconds=3.0, silent=False):
    t = np.arange(int(seconds * SR)) / SR
    s = np.zeros_like(t) if silent else 0.2 * np.sin(2 * np.pi * 440.0 * t)
    buf = io.BytesIO()
    sf.write(buf, np.stack([s, s], axis=1), SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _upload(client, data, name="my_song.wav"):
    r = client.post("/api/upload", files={"file": (name, data, "audio/wav")})
    assert r.status_code == 200, r.text
    return r.json()


def test_upload_returns_what_the_screens_read(client):
    data = _wav()
    d = _upload(client, data)
    assert d["session_id"] and abs(d["duration_s"] - 3.0) < 0.01
    assert d["digest"] == hashlib.sha1(data).hexdigest()
    assert d["title_hint"] == "my song"
    assert isinstance(d["edges"]["found"], bool)
    assert isinstance(d["repair"]["plan"]["notches"], list)
    assert d["analysis"]["loudness"]["lufs_i"] < 0
    assert len(d["analysis"]["spectrum"]["freqs_hz"]) == len(d["analysis"]["spectrum"]["band_db"])
    for key in ("source_tags", "stems_tiers", "project", "sample_rate", "channels"):
        assert key in d
    client.delete(f"/api/upload/{d['session_id']}")


def test_the_original_lives_and_dies_with_its_session(client):
    d = _upload(client, _wav())
    sess = sessions.SESSIONS.get(d["session_id"])
    path = sess.original_path
    assert os.path.dirname(path) == sess.workdir and os.path.isfile(path)
    client.delete(f"/api/upload/{d['session_id']}")
    assert not os.path.exists(path)
    assert sessions.SESSIONS.get(d["session_id"]) is None


def test_a_silent_upload_does_not_fail(client):
    d = _upload(client, _wav(silent=True))
    assert d["analysis"]["loudness"]["lufs_i"] is None
    client.delete(f"/api/upload/{d['session_id']}")


def test_a_file_that_is_not_audio_is_refused_and_leaves_nothing(client):
    before = len(sessions.SESSIONS)
    r = client.post("/api/upload", files={"file": ("x.wav", b"not audio", "audio/wav")})
    assert r.status_code == 400
    assert len(sessions.SESSIONS) == before


def test_the_envelope_is_served_from_the_session(client):
    d = _upload(client, _wav())
    r = client.get(f"/api/envelope/{d['session_id']}", params={"start_s": 0, "end_s": 2, "points": 100})
    assert r.status_code == 200
    e = r.json()
    assert len(e["db"]) == 100 and max(e["db"]) > -20.0
    assert client.get("/api/envelope/nope").status_code == 404
    client.delete(f"/api/upload/{d['session_id']}")


def test_the_1x_routes_see_the_same_sessions(client):
    from shimmer.preview_store import PREVIEW_STORE
    d = _upload(client, _wav())
    assert PREVIEW_STORE.get(d["session_id"]) is sessions.SESSIONS.get(d["session_id"])
    r = client.post("/api/preview", json={"session_id": d["session_id"], "start_s": 0.0, "end_s": 2.0})
    assert r.status_code == 200
    client.delete(f"/api/upload/{d['session_id']}")
