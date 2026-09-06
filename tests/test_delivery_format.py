"""
The release copy: WAV 16-bit at 44.1 kHz with TPDF dither, the chain
run at the delivery rate.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_delivery_format.py -q
"""

from __future__ import annotations

import glob
import io
import json
import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.audio_io import (  # noqa: E402
    OUTPUT_FORMATS, load_audio, process_file, resample_to, resolve_output_format,
)
from shimmer.mastering import measure_loudness  # noqa: E402
from shimmer.params import MasterParams  # noqa: E402
from shimmer.presets import get_preset  # noqa: E402

SR48 = 48000


def _signal(seconds: float = 4.0, sr: int = SR48, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    t = np.arange(n) / sr
    x = (0.4 * np.sin(2 * np.pi * 110 * t) + 0.2 * np.sin(2 * np.pi * 1000 * t)
         + 0.03 * rng.standard_normal(n))
    y = np.stack([x, x * 0.9], axis=1)
    return (y / np.max(np.abs(y)) * 0.5).astype(np.float32)


def _wav_bytes(x: np.ndarray, sr: int) -> io.BytesIO:
    soundfile = pytest.importorskip("soundfile")
    buf = io.BytesIO()
    soundfile.write(buf, x, sr, format="WAV")
    buf.seek(0)
    return buf


def test_output_format_specs():
    spec = resolve_output_format("wav16")
    assert spec["key"] == "wav16" and spec["ext"] == ".wav"
    assert spec["subtype"] == "PCM_16" and spec["sr"] == 44100
    assert spec["bit_depth"] == 16 and spec["dither"] is True
    wav = resolve_output_format(".WAV")
    assert wav["key"] == "wav" and wav["subtype"] == "PCM_24" and wav["sr"] is None
    assert wav["dither"] is False
    assert set(OUTPUT_FORMATS) == {"wav", "wav16", "flac", "mp3", "ogg", "m4a"}
    with pytest.raises(ValueError):
        resolve_output_format("aiff")


def test_resample_changes_the_rate_and_keeps_the_music():
    x = _signal()
    y, sr = resample_to(x, SR48, 44100)
    assert sr == 44100
    assert abs(y.shape[0] - x.shape[0] * 44100 / 48000) <= 2
    assert y.shape[1] == 2 and y.dtype == np.float32
    before = measure_loudness(x, SR48)["lufs_i"]
    after = measure_loudness(y, 44100)["lufs_i"]
    assert abs(after - before) < 0.15
    # No-ops hand the array straight back.
    same, sr2 = resample_to(x, SR48, None)
    assert same is x and sr2 == SR48
    same2, _ = resample_to(x, SR48, 48000)
    assert same2 is x


def test_process_file_writes_the_release_copy(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    src = tmp_path / "src.wav"
    soundfile.write(str(src), _signal(), SR48)
    out = tmp_path / "out.wav"
    spec = resolve_output_format("wav16")
    r = process_file(str(src), str(out), get_preset("generic"),
                     master_params=MasterParams(enabled=True, target_lufs=-14.0),
                     static_repair=False, subtype=spec["subtype"], target_sr=spec["sr"])
    info = soundfile.info(str(out))
    assert info.samplerate == 44100 and info.subtype == "PCM_16"
    assert r["sr"] == 44100
    y, sr = load_audio(str(out))
    m = measure_loudness(y, sr)
    assert abs(m["lufs_i"] - (-14.0)) <= 0.3, m      # the target holds at 44.1 kHz
    assert m["true_peak_dbtp"] <= -1.0 + 0.05, m       # the limiter worked at the delivery rate
    checks = {c["key"]: c for c in r["release"]["checks"]}
    assert checks["sample_rate"]["value"] == "44.1 kHz"
    assert checks["format"]["value"] == "16-bit WAV"


# ── Through the server ───────────────────────────────────────────────────

@pytest.fixture()
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from shimmer.server import app
    with TestClient(app) as c:
        yield c


def _wait(client, jid):
    deadline = time.time() + 120
    while time.time() < deadline:
        m = client.get(f"/api/metrics/{jid}")
        if m.status_code == 200 and m.json().get("status") == "done":
            return m.json()["metrics"]
        assert m.status_code != 500, m.text
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def test_api_process_release_copy(client):
    soundfile = pytest.importorskip("soundfile")
    params = json.dumps({"preset": "generic",
                         "mastering": {"enabled": True, "target": "streaming"}})
    r = client.post("/api/process",
                    files={"file": ("song.wav", _wav_bytes(_signal(), SR48), "audio/wav")},
                    data={"params": params, "output_format": "wav16"})
    assert r.status_code == 200, r.text
    metrics = _wait(client, r.json()["job_id"])
    ex = metrics["export"]
    assert ex["format"] == "wav" and ex["format_key"] == "wav16"
    assert ex["bit_depth"] == 16 and ex["dither"] is True and ex["sample_rate"] == 44100
    assert metrics["sample_rate"] == 44100
    assert abs(metrics["mastering"]["after"]["lufs_i"] - (-14.0)) <= 0.3
    assert metrics["mastering"]["ceiling_dbtp"] == -1.0
    dl = client.get(f"/api/result/{r.json()['job_id']}?kind=processed")
    assert dl.status_code == 200
    info = soundfile.info(io.BytesIO(dl.content))
    assert info.samplerate == 44100 and info.subtype == "PCM_16"
    assert 'filename="' in dl.headers.get("content-disposition", "") and ".wav" in dl.headers["content-disposition"]


def test_api_process_rejects_an_unknown_format(client):
    params = json.dumps({"preset": "generic", "mastering": {"enabled": False}})
    r = client.post("/api/process",
                    files={"file": ("song.wav", _wav_bytes(_signal(1.0), SR48), "audio/wav")},
                    data={"params": params, "output_format": "aiff"})
    assert r.status_code == 400


def test_chain_view_names_the_release_copy(client):
    r = client.post("/api/chain", json={"preset": "generic", "output_format": "wav16"})
    assert r.status_code == 200
    export = [m for m in r.json()["modules"]
              if m.get("id") == "export" or m.get("mid") == "export"][0]
    assert "WAV" in export["badges"]
    assert any("16-bit" in b and "44.1 kHz" in b for b in export["badges"])
    limiter = [m for m in r.json()["modules"]
               if m.get("id") == "m-limit" or m.get("mid") == "m-limit"][0]
    assert "-1.0 dBTP" in limiter["badges"]


def test_batch_release_copy(client, tmp_path):
    soundfile = pytest.importorskip("soundfile")
    folder = tmp_path / "in"
    folder.mkdir()
    for i in range(2):
        soundfile.write(str(folder / f"t{i}.wav"), _signal(seed=i), SR48)
    out = tmp_path / "out"
    r = client.post("/api/batch", json={
        "input_folder": str(folder), "output_folder": str(out),
        "preset": "generic", "output_format": "wav16", "static_repair": False,
        "mastering": {"enabled": True, "target": "streaming"},
        "tags": {"enabled": False},
    })
    assert r.status_code == 200, r.text
    assert r.text.count('"type": "file_done"') == 2
    files = sorted(glob.glob(os.path.join(str(out), "*.wav")))
    assert len(files) == 2
    for path in files:
        info = soundfile.info(path)
        assert info.samplerate == 44100 and info.subtype == "PCM_16"
