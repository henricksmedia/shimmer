"""
jobs.py — Per-request job state for the HTTP server.

A Job owns:
  - a UUID
  - a temp directory holding the original upload + processed outputs
  - a progress queue the worker pushes into and the SSE route consumes
  - measurement results once the worker finishes

Jobs are kept in `JOB_STORE` (an in-memory dict) for the lifetime of the
process.  A simple TTL sweep evicts jobs older than `JOB_TTL_SECONDS`.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


JOB_TTL_SECONDS = 60 * 60  # 1 hour


@dataclass
class Job:
    id: str
    workdir: str
    original_path: str = ""
    processed_path: str = ""
    diff_path: str = ""
    output_ext: str = ".wav"
    created_at: float = field(default_factory=time.time)
    status: str = "queued"  # queued | running | done | error
    error: str = ""
    progress: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    def cleanup(self) -> None:
        if self.workdir and os.path.isdir(self.workdir):
            shutil.rmtree(self.workdir, ignore_errors=True)


class JobStore:
    """Thread-safe (single-loop) job registry."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}

    def create(self, output_ext: str = ".wav") -> Job:
        jid = uuid.uuid4().hex
        workdir = tempfile.mkdtemp(prefix=f"shimmer_{jid[:8]}_")
        job = Job(id=jid, workdir=workdir, output_ext=output_ext)
        self._jobs[jid] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def sweep(self, now: Optional[float] = None) -> int:
        """Delete jobs older than TTL.  Returns number removed."""
        now = now if now is not None else time.time()
        stale = [
            jid for jid, j in self._jobs.items()
            if (now - j.created_at) > JOB_TTL_SECONDS
        ]
        for jid in stale:
            self._jobs[jid].cleanup()
            del self._jobs[jid]
        return len(stale)


JOB_STORE = JobStore()
