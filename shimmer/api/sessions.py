"""Sessions: the song is uploaded once, and every tab reuses it
(docs/API.md §2 and §1 decision 1).

A rewrite of shimmer/preview_store.py (ARCHITECTURE §16: Rewrite). The
session keeps the names the 1.x routes use (samples, sr, original_path,
track_analysis, repair_lines, digest, stems, stems_info), so Remix and the
stem routes work unchanged while they wait for their turn to move.

Fixes against 1.1.1:

- **The original file lives in the session's folder,** so it is deleted with
  the session. 1.1.1 wrote every upload to a separate temporary folder that
  nothing ever removed (ARCHITECTURE §10).
- **Exports read `original_path`, the whole file.** The session's samples
  are a preview copy that stops at 30 minutes (API.md §0).
- **A silent upload no longer fails.** Its loudness is -inf, which JSON
  cannot carry; it is sent as null.
"""
from __future__ import annotations

import asyncio
import math
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from .. import core
from .. import projects_store, stems

# Files longer than this still upload and export whole; the preview copy
# kept in memory stops here (float32 stereo at 48 kHz is ~22 MB a minute).
MAX_SECONDS_CACHED = 30 * 60
# A session unused this long is removed, with its folder and original.
SESSION_TTL_SECONDS = 60 * 60


def clamp_samples_for_preview(x: np.ndarray, sr: int) -> np.ndarray:
    """The preview copy: at most MAX_SECONDS_CACHED of the song."""
    max_n = int(MAX_SECONDS_CACHED * sr)
    return x[:max_n].copy() if x.shape[0] > max_n else x


@dataclass(eq=False)
class Session:
    id: str
    workdir: str
    source: core.Source                   # the preview copy
    original_path: str                    # the whole uploaded file
    original_name: str
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    track_analysis: Dict[str, Any] = field(default_factory=dict)
    repair_lines: list = field(default_factory=list)
    digest: str = ""
    stems: Optional[Dict[str, np.ndarray]] = None
    stems_info: Dict[str, Any] = field(default_factory=dict)

    @property
    def samples(self) -> np.ndarray:
        return self.source.audio

    @property
    def sr(self) -> int:
        return self.source.sr

    @property
    def duration_s(self) -> float:
        return float(self.samples.shape[0] / self.sr)

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])

    def touch(self) -> None:
        self.last_used = time.time()

    def cleanup(self) -> None:
        if self.workdir and os.path.isdir(self.workdir):
            shutil.rmtree(self.workdir, ignore_errors=True)


class SessionStore:
    """The sessions of this server process."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}

    def reserve(self) -> Tuple[str, str]:
        """A new session id and its folder, to write the upload into."""
        sid = uuid.uuid4().hex
        return sid, tempfile.mkdtemp(prefix=f"shimmer_sess_{sid[:8]}_")

    def create(self, samples: np.ndarray, sr: int, original_path: str,
               original_name: str, sid: Optional[str] = None,
               workdir: Optional[str] = None) -> Session:
        if sid is None or workdir is None:
            sid, workdir = self.reserve()
        sess = Session(id=sid, workdir=workdir,
                       source=core.Source.from_array(samples, sr, path=original_path),
                       original_path=original_path, original_name=original_name)
        self._sessions[sid] = sess
        return sess

    def get(self, sid: str) -> Optional[Session]:
        s = self._sessions.get(sid)
        if s is not None:
            s.touch()
        return s

    def drop(self, sid: str) -> None:
        s = self._sessions.pop(sid, None)
        if s is not None:
            s.cleanup()

    def sweep(self, now: Optional[float] = None) -> int:
        now = now if now is not None else time.time()
        stale = [sid for sid, s in self._sessions.items()
                 if (now - s.last_used) > SESSION_TTL_SECONDS]
        for sid in stale:
            self._sessions.pop(sid).cleanup()
        return len(stale)

    def __len__(self) -> int:
        return len(self._sessions)


SESSIONS = SessionStore()


def _json_safe(v: Any) -> Any:
    """Replace inf and NaN, which JSON cannot carry, with None."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v


router = APIRouter()


@router.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> JSONResponse:
    """Take the song once, decode it, and open a session for every tab."""
    sid, workdir = SESSIONS.reserve()
    name = Path(file.filename or "upload").name
    original = os.path.join(workdir, "input_" + name)
    with open(original, "wb") as f:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)

    loop = asyncio.get_running_loop()
    try:
        x, sr = await loop.run_in_executor(None, core.load_audio, original)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(400, f"Could not decode '{name}': {e}")
    x = clamp_samples_for_preview(x, sr)

    analysis = await loop.run_in_executor(None, core.analyze_track, x, sr)
    # Both edges are scanned for render glitches. Reported, never applied:
    # the screen raises it and the user decides.
    edges = await loop.run_in_executor(None, core.detect_edge_artifacts, x, sr)
    digest = await loop.run_in_executor(None, core.file_digest, original)
    lines = await loop.run_in_executor(None, core.scan_fixed_lines, x, sr)
    source_tags = await loop.run_in_executor(None, core.tags.read_tags, original)

    sess = SESSIONS.create(samples=x, sr=sr, original_path=original,
                           original_name=name, sid=sid, workdir=workdir)
    sess.track_analysis = analysis
    sess.digest = digest
    sess.repair_lines = lines
    SESSIONS.sweep()
    return JSONResponse(_json_safe({
        "session_id": sess.id,
        "source_tags": source_tags,
        "title_hint": core.tags.title_from_stem(Path(name).stem),
        "sample_rate": sr,
        "channels": sess.channels,
        "duration_s": sess.duration_s,
        "name": name,
        "analysis": analysis,
        "edges": edges,
        "repair": {"lines": lines, "plan": core.plan_from_lines(lines, sr).as_dict()},
        "digest": digest,
        # Any tier with a finished stem set for this exact file: the Remix
        # tab separates instantly on those.
        "stems_cached": bool(stems.cached_models(digest)),
        "stems_tiers": stems.cached_tiers(digest),
        "project": projects_store.load_project(digest),
    }))


@router.get("/api/envelope/{session_id}")
async def envelope(session_id: str, start_s: float = 0.0, end_s: float = 1.0,
                   points: int = 600) -> JSONResponse:
    """Peak envelope in dBFS over a time range, for the Trim view.

    In dB rather than linear amplitude on purpose: the artifacts this view
    exists to show sit near -50 dBFS, which is a flat line on a linear
    waveform. Served from the session, so zooming costs no upload.
    """
    sess = SESSIONS.get(session_id)
    if sess is None:
        raise HTTPException(404, "Unknown session_id")
    sr = sess.sr
    n = sess.samples.shape[0]
    a = int(np.clip(round(start_s * sr), 0, n))
    b = int(np.clip(round(end_s * sr), a + 1, n))
    points = int(np.clip(points, 16, 4000))
    seg = np.max(np.abs(sess.samples[a:b]), axis=1)
    # One bucket per output point; peak within each so a single-sample
    # click survives downsampling instead of averaging away.
    idx = np.linspace(0, seg.shape[0], points + 1).astype(np.int64)
    peaks = np.array([seg[idx[i]:max(idx[i] + 1, idx[i + 1])].max() for i in range(points)],
                     dtype=np.float64)
    db = 20.0 * np.log10(peaks + 1e-9)
    return JSONResponse({"start_s": a / sr, "end_s": b / sr, "sample_rate": sr,
                         "db": [round(float(v), 2) for v in db]})


@router.delete("/api/upload/{session_id}")
async def drop(session_id: str) -> JSONResponse:
    SESSIONS.drop(session_id)
    return JSONResponse({"ok": True})
