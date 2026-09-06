"""
The release check: one verdict on the exported file.

Unit tests drive shimmer.release.release_check with a synthetic export
and a mastering report; the endpoint test confirms a mastered run's
metrics carry the check and an unmastered run's do not.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_release_check.py -q
"""

from __future__ import annotations

import io
import json
import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.release import (  # noqa: E402
    add_check, count_clipped, platform_changes, release_check, summary, tags_check,
)

SR = 44100


def _signal(seconds: float = 40.0, peak: float = 0.5, seed: int = 7,
            head_silence_s: float = 0.0, tail_silence_s: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    x = 0.5 * np.sin(2 * np.pi * 110 * t) + 0.2 * np.sin(2 * np.pi * 440 * t)
    x += 0.03 * rng.standard_normal(n)
    y = np.stack([x, x * 0.9], axis=1)
    y = y / np.max(np.abs(y)) * peak
    if head_silence_s or tail_silence_s:
        y = np.concatenate([np.zeros((int(SR * head_silence_s), 2)), y,
                            np.zeros((int(SR * tail_silence_s), 2))], axis=0)
    return y.astype(np.float32)


def _mastering(after_lufs=-14.0, target=-14.0, tp=-1.2, ceiling=-1.0):
    return {"enabled": True, "target_lufs": target, "ceiling_dbtp": ceiling,
            "after": {"lufs_i": after_lufs, "true_peak_dbtp": tp}}


GOOD_TAGS = {"title": "Leave The World Behind", "artist": "The Treq", "album": "LTWB"}
WAV = {"format": "wav", "bit_depth": 24}


def _by_key(rep):
    return {c["key"]: c for c in rep["checks"]}


def test_clean_master_is_ready_to_upload():
    rep = release_check(_signal(), SR, mastering=_mastering(), export=WAV,
                        x_in=_signal(peak=0.5), correlation=0.9, tags=GOOD_TAGS,
                        tags_written=True)
    assert rep["status"] == "pass", rep
    assert rep["failed"] == 0 and rep["warned"] == 0
    checks = _by_key(rep)
    for key in ("loudness", "true_peak", "source_clipping", "sample_rate", "format",
                "head_silence", "tail_silence", "duration", "dc_offset", "mono", "tags"):
        assert checks[key]["status"] == "pass", checks[key]
    assert checks["isrc"]["status"] == "info"
    assert rep["passed"] == 11
    assert [p["name"] for p in rep["platforms"]][:3] == ["Spotify", "Apple Music", "YouTube"]


@pytest.mark.parametrize("after, expected", [(-14.4, "pass"), (-14.8, "warn"), (-15.6, "fail")])
def test_loudness_shortfall_grades(after, expected):
    rep = release_check(_signal(), SR, mastering=_mastering(after_lufs=after), export=WAV)
    assert _by_key(rep)["loudness"]["status"] == expected
    assert rep["status"] == expected


def test_album_level_is_the_yardstick_in_album_mode():
    # A quiet album track that landed 6 LU under the target on purpose.
    rep = release_check(_signal(), SR, mastering=_mastering(after_lufs=-20.0), export=WAV,
                        expected_lufs=-20.0)
    c = _by_key(rep)["loudness"]
    assert c["status"] == "pass" and "album mode" in c["detail"], c
    # The loudest track: on the target.
    rep2 = release_check(_signal(), SR, mastering=_mastering(after_lufs=-14.0), export=WAV,
                         expected_lufs=-14.0)
    assert "loudest" in _by_key(rep2)["loudness"]["detail"]
    # Missing its album level by 2 LU is still a fail.
    rep3 = release_check(_signal(), SR, mastering=_mastering(after_lufs=-22.0), export=WAV,
                         expected_lufs=-20.0)
    assert _by_key(rep3)["loudness"]["status"] == "fail"


def test_true_peak_over_ceiling_fails():
    rep = release_check(_signal(), SR, mastering=_mastering(tp=-0.6), export=WAV)
    assert _by_key(rep)["true_peak"]["status"] == "fail"
    assert rep["status"] == "fail" and rep["failed"] == 1


def test_clipped_upload_warns():
    x = _signal(peak=0.5)
    x[1000:2000, :] = 1.0                      # a flat-topped burst
    assert count_clipped(x) >= 1000
    rep = release_check(_signal(), SR, mastering=_mastering(), export=WAV, x_in=x)
    c = _by_key(rep)["source_clipping"]
    assert c["status"] == "warn" and "samples" in c["value"]
    # The same count can be handed over from an earlier pass.
    rep2 = release_check(_signal(), SR, mastering=_mastering(), export=WAV, clipped_samples=5)
    assert _by_key(rep2)["source_clipping"]["status"] == "pass"


def test_silence_at_the_edges_warns():
    y = _signal(seconds=35.0, head_silence_s=2.0, tail_silence_s=7.0)
    rep = release_check(y, SR, mastering=_mastering(), export=WAV)
    checks = _by_key(rep)
    assert checks["head_silence"]["status"] == "warn"
    assert checks["tail_silence"]["status"] == "warn"
    assert checks["head_silence"]["value"].startswith("2.0 s")
    assert rep["warned"] == 2


def test_short_lossy_unmastered_file_warns_everywhere_it_should():
    y = _signal(seconds=12.0)
    rep = release_check(y, SR, mastering={"enabled": False},
                        export={"format": "mp3", "bit_depth": None}, lufs_out=-17.0)
    checks = _by_key(rep)
    assert checks["loudness"]["status"] == "warn"      # not mastered
    assert checks["format"]["status"] == "warn"        # lossy
    assert checks["duration"]["status"] == "warn"      # under 30 s
    assert checks["true_peak"]["status"] == "pass"     # measured from the audio
    assert rep["status"] == "warn"


def test_dc_offset_and_mono_checks():
    y = _signal()
    y[:, 0] += 0.02
    rep = release_check(y, SR, mastering=_mastering(), export=WAV, correlation=-0.3)
    checks = _by_key(rep)
    assert checks["dc_offset"]["status"] == "warn"
    assert checks["mono"]["status"] == "warn"
    rep2 = release_check(_signal(), SR, mastering=_mastering(), export=WAV, correlation=None)
    assert _by_key(rep2)["mono"]["status"] == "info"


def test_unusual_sample_rate_warns():
    rep = release_check(_signal(), 32000, mastering=_mastering(), export=WAV)
    assert _by_key(rep)["sample_rate"]["status"] == "warn"
    rep2 = release_check(_signal(), 96000, mastering=_mastering(), export=WAV)
    assert _by_key(rep2)["sample_rate"]["status"] == "pass"


def test_tags_added_later_change_the_verdict():
    rep = release_check(_signal(), SR, mastering=_mastering(), export=WAV)
    assert "tags" not in _by_key(rep) and rep["status"] == "pass"
    rep = add_check(rep, tags_check({"title": "Song"}, True))
    assert _by_key(rep)["tags"]["status"] == "warn"
    assert "artist" in _by_key(rep)["tags"]["detail"]
    assert rep["status"] == "warn"
    rep = add_check(rep, tags_check(GOOD_TAGS, True))       # replaces, not duplicates
    assert sum(1 for c in rep["checks"] if c["key"] == "tags") == 1
    assert rep["status"] == "pass"
    assert tags_check(None, False)["status"] == "warn"


def test_platform_changes_read_right():
    loud = {p["name"]: p for p in platform_changes(-9.0)}
    assert loud["Spotify"]["change_db"] == pytest.approx(-5.0)
    assert loud["Spotify"]["note"] == "turned down 5.0 dB"
    assert loud["Apple Music"]["note"] == "turned down 7.0 dB"
    quiet = {p["name"]: p for p in platform_changes(-16.0)}
    assert quiet["YouTube"]["note"] == "played as is (no boost)"
    assert quiet["Spotify"]["note"] == "turned up 2.0 dB at most"
    assert quiet["Apple Music"]["note"] == "played as is"
    assert platform_changes(None) == []


def test_summary_lists_the_flags():
    rep = release_check(_signal(seconds=10.0), SR, mastering=_mastering(after_lufs=-15.0),
                        export=WAV)
    s = summary(rep)
    assert s["status"] == "warn" and "Loudness" in s["flags"] and "Length" in s["flags"]
    assert summary(None) is None


# ── Through the server ───────────────────────────────────────────────────

def _run(client, buf, data, name="song.wav"):
    r = client.post("/api/process", files={"file": (name, buf, "audio/wav")}, data=data)
    assert r.status_code == 200, r.text
    jid = r.json()["job_id"]
    deadline = time.time() + 120
    while time.time() < deadline:
        m = client.get(f"/api/metrics/{jid}")
        if m.status_code == 200 and m.json().get("status") == "done":
            return m.json()["metrics"]
        assert m.status_code != 500, m.text
        time.sleep(0.2)
    raise AssertionError("job did not finish")


def _wav(x):
    soundfile = pytest.importorskip("soundfile")
    buf = io.BytesIO()
    soundfile.write(buf, x, SR, format="WAV")
    buf.seek(0)
    return buf


@pytest.fixture()
def client():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from shimmer.server import app
    with TestClient(app) as c:
        yield c


def test_mastered_job_carries_the_release_check(client):
    params = json.dumps({"preset": "generic", "mastering": {"enabled": True, "target": "streaming"},
                         "tags": {"enabled": True, "artist": "The Treq", "album": "LTWB"}})
    metrics = _run(client, _wav(_signal(seconds=4.0)), {"params": params, "output_format": "wav"})
    rel = metrics["release"]
    assert rel and rel["status"] in ("pass", "warn")
    keys = {c["key"] for c in rel["checks"]}
    assert {"loudness", "true_peak", "source_clipping", "sample_rate", "format",
            "head_silence", "tail_silence", "duration", "mono", "tags", "isrc"} <= keys
    checks = {c["key"]: c for c in rel["checks"]}
    assert checks["loudness"]["status"] == "pass"
    assert checks["true_peak"]["status"] == "pass"
    assert checks["duration"]["status"] == "warn"          # a 4 s test file
    assert checks["tags"]["status"] == "pass"              # title from the name, artist and album given
    assert len(rel["platforms"]) == 6


def test_unmastered_job_has_no_release_check(client):
    params = json.dumps({"preset": "generic", "mastering": {"enabled": False}})
    metrics = _run(client, _wav(_signal(seconds=3.0)), {"params": params, "output_format": "wav"})
    assert metrics["release"] is None
