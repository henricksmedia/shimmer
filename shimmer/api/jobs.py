"""One job runner: the progress stream, and cancel (docs/ARCHITECTURE.md
§18.3).

A rewrite of shimmer/jobs.py (ARCHITECTURE §16: Rewrite). A Job keeps the
fields the 1.x routes use, so Remix and stem jobs run unchanged while they
wait for their turn to move.

Fixes against 1.1.1:

- **Any number of listeners.** 1.1.1 handed each progress event to
  whichever listener took it first, so a second tab or a reconnect stole
  events (docs/API.md §4). Now every event is kept, and each listener reads
  all of them from the start.
- **Cancel.** A job the new engine runs checks for cancel between stages and
  stops. A 1.x job (Remix, stems) runs to the end; cancelling one says so.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import core
from ..core import Progress

JOB_TTL_SECONDS = 60 * 60  # 1 hour
KEEPALIVE_S = 15.0


@dataclass(eq=False)
class Job:
    id: str
    workdir: str
    original_path: str = ""
    processed_path: str = ""
    diff_path: str = ""
    # Silence-trimmed export variant; playback always streams processed_path
    # so the synced A/B/C player keeps a shared clock.
    trimmed_path: str = ""
    # Copy of the export written into the user's chosen folder.
    saved_path: str = ""
    output_ext: str = ".wav"
    # The song's name, for download filenames.
    source_stem: str = "audio"
    # 1.x jobs name their preset in their download filenames.
    preset_name: str = "generic"
    created_at: float = field(default_factory=time.time)
    status: str = "queued"  # queued | running | done | error | cancelled
    error: str = ""
    progress: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)
    # Producers put events here (1.x workers do it directly).
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    # Every event so far, for every listener.
    events: List[Dict[str, Any]] = field(default_factory=list)
    # Set when the job runs on the new engine, which can stop between stages.
    run: Optional[Progress] = None
    _changed: Optional[asyncio.Event] = field(default=None, repr=False)
    _pump: Optional[asyncio.Task] = field(default=None, repr=False)

    def cancel(self) -> bool:
        """Ask the job to stop. False when this job cannot stop early."""
        if self.run is None or self.status not in ("queued", "running"):
            return False
        self.run.cancel()
        return True

    def cleanup(self) -> None:
        if self.workdir and os.path.isdir(self.workdir):
            shutil.rmtree(self.workdir, ignore_errors=True)


class JobStore:
    """The jobs of this server process."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}

    def create(self, output_ext: str = ".wav") -> Job:
        jid = uuid.uuid4().hex
        job = Job(id=jid, workdir=tempfile.mkdtemp(prefix=f"shimmer_{jid[:8]}_"),
                  output_ext=output_ext)
        self._jobs[jid] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def sweep(self, now: Optional[float] = None) -> int:
        """Delete jobs older than the TTL. Returns how many were removed."""
        now = now if now is not None else time.time()
        stale = [jid for jid, j in self._jobs.items() if (now - j.created_at) > JOB_TTL_SECONDS]
        for jid in stale:
            self._jobs.pop(jid).cleanup()
        return len(stale)


JOB_STORE = JobStore()


def pusher(job: Job, loop: asyncio.AbstractEventLoop) -> Progress:
    """A Progress for a worker thread: stages and fractions become events on
    the job, and job.cancel() reaches the worker."""
    def on_fraction(f: float) -> None:
        job.progress = f
        asyncio.run_coroutine_threadsafe(job.queue.put({"fraction": f}), loop)

    def on_stage(key: str, label: str, detail: str) -> None:
        asyncio.run_coroutine_threadsafe(
            job.queue.put({"fraction": float(job.progress), "stage": key,
                           "status": label, "detail": detail}), loop)

    job.run = Progress(on_stage=on_stage, on_fraction=on_fraction)
    return job.run


def _notify(job: Job) -> None:
    if job._changed is not None:
        job._changed.set()
    job._changed = asyncio.Event()


async def _pump_events(job: Job) -> None:
    """Move events from the job's queue into its history, waking listeners."""
    while True:
        msg = await job.queue.get()
        job.events.append(msg)
        _notify(job)
        if msg.get("done"):
            return


async def events(job: Job, is_disconnected):
    """Every event of the job, from the first, then new ones as they come.
    Yields None as a keepalive when nothing has happened for a while."""
    if job._changed is None:
        job._changed = asyncio.Event()
    if job._pump is None:
        job._pump = asyncio.create_task(_pump_events(job))
    i = 0
    while True:
        if await is_disconnected():
            return
        changed = job._changed                    # taken before reading, so no event is missed
        while i < len(job.events):
            msg = job.events[i]
            i += 1
            yield msg
            if msg.get("done"):
                return
        try:
            await asyncio.wait_for(changed.wait(), timeout=KEEPALIVE_S)
        except asyncio.TimeoutError:
            yield None


async def finish(job: Job, error: Optional[BaseException] = None) -> None:
    """Record how a job ended and send the last event."""
    if error is None:
        job.progress = 1.0
        job.status = "done"
        await job.queue.put({"fraction": 1.0, "done": True})
    elif isinstance(error, core.Cancelled):
        job.status = "cancelled"
        job.error = "Cancelled"
        await job.queue.put({"error": "Cancelled", "cancelled": True, "done": True})
    else:
        job.status = "error"
        job.error = str(error)
        await job.queue.put({"error": str(error), "done": True})
