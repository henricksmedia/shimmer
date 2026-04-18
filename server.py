"""
server.py — Shimmer by The Treq: FastAPI backend.

Endpoints:
    GET  /                       → static index.html
    GET  /static/*               → static assets (css, js)
    GET  /api/presets            → list of presets + their full Params
    POST /api/process            → multipart file + JSON params → job_id
    GET  /api/progress/{job_id}  → SSE stream of processing progress
    GET  /api/result/{job_id}?kind={processed|diff|original}
                                 → streams the finished file (or 202 if not ready)
    GET  /api/metrics/{job_id}   → measurements dict (or 202 if not ready)
    POST /api/suggest            → multipart file → {preset, scores, ...}
    POST /api/batch              → JSON body; SSE stream of per-file status
    GET  /api/settings           → last-saved UI settings
    POST /api/settings           → save UI settings

Runs single-user, single-job-in-flight.  CPU-heavy `process()` is pushed
onto a thread executor so the event loop stays responsive.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict

from fastapi import (
    FastAPI, UploadFile, File, Form, HTTPException, Request,
    BackgroundTasks,
)
from fastapi.responses import (
    FileResponse, JSONResponse, StreamingResponse, HTMLResponse,
)
from fastapi.staticfiles import StaticFiles

from audio_io import (
    load_audio, save_audio, measure, preserve_volume, clip_protect,
    process_file,
)
from engine import process
from dsp import as_2d
from jobs import JOB_STORE, Job
from params import Params
from presets import PRESETS, PRESET_NAMES, get_preset, describe_preset
from settings_store import load_settings, save_settings


HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"

app = FastAPI(title="Shimmer by The Treq")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

def _params_from_json(data: Dict[str, Any]) -> Params:
    """Build a Params instance from a preset name + override dict.

    Expected shape: {"preset": "suno_v5", "overrides": {"thr_db": 7.0, ...}}
    """
    preset_name = data.get("preset") or "generic"
    p = get_preset(preset_name)
    for key, value in (data.get("overrides") or {}).items():
        if hasattr(p, key) and value is not None:
            try:
                current = getattr(p, key)
                if isinstance(current, bool):
                    setattr(p, key, bool(value))
                elif isinstance(current, int):
                    setattr(p, key, int(value))
                else:
                    setattr(p, key, float(value))
            except (TypeError, ValueError):
                pass
    return p


def _threadsafe_progress_pusher(job: Job, loop: asyncio.AbstractEventLoop):
    """Return a callback(fraction) that pushes into the job's asyncio.Queue
    from a worker thread."""
    def _cb(fraction: float) -> None:
        job.progress = float(fraction)
        asyncio.run_coroutine_threadsafe(
            job.queue.put({"fraction": float(fraction)}), loop)
    return _cb


def _run_job_sync(job: Job, upload_path: str, params: Params,
                  preserve_vol: bool, progress_cb) -> None:
    """CPU-bound worker: runs in a thread executor."""
    x, sr = load_audio(upload_path)
    meas_in = measure(x)
    y = process(x, sr, params, progress_callback=progress_cb)
    y2 = as_2d(y)
    if preserve_vol:
        y2 = preserve_volume(y2, meas_in["peak_linear"])
    y2 = clip_protect(y2)
    meas_out = measure(y2)

    processed_path = os.path.join(
        job.workdir, f"processed{job.output_ext}")
    diff_path = os.path.join(job.workdir, f"removed{job.output_ext}")
    save_audio(processed_path, y2, sr)
    n = min(x.shape[0], y2.shape[0])
    diff = (x[:n, :] - y2[:n, :]).astype("float32") * 5.0
    diff = clip_protect(diff)
    save_audio(diff_path, diff, sr)

    job.processed_path = processed_path
    job.diff_path = diff_path
    job.metrics = {
        "sample_rate": sr,
        "channels": int(x.shape[1]),
        "duration_s": float(x.shape[0] / sr),
        "input": meas_in,
        "output": meas_out,
    }


async def _run_job_async(job: Job, upload_path: str, params: Params,
                         preserve_vol: bool) -> None:
    """Schedule the worker on the default executor; push done sentinel."""
    loop = asyncio.get_running_loop()
    cb = _threadsafe_progress_pusher(job, loop)
    job.status = "running"
    try:
        await loop.run_in_executor(
            None, _run_job_sync,
            job, upload_path, params, preserve_vol, cb)
        job.progress = 1.0
        job.status = "done"
        await job.queue.put({"fraction": 1.0, "done": True})
    except Exception as e:  # noqa: BLE001
        job.status = "error"
        job.error = str(e)
        await job.queue.put({"error": str(e), "done": True})


# ───────────────────────────────────────────────────────────────────────────
# Pages & static
# ───────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


# ───────────────────────────────────────────────────────────────────────────
# Presets & settings
# ───────────────────────────────────────────────────────────────────────────

@app.get("/api/presets")
async def api_presets() -> JSONResponse:
    items = []
    for name in PRESET_NAMES:
        p = get_preset(name)
        items.append({
            "name": name,
            "description": describe_preset(name),
            "values": asdict(p),
        })
    return JSONResponse({"presets": items, "default": "generic"})


@app.get("/api/settings")
async def api_settings_get() -> JSONResponse:
    return JSONResponse(load_settings())


@app.post("/api/settings")
async def api_settings_post(payload: Dict[str, Any]) -> JSONResponse:
    save_settings(payload or {})
    return JSONResponse({"ok": True})


# ───────────────────────────────────────────────────────────────────────────
# Single-file processing
# ───────────────────────────────────────────────────────────────────────────

@app.post("/api/process")
async def api_process(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    params: str = Form(...),
    preserve_volume: bool = Form(True),
    output_format: str = Form("wav"),
) -> JSONResponse:
    try:
        params_data = json.loads(params)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid params JSON: {e}")

    try:
        p = _params_from_json(params_data)
    except KeyError as e:
        raise HTTPException(400, f"Unknown preset: {e}")

    output_ext = "." + output_format.lstrip(".").lower()
    if output_ext not in {".wav", ".flac", ".mp3", ".ogg", ".m4a"}:
        raise HTTPException(400, f"Unsupported output format: {output_format}")

    job = JOB_STORE.create(output_ext=output_ext)

    orig_name = Path(file.filename or "upload").name
    job.original_path = os.path.join(job.workdir, "input_" + orig_name)
    with open(job.original_path, "wb") as f:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)

    # Fire-and-forget worker task; progress flows via job.queue → SSE.
    asyncio.create_task(_run_job_async(job, job.original_path, p, preserve_volume))
    JOB_STORE.sweep()
    return JSONResponse({"job_id": job.id})


@app.get("/api/progress/{job_id}")
async def api_progress(job_id: str, request: Request) -> StreamingResponse:
    job = JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")

    async def event_stream():
        # Send the current status first so late subscribers get context.
        yield _sse_event({
            "fraction": job.progress,
            "status": job.status,
        })
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(job.queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield _sse_event(msg)
            if msg.get("done"):
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/metrics/{job_id}")
async def api_metrics(job_id: str) -> JSONResponse:
    job = JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    if job.status == "error":
        raise HTTPException(500, job.error or "Job failed")
    if job.status != "done":
        return JSONResponse({"status": job.status}, status_code=202)
    return JSONResponse({
        "status": "done",
        "metrics": job.metrics,
    })


@app.get("/api/result/{job_id}")
async def api_result(job_id: str, kind: str = "processed") -> FileResponse:
    job = JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    if job.status == "error":
        raise HTTPException(500, job.error or "Job failed")
    if job.status != "done":
        raise HTTPException(202, "Job not finished")

    path = {
        "processed": job.processed_path,
        "diff":      job.diff_path,
        "original":  job.original_path,
    }.get(kind)
    if not path or not os.path.isfile(path):
        raise HTTPException(404, f"No {kind} artefact for this job")

    ext = os.path.splitext(path)[1].lower()
    media = {
        ".wav": "audio/wav", ".flac": "audio/flac",
        ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
    }.get(ext, "application/octet-stream")
    download_name = f"{kind}{ext}"
    return FileResponse(path, media_type=media, filename=download_name)


# ───────────────────────────────────────────────────────────────────────────
# Suggest preset
# ───────────────────────────────────────────────────────────────────────────

@app.post("/api/suggest")
async def api_suggest(file: UploadFile = File(...)) -> JSONResponse:
    from probe import suggest_preset  # local import: heavier scipy path

    import tempfile
    with tempfile.NamedTemporaryFile(
            suffix=Path(file.filename or "x.wav").suffix,
            delete=False) as tmp:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            tmp.write(chunk)
        tmp_path = tmp.name
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, suggest_preset, tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return JSONResponse(result)


# ───────────────────────────────────────────────────────────────────────────
# Batch
# ───────────────────────────────────────────────────────────────────────────

@app.post("/api/batch")
async def api_batch(payload: Dict[str, Any]) -> StreamingResponse:
    input_folder = (payload.get("input_folder") or "").strip()
    output_folder = (payload.get("output_folder") or "").strip()
    preset = payload.get("preset") or "generic"
    preserve_vol = bool(payload.get("preserve_volume", True))
    output_format = (payload.get("output_format") or "wav").lstrip(".").lower()

    if not input_folder or not os.path.isdir(input_folder):
        raise HTTPException(400, f"Input folder not found: {input_folder}")
    if not output_folder:
        output_folder = input_folder.rstrip("/\\") + "_deshimmered"
    os.makedirs(output_folder, exist_ok=True)

    try:
        params = get_preset(preset)
    except KeyError as e:
        raise HTTPException(400, f"Unknown preset: {e}")

    patterns = ["*.wav", "*.WAV", "*.mp3", "*.MP3",
                "*.flac", "*.FLAC", "*.ogg", "*.m4a"]
    files = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(input_folder, pat)))
    files = sorted(set(files))

    async def stream():
        yield _sse_event({
            "type": "start",
            "total": len(files),
            "output_folder": output_folder,
            "preset": preset,
        })
        if not files:
            yield _sse_event({"type": "end",
                              "message": "No audio files found"})
            return
        loop = asyncio.get_running_loop()
        for i, src in enumerate(files):
            name = os.path.basename(src)
            dst = os.path.join(
                output_folder, os.path.splitext(name)[0] + "." + output_format)
            yield _sse_event({"type": "file_start", "index": i, "name": name})
            try:
                r = await loop.run_in_executor(
                    None, _batch_one, src, dst, params, preserve_vol)
                yield _sse_event({
                    "type": "file_done", "index": i, "name": name,
                    "duration_s": r["duration_s"],
                    "peak_in_db": r["input"]["peak_dbfs"],
                    "peak_out_db": r["output"]["peak_dbfs"],
                })
            except Exception as e:  # noqa: BLE001
                yield _sse_event({
                    "type": "file_error", "index": i, "name": name,
                    "error": str(e),
                })
        yield _sse_event({"type": "end", "total": len(files)})

    return StreamingResponse(stream(), media_type="text/event-stream")


def _batch_one(src: str, dst: str, params: Params, preserve_vol: bool):
    return process_file(
        input_path=src, output_path=dst,
        params=params, do_preserve_volume=preserve_vol,
    )


# ───────────────────────────────────────────────────────────────────────────
# SSE helper
# ───────────────────────────────────────────────────────────────────────────

def _sse_event(data: Dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"
