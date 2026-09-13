"""POST /api/chain: the Signal chain view's stages for the Master tab's
settings, with the loaded song's facts when a session is sent.
"""
import io

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


def _stages(r):
    assert r.status_code == 200, r.text
    return {s["key"]: s for s in r.json()["stages"]}


def test_no_song_yet(client):
    r = client.post("/api/chain", json={})
    st = _stages(r)
    assert list(st) == ["load", "edit", "rate", "fixes", "tone", "eq", "master", "export",
                        "report"]
    assert st["load"]["verdict"] == "On · no song loaded yet"
    assert r.json()["summary"]["total"] == 9


def test_the_songs_facts_come_from_the_session(client):
    sid = _upload(client)
    st = _stages(client.post("/api/chain", json={"session_id": sid, "output_format": "wav16"}))
    assert st["load"]["verdict"] == "On · song.wav"
    assert st["load"]["badges"] == ["48 kHz", "16-bit", "stereo", "0:40"]
    assert st["rate"]["badges"] == ["48 kHz → 44.1 kHz"]


def test_the_screens_notches_and_cards(client):
    st = _stages(client.post("/api/chain", json={
        "fixes": {"tones": 1.0}, "auto": True,
        "repair": {"enabled": True, "notches": [{"hz": 3000.0, "depth_db": 8.0, "bw_hz": 40.0}]},
        "cards": {"on": ["tones", "air"], "noted": ["shimmer", "nonsense"]},
        "mastering": {"enabled": True, "target": "cd"},
        "trim": {"in_s": 1.5, "out_s": None},
    }))
    assert st["fixes"]["badges"][0] == "1 notch"
    assert [r["key"] for r in st["fixes"]["fixes"]] == ["tones", "air"]
    assert [r["key"] for r in st["fixes"]["noted"]] == ["shimmer"]
    assert st["edit"]["verdict"] == "On · starts at 0:01.5"


def test_the_reference_counts_only_when_one_is_loaded(client):
    sid = _upload(client)
    st = _stages(client.post("/api/chain", json={
        "session_id": sid, "mastering": {"enabled": True, "tone_target": "reference"}}))
    assert st["tone"]["name"] == "Tone match"


def test_master_shows_the_gain_after_the_preview(client):
    sid = _upload(client)
    body = {"session_id": sid, "mastering": {"enabled": True, "target": "cd"}}
    before = _stages(client.post("/api/chain", json=body))["master"]
    assert not before["badges"][0].endswith("gain")
    r = client.post("/api/preview", json={**body, "start_s": 0.0, "end_s": 5.0})
    assert r.status_code == 200, r.text
    after = _stages(client.post("/api/chain", json=body))["master"]
    assert after["badges"][0].endswith(" dB gain"), after["badges"]


def test_old_saved_fields_still_work(client):
    """A 1.x body (a preset) maps through migrate(), as the other routes do."""
    r = client.post("/api/chain", json={"preset": "vocal_glaze", "preset_strength": 1.0,
                                        "mastering": {"enabled": False},
                                        "preserve_volume": True})
    st = _stages(r)
    assert "sibilance" in [row["key"] for row in st["fixes"]["fixes"]]
    assert st["master"]["tag"] == "Mastering off"
