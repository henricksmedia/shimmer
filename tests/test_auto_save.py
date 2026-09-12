"""
Save to folder: the finished file lands in the user's folder on its own.

/api/process takes an optional `save_folder`. When set, the export (the
silence-trimmed variant when trim is on) is copied there as the job ends,
under the same name the Download button gives, and the metrics say where
it went. A folder that cannot be created is a 400 before the run starts;
a copy that fails at the end is reported, not fatal.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_auto_save.py -q
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SR = 44100
PARAMS = json.dumps({"preset": "generic", "mastering": {"enabled": False}})


def _signal(seconds: float = 2.0, seed: int = 5,
            head_s: float = 0.0, tail_s: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    x = 0.2 * np.sin(2 * np.pi * 220 * t) + 0.02 * rng.standard_normal(n)
    y = np.stack([x, x * 0.9], axis=1).astype(np.float32)
    if head_s or tail_s:
        y = np.concatenate([np.zeros((int(SR * head_s), 2), np.float32), y,
                            np.zeros((int(SR * tail_s), 2), np.float32)], axis=0)
    return y


def _wav_bytes(x: np.ndarray) -> io.BytesIO:
    soundfile = pytest.importorskip("soundfile")
    buf = io.BytesIO()
    soundfile.write(buf, x, SR, format="WAV")
    buf.seek(0)
    return buf


def _run(client, buf, data, name="song.wav"):
    """POST the job and wait for it. Returns (response, (job_id, metrics))
    or (response, None) when the request itself was refused."""
    r = client.post("/api/process",
                    files={"file": (name, buf, "audio/wav")}, data=data)
    if r.status_code != 200:
        return r, None
    jid = r.json()["job_id"]
    deadline = time.time() + 120
    while time.time() < deadline:
        m = client.get(f"/api/metrics/{jid}")
        if m.status_code == 200 and m.json().get("status") == "done":
            return r, (jid, m.json()["metrics"])
        assert m.status_code != 500, m.text
        time.sleep(0.2)
    raise AssertionError("job did not finish")


@pytest.fixture()
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from shimmer.server import app
    with TestClient(app) as c:
        yield c


def test_saved_copy_matches_the_download(client, tmp_path):
    folder = tmp_path / "masters"
    _, (jid, metrics) = _run(client, _wav_bytes(_signal()),
                             {"params": PARAMS, "output_format": "wav",
                              "save_folder": str(folder)})
    saved = metrics["export"]["saved"]
    assert saved["enabled"] is True and "error" not in saved, saved
    assert os.path.dirname(saved["path"]) == str(folder)
    assert os.path.isfile(saved["path"])

    dl = client.get(f"/api/result/{jid}?kind=processed")
    assert dl.status_code == 200
    with open(saved["path"], "rb") as f:
        assert f.read() == dl.content            # same bytes as the download
    disp = dl.headers.get("content-disposition", "")
    m = re.search(r'filename="?([^";]+)"?', disp)
    assert m, disp
    assert m.group(1) == saved["name"] == os.path.basename(saved["path"])
    # 2.0 names drop the preset (docs/API.md §4, signed off 2026-09-12).
    assert saved["name"].startswith("song_processed_")
    assert saved["name"].endswith(".wav")


def test_trimmed_variant_is_what_gets_saved(client, tmp_path):
    folder = tmp_path / "out"
    x = _signal(head_s=1.0, tail_s=1.5)
    _, (jid, metrics) = _run(client, _wav_bytes(x),
                             {"params": PARAMS, "output_format": "wav",
                              "trim_silence": "true",
                              "save_folder": str(folder)})
    saved = metrics["export"]["saved"]
    assert "_trimmed_" in saved["name"], saved
    trimmed = client.get(f"/api/result/{jid}?kind=trimmed")
    assert trimmed.status_code == 200
    with open(saved["path"], "rb") as f:
        assert f.read() == trimmed.content
    assert metrics["trim"]["cut_head_s"] + metrics["trim"]["cut_tail_s"] > 1.0


def test_no_folder_means_no_copy(client):
    _, (_jid, metrics) = _run(client, _wav_bytes(_signal()),
                              {"params": PARAMS, "output_format": "wav"})
    assert metrics["export"]["saved"] == {"enabled": False}


def test_missing_folder_is_created(client, tmp_path):
    folder = tmp_path / "new" / "deeper"
    _, (_jid, metrics) = _run(client, _wav_bytes(_signal()),
                              {"params": PARAMS, "output_format": "wav",
                               "save_folder": str(folder)})
    assert folder.is_dir()
    assert os.path.isfile(metrics["export"]["saved"]["path"])


def test_unusable_folder_is_refused_before_the_run(client, tmp_path):
    blocker = tmp_path / "a_file"
    blocker.write_text("not a folder")
    r, done = _run(client, _wav_bytes(_signal()),
                   {"params": PARAMS, "output_format": "wav",
                    "save_folder": str(blocker / "sub")})
    assert r.status_code == 400 and done is None
    assert "Save folder" in r.text


def test_chain_view_shows_the_folder(client):
    r = client.post("/api/chain", json={
        "preset": "generic", "output_format": "wav",
        "save_folder": os.path.join("D:" + os.sep, "Music", "Masters")})
    assert r.status_code == 200
    export = [m for m in r.json()["modules"]
              if m.get("id") == "export" or m.get("mid") == "export"][0]
    assert "saved to Masters" in export["badges"], export["badges"]
    plain = client.post("/api/chain", json={"preset": "generic"})
    export2 = [m for m in plain.json()["modules"]
               if m.get("id") == "export" or m.get("mid") == "export"][0]
    assert not any(b.startswith("saved to") for b in export2["badges"])


def test_metrics_name_the_download(client, tmp_path):
    _, (jid, metrics) = _run(client, _wav_bytes(_signal()),
                             {"params": PARAMS, "output_format": "wav"})
    ex = metrics["export"]
    dl = client.get(f"/api/result/{jid}?kind=processed")
    assert ex["name"].startswith("song_processed_") and ex["name"].endswith(".wav")
    assert ex["size_bytes"] == len(dl.content)


def test_reveal_needs_an_existing_path(client, tmp_path):
    r = client.post("/api/reveal", json={"path": str(tmp_path / "nope.wav")})
    assert r.status_code == 404
    r = client.post("/api/reveal", json={})
    assert r.status_code == 400


def test_reveal_hands_the_path_to_the_file_manager(client, tmp_path, monkeypatch):
    import shimmer.server as server
    seen = []
    monkeypatch.setattr(server, "_REVEAL_LAUNCHER", lambda p: seen.append(p) or True)
    f = tmp_path / "song.wav"
    f.write_bytes(b"RIFF")
    r = client.post("/api/reveal", json={"path": str(f)})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen == [os.path.abspath(str(f))]


def test_ui_has_the_settings_tab_and_the_download_step():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert 'data-tab="settings"' in html and 'id="tab-settings"' in html
    for el_id in ("dl-auto", "dl-location-browser", "dl-location-folder",
                  "save-folder", "browse-save-btn"):
        assert f'id="{el_id}"' in html, el_id
    modal = html[html.index('id="process-modal"'):]
    for el_id in ("process-modal-download", "process-modal-dl-primary",
                  "process-modal-dl-secondary", "process-modal-dl-close"):
        assert f'id="{el_id}"' in modal, el_id
