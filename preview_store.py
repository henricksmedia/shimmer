"""
preview_store.py — In-memory cache for live-preview sessions.

A PreviewSession holds a single decoded audio file (samples + sample rate)
plus a per-session workdir into which we write small WAV slices that the
browser fetches as the user moves sliders.

The decoded array stays resident so that re-rendering a 10 s slice on every
slider change is just a numpy slice + engine.process() call — no re-decode,
no re-upload.

Memory budget: float32 stereo @ 48 kHz is ~22 MB / minute.  We cap a single
session at MAX_SECONDS_CACHED to avoid blowing host RAM on very long files.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np


# Hard cap on how much of a file we keep in RAM for live preview.
# Files longer than this still upload fine; preview just clamps to the
# first N seconds.  Adjust if you have a beefy machine.
MAX_SECONDS_CACHED = 30 * 60  # 30 minutes

# Sessions older than this with no activity get evicted.
SESSION_TTL_SECONDS = 60 * 60  # 1 hour


@dataclass
class PreviewSession:
    id: str
    workdir: str
    samples: np.ndarray          # shape (n, channels), float32
    sr: int
    original_path: str           # path of the raw uploaded file (kept as-is)
    original_name: str           # original filename for downloads
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    # Latest preview render id; previous renders get GC'd on each new call.
    current_render_id: str = ""

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


class PreviewStore:
    """Single-process registry of live-preview sessions."""

    def __init__(self) -> None:
        self._sessions: Dict[str, PreviewSession] = {}

    def create(self, samples: np.ndarray, sr: int,
               original_path: str, original_name: str) -> PreviewSession:
        sid = uuid.uuid4().hex
        workdir = tempfile.mkdtemp(prefix=f"shimmer_prev_{sid[:8]}_")
        sess = PreviewSession(
            id=sid, workdir=workdir,
            samples=samples, sr=sr,
            original_path=original_path,
            original_name=original_name,
        )
        self._sessions[sid] = sess
        return sess

    def get(self, sid: str) -> Optional[PreviewSession]:
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
        stale = [
            sid for sid, s in self._sessions.items()
            if (now - s.last_used) > SESSION_TTL_SECONDS
        ]
        for sid in stale:
            self._sessions[sid].cleanup()
            del self._sessions[sid]
        return len(stale)


PREVIEW_STORE = PreviewStore()


def clamp_samples_for_preview(x: np.ndarray, sr: int) -> np.ndarray:
    """Trim a decoded array to MAX_SECONDS_CACHED to bound preview RAM."""
    max_n = int(MAX_SECONDS_CACHED * sr)
    if x.shape[0] > max_n:
        return x[:max_n].copy()
    return x
