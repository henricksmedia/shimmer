"""
Album mode in Batch: the folder is mastered as one record.

Three tracks at different levels go through /api/batch twice. Without
album mode every output lands on the target. With album mode the loudest
output lands on the target and the others keep their distance below it,
the limiter's ceiling holds on every file, the album event reports the
gain the tracks got, and the parked pass-1 files are gone afterwards.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_batch_album.py -q
"""

from __future__ import annotations

import glob
import json
import os
import sys
import tempfile

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.audio_io import load_audio  # noqa: E402
from shimmer.mastering import measure_loudness  # noqa: E402

SR = 44100
TARGET = -14.0
# Track peaks in dBFS: the loudest first, then 6 and 12 dB quieter.
LEVELS_DB = {"01_single": -6.0, "02_ballad": -12.0, "03_outro": -18.0}


def _track(peak_db: float, seed: int, seconds: float = 3.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    bed = (0.5 * np.sin(2 * np.pi * 110 * t) + 0.25 * np.sin(2 * np.pi * 220 * t)
           + 0.12 * np.sin(2 * np.pi * 880 * t) + 0.04 * rng.standard_normal(n))
    beat = (t * 2.0) % 1.0
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-beat * 12.0)
    x = 0.6 * bed + 0.8 * kick
    y = np.stack([x + 0.02 * rng.standard_normal(n),
                  x + 0.02 * rng.standard_normal(n)], axis=1)
    y = y / np.max(np.abs(y)) * (10 ** (peak_db / 20.0))
    return y.astype(np.float32)


@pytest.fixture()
def album_folder(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    folder = tmp_path / "album"
    folder.mkdir()
    for i, (name, peak_db) in enumerate(LEVELS_DB.items()):
        soundfile.write(str(folder / f"{name}.wav"), _track(peak_db, seed=i), SR)
    return folder


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
    out = []
    for chunk in r.text.split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("data: "):
            out.append(json.loads(chunk[len("data: "):]))
    return out


def _payload(folder, out, album_mode):
    return {
        "input_folder": str(folder), "output_folder": str(out),
        "preset": "generic", "output_format": "wav",
        "static_repair": False, "trim_silence": False,
        "mastering": {"enabled": True, "target": "streaming"},
        "album_mode": album_mode,
        "tags": {"enabled": False},
    }


def _output_loudness(out):
    res = {}
    for path in sorted(glob.glob(os.path.join(str(out), "*.wav"))):
        x, sr = load_audio(path)
        res[os.path.splitext(os.path.basename(path))[0]] = measure_loudness(x, sr)
    return res


def test_without_album_mode_every_track_lands_on_target(client, album_folder, tmp_path):
    out = tmp_path / "flat"
    events = _events(client, _payload(album_folder, out, False))
    assert [e["type"] for e in events][0] == "start"
    assert not any(e["type"] == "album" for e in events)
    dones = [e for e in events if e["type"] == "file_done"]
    assert len(dones) == 3
    for e in dones:                       # per-file verification is logged
        assert abs(e["lufs_out"] - TARGET) <= 0.3, e
        assert e["true_peak_out"] <= -1.0 + 0.05, e
    loud = _output_loudness(out)
    for name, m in loud.items():
        assert abs(m["lufs_i"] - TARGET) <= 0.3, (name, m)


def test_album_mode_keeps_relative_levels(client, album_folder, tmp_path):
    out = tmp_path / "album_out"
    events = _events(client, _payload(album_folder, out, True))
    types = [e["type"] for e in events]
    assert types[0] == "start" and events[0]["album_mode"] is True
    assert types.count("phase") == 2 and types[-1] == "end"
    cleans = [e for e in events if e["type"] == "file_done" and e["phase"] == "clean"]
    masters = [e for e in events if e["type"] == "file_done" and e["phase"] == "master"]
    assert len(cleans) == 3 and len(masters) == 3
    album = [e for e in events if e["type"] == "album"][0]
    assert album["loudest"] == "01_single.wav"
    assert album["tracks"] == 3
    assert abs(album["gain_db"] - (TARGET - album["loudest_lufs"])) < 1e-6
    assert album["spread_lu"] == pytest.approx(
        album["loudest_lufs"] - min(e["lufs_clean"] for e in cleans), abs=1e-6)
    assert album["album_lufs"] < album["loudest_lufs"]

    loud = _output_loudness(out)
    assert set(loud) == set(LEVELS_DB)
    # The loudest track lands on the target; the others keep their
    # distance below it (within a few tenths: the shaper/limiter and the
    # measurement).
    assert abs(loud["01_single"]["lufs_i"] - TARGET) <= 0.3
    for name, peak_db in LEVELS_DB.items():
        expect = TARGET + (peak_db - LEVELS_DB["01_single"])
        assert abs(loud[name]["lufs_i"] - expect) <= 0.5, (name, loud[name], expect)
        assert loud[name]["true_peak_dbtp"] <= -1.0 + 0.05
    # The pass-2 events report what is on disk, and the one gain.
    for e in masters:
        stem = os.path.splitext(e["name"])[0]
        assert abs(e["lufs_out"] - loud[stem]["lufs_i"]) <= 0.1
        assert e["gain_db"] == pytest.approx(album["gain_db"])
        # The release check grades each track against its album level, so
        # sitting below the target by design is not a loudness problem.
        assert e["release"] and "Loudness" not in e["release"]["flags"], e["release"]
    # No parked pass-1 files are left behind.
    assert not glob.glob(os.path.join(tempfile.gettempdir(), "shimmer_album_*"))


def test_album_mode_needs_mastering(client, album_folder, tmp_path):
    out = tmp_path / "plain"
    payload = _payload(album_folder, out, True)
    payload["mastering"] = {"enabled": False}
    events = _events(client, payload)
    assert events[0]["album_mode"] is False
    assert not any(e["type"] in ("album", "phase") for e in events)
    assert len([e for e in events if e["type"] == "file_done"]) == 3


def test_ui_has_the_album_switch():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert 'id="batch-album-mode"' in html and 'id="batch-album-row"' in html
