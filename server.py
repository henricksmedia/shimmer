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
    POST /api/browse-folder       → open native folder picker, return path
    GET  /api/settings           → last-saved UI settings
    POST /api/settings           → save UI settings
    POST /api/upload             → upload a file once, get a session_id
    DELETE /api/upload/{sid}     → release a preview session
    POST /api/preview            → render a small slice for live A/B
    GET  /api/preview/{sid}/{rid}?kind={processed|diff}
                                 → stream the slice WAV

Runs single-user, single-job-in-flight.  CPU-heavy `process()` is pushed
onto a thread executor so the event loop stays responsive.
"""

from __future__ import annotations

import _winfix  # noqa: F401  # must precede scipy/numpy import on Windows

import asyncio
import glob
import json
import os
import struct
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from fastapi import (
    FastAPI, UploadFile, File, Form, HTTPException, Request,
    BackgroundTasks,
)
from fastapi.responses import (
    FileResponse, JSONResponse, StreamingResponse, HTMLResponse, Response,
)
from fastapi.staticfiles import StaticFiles

from audio_io import (
    load_audio, save_audio, measure, preserve_volume, clip_protect,
    process_file, encode_wav_bytes,
)
from engine import process, apply_post_filters
from dsp import as_2d, trim_silence as dsp_trim_silence
from jobs import JOB_STORE, Job
from params import Params, apply_preset_strength, MasterParams
from mastering import (
    master, master_params_from_json, analyze_track, measure_loudness,
    get_export_ceiling_dbtp,
)
from pipeline import clean_and_master
from presets import (
    PRESETS, PRESET_NAMES, VISIBLE_PRESETS,
    get_preset, describe_preset, label_for, is_visible,
)
from preview_store import PREVIEW_STORE, clamp_samples_for_preview
from settings_store import load_settings, save_settings


HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"

class _NoCacheStaticFiles(StaticFiles):
    """Static files that always revalidate so UI updates take effect
    immediately after a server upgrade (files are tiny; cost is nil)."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app = FastAPI(title="Shimmer by The Treq")
app.mount("/static", _NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

_FILENAME_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                     "0123456789-_.")


def _safe_filename_stem(s: str) -> str:
    """Strip filesystem-hostile chars from a filename stem.

    Spaces and parens become underscores; anything not in a small allowlist
    is dropped. Keeps output readable while guaranteeing it survives every
    OS / browser quoting rule for Content-Disposition.
    """
    out = []
    for c in (s or ""):
        if c in _FILENAME_SAFE:
            out.append(c)
        elif c in " ()[]":
            out.append("_")
    cleaned = "".join(out).strip("._-")
    return cleaned[:64]


def _finite_or_none(v: Any) -> Optional[float]:
    """JSON-safe float: -inf/nan (pyloudnorm on silence) become None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _params_from_json(data: Dict[str, Any]) -> Params:
    """Build a Params instance from a preset name + override dict.

    Expected shape:
        {
            "preset": "suno_hash",
            "preset_strength": 1.0,           # optional, 0..2, default 1.0
            "overrides": {"thr_db": 7.0, ...} # optional per-key overrides
        }

    Order of operations: preset -> preset_strength scaling (only on the
    whitelisted amount-style keys, see params.apply_preset_strength) ->
    explicit overrides (which always win, so the user can dial in any
    individual slider on top of the strength-scaled recipe).
    """
    preset_name = data.get("preset") or "generic"
    p = get_preset(preset_name)

    raw_strength = data.get("preset_strength")
    if raw_strength is not None:
        try:
            strength = float(raw_strength)
        except (TypeError, ValueError):
            strength = 1.0
        if strength < 0.0:
            strength = 0.0
        elif strength > 2.0:
            strength = 2.0
        if abs(strength - 1.0) > 1e-6:
            apply_preset_strength(p, strength)

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


def _master_params_from_request(data: Dict[str, Any]) -> MasterParams:
    return master_params_from_json(data.get("mastering") or {})


def _run_job_sync(job: Job, upload_path: str, params: Params,
                  preserve_vol: bool, progress_cb,
                  master_params: Optional[MasterParams] = None,
                  mastering_analysis: Optional[Dict[str, Any]] = None,
                  trim_silence: bool = False) -> None:
    """CPU-bound worker: runs in a thread executor."""
    x, sr = load_audio(upload_path)
    meas_in = measure(x)
    use_mastering = master_params is not None and master_params.enabled

    # RAW-input analysis: the tone curve must come from the unprocessed
    # signal, never from cleaned audio (post-clean tone match would
    # boost the harshness the cleaner removed).
    if use_mastering and mastering_analysis is None:
        mastering_analysis = analyze_track(x, sr)

    y2, removed, pipe_report = clean_and_master(
        x, sr, params,
        master_params=master_params if use_mastering else None,
        progress_callback=progress_cb,
        raw_analysis=mastering_analysis,
    )
    mastering_report: Dict[str, Any] = pipe_report.get(
        "mastering", {"enabled": False})

    if not use_mastering and preserve_vol:
        y2 = preserve_volume(
            y2, meas_in["peak_linear"], input_rms=meas_in["rms_linear"])
        y2 = clip_protect(y2)

    meas_out = measure(y2)
    # The removed-signal file is exported UNBOOSTED — audition boost is a
    # client-side monitoring gain only (never baked into files).
    diff = clip_protect(removed)

    # Input/output LUFS so the client can loudness-match A/B in every
    # state, not just when mastering ran (the report covers that case).
    loudness: Dict[str, Any] = {}
    if use_mastering:
        before = mastering_report.get("before") or {}
        after = mastering_report.get("after") or {}
        loudness = {
            "input_lufs_i": _finite_or_none(before.get("lufs_i")),
            "output_lufs_i": _finite_or_none(after.get("lufs_i")),
        }
    else:
        try:
            loudness = {
                "input_lufs_i": _finite_or_none(
                    measure_loudness(x, sr).get("lufs_i")),
                "output_lufs_i": _finite_or_none(
                    measure_loudness(y2, sr).get("lufs_i")),
            }
        except Exception:  # noqa: BLE001
            loudness = {}

    processed_path = os.path.join(
        job.workdir, f"processed{job.output_ext}")
    diff_path = os.path.join(job.workdir, f"removed{job.output_ext}")
    save_audio(processed_path, y2, sr)
    save_audio(diff_path, diff, sr)

    # Silence trim is an export-only variant: the playback files above stay
    # full length so the synced A/B/C player keeps a shared clock.
    trim_report: Dict[str, Any] = {"enabled": False}
    if trim_silence:
        y_trim, cut_head, cut_tail = dsp_trim_silence(y2, sr)
        trimmed_path = os.path.join(job.workdir, f"trimmed{job.output_ext}")
        save_audio(trimmed_path, y_trim, sr)
        job.trimmed_path = trimmed_path
        trim_report = {
            "enabled": True,
            "cut_head_s": round(cut_head, 3),
            "cut_tail_s": round(cut_tail, 3),
        }

    job.processed_path = processed_path
    job.diff_path = diff_path
    job.metrics = {
        "sample_rate": sr,
        "channels": int(x.shape[1]),
        "duration_s": float(x.shape[0] / sr),
        "input": meas_in,
        "output": meas_out,
        "pipeline": {
            "tone_curve_db": pipe_report.get("tone_curve_db", []),
            "side_width_compensation": pipe_report.get(
                "side_width_compensation", {}),
        },
        "mastering": mastering_report,
        "loudness": loudness,
        "trim": trim_report,
    }


async def _run_job_async(job: Job, upload_path: str, params: Params,
                         preserve_vol: bool,
                         master_params: Optional[MasterParams] = None,
                         mastering_analysis: Optional[Dict[str, Any]] = None,
                         trim_silence: bool = False) -> None:
    """Schedule the worker on the default executor; push done sentinel."""
    loop = asyncio.get_running_loop()
    cb = _threadsafe_progress_pusher(job, loop)
    job.status = "running"
    try:
        await loop.run_in_executor(
            None, _run_job_sync,
            job, upload_path, params, preserve_vol, cb,
            master_params, mastering_analysis, trim_silence)
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
    """List every resolvable preset key (visible artifact presets +
    legacy aliases). The frontend filters the dropdown by `visible: true`
    while still being able to look up a friendly label for an alias key
    that arrives via saved settings or auto-detect output."""
    items = []
    for name in PRESET_NAMES:
        p = get_preset(name)
        items.append({
            "name": name,
            "label": label_for(name),
            "description": describe_preset(name),
            "values": asdict(p),
            "visible": is_visible(name),
        })
    return JSONResponse({"presets": items, "default": "generic"})


@app.get("/api/settings")
async def api_settings_get() -> JSONResponse:
    return JSONResponse(load_settings())


@app.post("/api/settings")
async def api_settings_post(payload: Dict[str, Any]) -> JSONResponse:
    save_settings(payload or {})
    return JSONResponse({"ok": True})


@app.post("/api/browse-folder")
async def api_browse_folder(payload: Dict[str, Any] = {}) -> JSONResponse:
    """Open the OS-native folder picker and return the selected path.

    Optional payload: {"initial_dir": "D:\\...", "title": "Select folder"}
    Returns: {"path": "D:\\..."} or {"path": null} if cancelled.
    """
    initial_dir = (payload.get("initial_dir") or "").strip() or None
    title = (payload.get("title") or "").strip() or "Select folder"

    # Validate initial_dir exists; fall back to None if it doesn't.
    if initial_dir and not os.path.isdir(initial_dir):
        initial_dir = None

    loop = asyncio.get_running_loop()
    selected = await loop.run_in_executor(None, _open_folder_dialog, initial_dir, title)
    return JSONResponse({"path": selected})


def _open_folder_dialog(initial_dir: str | None, title: str) -> str | None:
    """Open tkinter folder dialog in a thread-safe way."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()          # hide the root window
    root.attributes('-topmost', True)  # bring dialog to front
    root.update()            # process events so attributes take effect

    kwargs: Dict[str, Any] = {"title": title, "parent": root}
    if initial_dir:
        kwargs["initialdir"] = initial_dir

    selected = filedialog.askdirectory(**kwargs)
    root.destroy()
    return selected if selected else None


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
    trim_silence: bool = Form(False),
) -> JSONResponse:
    try:
        params_data = json.loads(params)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid params JSON: {e}")

    try:
        p = _params_from_json(params_data)
    except KeyError as e:
        raise HTTPException(400, f"Unknown preset: {e}")

    mp = _master_params_from_request(params_data)
    mastering_analysis = params_data.get("mastering_analysis")

    output_ext = "." + output_format.lstrip(".").lower()
    if output_ext not in {".wav", ".flac", ".mp3", ".ogg", ".m4a"}:
        raise HTTPException(400, f"Unsupported output format: {output_format}")

    # Codec-aware true-peak ceiling: lossy encoders overshoot on decode,
    # so MP3/OGG/M4A exports get -1.5 dBTP unless the user explicitly
    # chose a ceiling.
    if (params_data.get("mastering") or {}).get("ceiling_dbtp") is None:
        mp.ceiling_dbtp = get_export_ceiling_dbtp(output_format)

    job = JOB_STORE.create(output_ext=output_ext)
    job.preset_name = params_data.get("preset") or "generic"

    orig_name = Path(file.filename or "upload").name
    job.source_stem = Path(orig_name).stem or "audio"
    job.original_path = os.path.join(job.workdir, "input_" + orig_name)
    with open(job.original_path, "wb") as f:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)

    # Fire-and-forget worker task; progress flows via job.queue → SSE.
    asyncio.create_task(_run_job_async(
        job, job.original_path, p, preserve_volume, mp, mastering_analysis,
        trim_silence))
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
        "trimmed":   job.trimmed_path,
    }.get(kind)
    if not path or not os.path.isfile(path):
        raise HTTPException(404, f"No {kind} artefact for this job")

    ext = os.path.splitext(path)[1].lower()
    media = {
        ".wav": "audio/wav", ".flac": "audio/flac",
        ".mp3": "audio/mpeg", ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
    }.get(ext, "application/octet-stream")
    # Make download filenames informative + unique-per-run so successive
    # downloads of different presets / different songs don't all collide on
    # `processed.wav` in the user's Downloads folder. Filesystem-safe stem +
    # short job id so old/new runs are visually distinguishable.
    safe_stem = _safe_filename_stem(job.source_stem) or "audio"
    safe_preset = _safe_filename_stem(job.preset_name) or "preset"
    short_id = job.id[:8]
    if kind == "original":
        download_name = f"{safe_stem}_original{ext}"
    else:
        suffix = {"diff": "removed", "trimmed": "trimmed"}.get(
            kind, "processed")
        download_name = (
            f"{safe_stem}_{safe_preset}_{suffix}_{short_id}{ext}"
        )
    return FileResponse(path, media_type=media, filename=download_name)


# ───────────────────────────────────────────────────────────────────────────
# Suggest preset
# ───────────────────────────────────────────────────────────────────────────

@app.post("/api/suggest")
async def api_suggest(file: UploadFile = File(...)) -> JSONResponse:
    """Artifact preset suggestion + loudness/spectrum analysis."""
    from probe import suggest_preset

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
        x, sr = await loop.run_in_executor(None, load_audio, tmp_path)
        analysis = await loop.run_in_executor(None, analyze_track, x, sr)
        result["analysis"] = analysis
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return JSONResponse(result)


@app.post("/api/analyze")
async def api_analyze(file: UploadFile = File(...)) -> JSONResponse:
    """Combined artifact detect + mastering analysis (alias of suggest)."""
    return await api_suggest(file)


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
    auto_detect = bool(payload.get("auto_detect", False))
    trim_silence = bool(payload.get("trim_silence", False))
    mp = master_params_from_json(payload.get("mastering") or {})
    # Codec-aware ceiling unless the user explicitly chose one.
    if (payload.get("mastering") or {}).get("ceiling_dbtp") is None:
        mp.ceiling_dbtp = get_export_ceiling_dbtp(output_format)

    # Preset strength: parse and clamp to [0, 2].
    raw_strength = payload.get("preset_strength")
    if raw_strength is not None:
        try:
            preset_strength = float(raw_strength)
        except (TypeError, ValueError):
            preset_strength = 1.0
        preset_strength = max(0.0, min(2.0, preset_strength))
    else:
        preset_strength = 1.0

    if not input_folder or not os.path.isdir(input_folder):
        raise HTTPException(400, f"Input folder not found: {input_folder}")
    if not output_folder:
        output_folder = input_folder.rstrip("/\\") + "_deshimmered"
    os.makedirs(output_folder, exist_ok=True)

    # Validate the explicit preset when not auto-detecting.
    if not auto_detect:
        try:
            get_preset(preset)
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
            "preset": "auto-detect" if auto_detect else preset,
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
                    None, _batch_one, src, dst, preset, preserve_vol,
                    auto_detect, preset_strength, mp, trim_silence)
                yield _sse_event({
                    "type": "file_done", "index": i, "name": name,
                    "duration_s": r["duration_s"],
                    "trim": r.get("trim"),
                    "peak_in_db": r["input"]["peak_dbfs"],
                    "peak_out_db": r["output"]["peak_dbfs"],
                    "detected_preset": r.get("detected_preset"),
                    "detected_label": r.get("detected_label"),
                    "detected_confidence": r.get("detected_confidence"),
                })
            except Exception as e:  # noqa: BLE001
                yield _sse_event({
                    "type": "file_error", "index": i, "name": name,
                    "error": str(e),
                })
        yield _sse_event({"type": "end", "total": len(files)})

    return StreamingResponse(stream(), media_type="text/event-stream")


def _batch_one(src: str, dst: str, preset_name: str, preserve_vol: bool,
               auto_detect: bool = False, preset_strength: float = 1.0,
               master_params: Optional[MasterParams] = None,
               trim_silence: bool = False):
    detected_info: Dict[str, Any] = {}

    if auto_detect:
        from probe import suggest_preset as _suggest
        from presets import label_for
        suggestion = _suggest(src)
        chosen = suggestion.get("preset") or "generic"
        ranked = suggestion.get("ranked") or []
        confidence = ranked[0]["confidence"] if ranked else 0.0
        detected_info = {
            "detected_preset": chosen,
            "detected_label": label_for(chosen),
            "detected_confidence": round(float(confidence), 2),
        }
        params = get_preset(chosen)
    else:
        params = get_preset(preset_name)

    # Apply preset strength scaling.
    if abs(preset_strength - 1.0) > 1e-6:
        apply_preset_strength(params, preset_strength)

    result = process_file(
        input_path=src, output_path=dst,
        params=params, do_preserve_volume=preserve_vol,
        master_params=master_params,
        trim_silence=trim_silence,
    )
    result.update(detected_info)
    return result


# ───────────────────────────────────────────────────────────────────────────
# Live preview — upload once, re-render slices on every slider change
# ───────────────────────────────────────────────────────────────────────────

# Pre-roll prepended to every preview slice so stateful stages (DenoiseStage's
# minimum-statistics noise PSD, DeCheckerStage's persistence EMA, etc.) have
# time to settle before the audible window begins.  Discarded after render.
_PREVIEW_PREROLL_S = 1.5
# Post-roll appended so the DSP block never truncates mid-window: STFT
# overlap-add, the FIR crossover group delay, envelope followers and the
# limiter lookahead all need audio AFTER the audible region or the loop
# end clicks/sputters.  0.5 s minimum per spec; FIR/lookahead margins are
# added on top in _preview_margin_s().
_PREVIEW_POSTROLL_S = 0.5


def _preview_margin_s(p: Params, sr: int,
                      master_params: Optional[MasterParams]) -> float:
    """Extra safety margin: FIR crossover group delay + limiter lookahead."""
    fir_delay_s = (int(p.crossover_taps) // 2) / float(max(1, sr))
    lookahead_s = 0.0
    if master_params is not None and master_params.enabled:
        lookahead_s = float(master_params.lookahead_ms) / 1000.0
    return fir_delay_s + lookahead_s


def extract_preview_block(samples: np.ndarray, sr: int,
                          start_s: float, end_s: float,
                          extra_margin_s: float = 0.0):
    """Extract pre-roll + requested slice + post-roll from the session.

    Returns (block, head_pad_samples, audible_len_samples). Handles
    edge cases near the beginning/end of the file and files shorter
    than the requested slice (pads shrink to what's available).
    """
    n_total = samples.shape[0]
    duration = n_total / sr

    start_s = float(max(0.0, min(duration, start_s)))
    end_s = float(max(start_s + 0.05, min(duration, end_s)))

    audible_n0 = int(round(start_s * sr))
    audible_n1 = int(round(end_s * sr))
    audible_n1 = min(audible_n1, n_total)

    pre_n = int(round((_PREVIEW_PREROLL_S + extra_margin_s) * sr))
    post_n = int(round((_PREVIEW_POSTROLL_S + extra_margin_s) * sr))
    n0 = max(0, audible_n0 - pre_n)
    n1 = min(n_total, audible_n1 + post_n)

    head_pad = audible_n0 - n0
    block = samples[n0:n1, :].copy()
    return block, head_pad, audible_n1 - audible_n0


def trim_processed_preview(y: np.ndarray, head_pad: int,
                           audible_len: int) -> np.ndarray:
    """Trim a processed padded block back to the audible window."""
    y = as_2d(np.asarray(y, dtype=np.float32))
    out = y[head_pad:head_pad + audible_len, :]
    if out.shape[0] < audible_len:
        out = np.pad(out, ((0, audible_len - out.shape[0]), (0, 0)))
    return out


@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)) -> JSONResponse:
    """Accept an audio file once, decode it, and create a preview session.

    The decoded samples stay resident in memory so subsequent /api/preview
    calls can re-render arbitrary slices in milliseconds without re-uploading
    or re-decoding.  Also stores the original file on disk so the existing
    full-file `/api/process` flow can reuse it via `session_id`.
    """
    sess_workdir = tempfile.mkdtemp(prefix="shimmer_upload_")
    orig_name = Path(file.filename or "upload").name
    orig_path = os.path.join(sess_workdir, "input_" + orig_name)
    with open(orig_path, "wb") as f:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)

    loop = asyncio.get_running_loop()
    try:
        x, sr = await loop.run_in_executor(None, load_audio, orig_path)
    except Exception as e:  # noqa: BLE001
        try:
            os.unlink(orig_path)
            os.rmdir(sess_workdir)
        except OSError:
            pass
        raise HTTPException(400, f"Could not decode '{orig_name}': {e}")

    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    x = clamp_samples_for_preview(x, sr)

    loop2 = asyncio.get_running_loop()
    track_analysis = await loop2.run_in_executor(None, analyze_track, x, sr)

    sess = PREVIEW_STORE.create(
        samples=x, sr=sr,
        original_path=orig_path,
        original_name=orig_name,
    )
    sess.track_analysis = track_analysis
    PREVIEW_STORE.sweep()
    return JSONResponse({
        "session_id": sess.id,
        "sample_rate": sr,
        "channels": sess.channels,
        "duration_s": sess.duration_s,
        "name": orig_name,
        "analysis": track_analysis,
    })


def _slice_loudness_db(arr: np.ndarray, sr: int) -> float:
    """Integrated LUFS of a preview slice; RMS-dB fallback for windows
    too short for BS.1770 gating."""
    try:
        v = measure_loudness(arr, sr).get("lufs_i")
        if v is not None and np.isfinite(float(v)):
            return float(v)
    except Exception:  # noqa: BLE001
        pass
    rms = float(np.sqrt(np.mean(np.asarray(arr, dtype=np.float64) ** 2)))
    return float(20.0 * np.log10(rms + 1e-9))


def _render_preview_sync(sess, start_s: float, end_s: float, p: Params,
                         preserve_vol: bool,
                         master_params: Optional[MasterParams] = None) -> Dict[str, Any]:
    """Render processed + diff slices for the requested window.

    The Original player keeps the full file in the browser (so the user
    can scrub through the whole track), so the server only needs to ship
    the two slices that change as the user moves sliders. Slices are
    encoded to in-memory WAVs and returned in the response body — no
    per-render files, no render ids, no GC.

    We pad the window with PREROLL/POSTROLL (+ FIR/lookahead margins) on
    both sides, run the safe pipeline with pad=False and fade_ms=0, then
    trim back to the audible window so loop boundaries are clean and
    stateful stages have warmed up.
    """
    sr = sess.sr

    use_mastering = master_params is not None and master_params.enabled
    margin_s = _preview_margin_s(p, sr, master_params)
    in_slice, head_pad, audible_len = extract_preview_block(
        sess.samples, sr, start_s, end_s, extra_margin_s=margin_s)

    # Disable engine's own pad/fade for slice rendering — the discarded
    # warm-up tail handles edge effects, and looping needs no fades.
    p.pad = False
    p.fade_ms = 0.0

    # Full safe pipeline (tone curve from the session's RAW analysis,
    # band split, M/S clean, width comp, mastering) on the padded block.
    y2, removed_block, _report = clean_and_master(
        in_slice, sr, p,
        master_params=master_params if use_mastering else None,
        raw_analysis=dict(sess.track_analysis or {}),
    )

    proc_audible = trim_processed_preview(y2, head_pad, audible_len)
    orig_audible = in_slice[head_pad:head_pad + audible_len, :]

    # Measure ONLY the audible region — using the full padded slice
    # mixes in 1.5 s of preroll which is often quieter than the loop,
    # making the RMS comparison wrong (preview ends up scaled DOWN
    # because input_rms < proc_audible_rms).
    audible_in_meas = measure(orig_audible)

    if not use_mastering:
        if preserve_vol:
            proc_audible = preserve_volume(
                proc_audible, audible_in_meas["peak_linear"],
                input_rms=audible_in_meas["rms_linear"])
        proc_audible = clip_protect(proc_audible)

    # Removed signal straight from the pipeline (what cleaning stripped
    # from the high band). Shipped UNBOOSTED — the client applies an
    # audition boost via a gain node (capped against the slice's own
    # peak to avoid clipping).
    diff = trim_processed_preview(removed_block, head_pad, audible_len)
    diff = clip_protect(diff)

    return {
        "duration_s": float(audible_len / sr),
        "sample_rate": sr,
        "lufs_original": _slice_loudness_db(orig_audible, sr),
        "lufs_processed": _slice_loudness_db(proc_audible, sr),
        "wav_processed": encode_wav_bytes(proc_audible, sr),
        "wav_removed": encode_wav_bytes(diff, sr),
    }


@app.post("/api/preview")
async def api_preview(payload: Dict[str, Any]) -> Response:
    """Render a small looped slice for live A/B previewing.

    Returns a single binary payload so one round trip carries everything:
        [u32 json_len][json meta][u32 wav_len][processed wav][removed wav]
    Meta includes per-slice loudness so the client can loudness-match A/B
    during preview.
    """
    sid = payload.get("session_id") or ""
    sess = PREVIEW_STORE.get(sid)
    if sess is None:
        raise HTTPException(404, "Unknown session_id")

    try:
        start_s = float(payload.get("start_s", 0.0))
        end_s = float(payload.get("end_s", min(10.0, sess.duration_s)))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"Invalid start_s/end_s: {e}")

    preserve_vol = bool(payload.get("preserve_volume", True))
    mp = master_params_from_json(payload.get("mastering") or {})

    try:
        p = _params_from_json({
            "preset": payload.get("preset") or "generic",
            "preset_strength": payload.get("preset_strength"),
            "overrides": payload.get("overrides") or {},
        })
    except KeyError as e:
        raise HTTPException(400, f"Unknown preset: {e}")

    loop = asyncio.get_running_loop()
    t0 = time.time()
    try:
        result = await loop.run_in_executor(
            None, _render_preview_sync, sess, start_s, end_s, p, preserve_vol, mp)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Preview render failed: {e}")
    elapsed_ms = int((time.time() - t0) * 1000)

    meta = json.dumps({
        "duration_s": result["duration_s"],
        "sample_rate": result["sample_rate"],
        "render_ms": elapsed_ms,
        "start_s": start_s,
        "end_s": end_s,
        "lufs_original": result["lufs_original"],
        "lufs_processed": result["lufs_processed"],
    }).encode("utf-8")
    wav_processed = result["wav_processed"]
    body = b"".join([
        struct.pack("<I", len(meta)), meta,
        struct.pack("<I", len(wav_processed)), wav_processed,
        result["wav_removed"],
    ])
    return Response(content=body, media_type="application/octet-stream")


@app.delete("/api/upload/{session_id}")
async def api_upload_drop(session_id: str) -> JSONResponse:
    PREVIEW_STORE.drop(session_id)
    return JSONResponse({"ok": True})


# ───────────────────────────────────────────────────────────────────────────
# SSE helper
# ───────────────────────────────────────────────────────────────────────────

def _sse_event(data: Dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"
