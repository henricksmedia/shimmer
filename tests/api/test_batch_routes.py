"""Batch on the new engine (docs/API.md §5): each file goes through
core.render() and core.export(), the Master tab's own path, and each file's
findings replace the old preset trial.

Album mode's levels are held by tests/test_batch_album.py.
"""
import json

import numpy as np
import pytest

SR = 48000


def _mix(seed, level=0.1, seconds=4.0):
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    bed = 0.5 * np.sin(2 * np.pi * 110 * t) + 0.3 * rng.standard_normal(n)
    x = np.stack([bed, 0.9 * bed + 0.1 * rng.standard_normal(n)], axis=1)
    return (level * x / np.max(np.abs(x))).astype(np.float32)


@pytest.fixture()
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from shimmer.server import app
    with TestClient(app) as c:
        yield c


def _events(client, payload):
    r = client.post("/api/batch", json=payload)
    assert r.status_code == 200, r.text
    return [json.loads(c.strip()[len("data: "):]) for c in r.text.split("\n\n")
            if c.strip().startswith("data: ")]


def test_a_batch_file_is_the_engines_render(client, tmp_path):
    soundfile = pytest.importorskip("soundfile")
    from shimmer import core
    folder = tmp_path / "in"
    folder.mkdir()
    soundfile.write(str(folder / "song.wav"), _mix(1, level=0.3), SR, subtype="PCM_24")
    out = tmp_path / "out"
    events = _events(client, {
        "input_folder": str(folder), "output_folder": str(out),
        "preset": "generic", "output_format": "wav", "static_repair": True,
        "mastering": {"enabled": True, "target": "cd"}, "tags": {"enabled": False},
    })
    done = [e for e in events if e["type"] == "file_done"]
    assert len(done) == 1, events
    assert abs(done[0]["lufs_out"] - (-9.0)) <= 0.3, done[0]
    assert done[0]["release"]["status"] in ("pass", "warn")

    expected = core.render(core.Source.load(str(folder / "song.wav")),
                           core.Settings(loudness_target="cd"))
    got, sr = core.load_audio(str(out / "song.wav"))
    assert sr == expected.sr
    # Written at 24 bits: within one step of the render.
    assert float(np.max(np.abs(got - expected.audio))) < 2.0 ** -22


def test_batch_reports_findings_not_presets(client, tmp_path):
    soundfile = pytest.importorskip("soundfile")
    folder = tmp_path / "in"
    folder.mkdir()
    soundfile.write(str(folder / "quiet.wav"), _mix(2, level=0.01), SR)
    events = _events(client, {
        "input_folder": str(folder), "output_folder": str(tmp_path / "out"),
        "preset": "generic", "auto_detect": True, "output_format": "wav",
        "mastering": {"enabled": False}, "tags": {"enabled": False},
    })
    done = [e for e in events if e["type"] == "file_done"][0]
    assert not any(k.startswith("detected_") for k in done)
    assert "loudness" in {f["card"] for f in done["findings"]}, done["findings"]


def test_a_file_that_fails_does_not_stop_the_batch(client, tmp_path):
    soundfile = pytest.importorskip("soundfile")
    folder = tmp_path / "in"
    folder.mkdir()
    soundfile.write(str(folder / "a_good.wav"), _mix(3), SR)
    (folder / "b_broken.wav").write_bytes(b"not audio")
    events = _events(client, {
        "input_folder": str(folder), "output_folder": str(tmp_path / "out"),
        "preset": "generic", "output_format": "wav",
        "mastering": {"enabled": True, "target": "streaming"}, "tags": {"enabled": False},
    })
    types = [e["type"] for e in events]
    assert types.count("file_done") == 1 and types.count("file_error") == 1
    assert types[-1] == "end"
