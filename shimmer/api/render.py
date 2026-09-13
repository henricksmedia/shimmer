"""Render and export: preview, process, progress, metrics, result, cancel
(docs/API.md §4).

Every route here renders with shimmer.core.render() and writes with
shimmer.core.export(), so the preview and the export are the same sound path
(the contract test "the preview is the export on a window").

The transition rule (docs/API.md §0): until the screens are re-wired, these
routes still accept the 1.x fields (preset, preset_strength, overrides,
repair) and map them through core.migrate(), and they still return the
fields the screens read.

Fixes against 1.1.1:

- **Upload once.** /api/process takes the session_id from /api/upload in
  place of the file. An expired session answers 404 and the screen sends the
  file again.
- **Exports read the whole original file,** never the 30-minute preview copy.
- **The preview matches the export,** level included. 1.1.1 matched each
  preview window's level on its own, so a quiet verse previewed louder than
  it would export.
- **Cancel.** POST /api/cancel/{job_id} stops a run between stages.
- **An unfinished result answers 409** with a JSON body, not 202.
- **Download names drop the preset:** {song}_{processed|removed|trimmed}_{id}.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import math
import os
import shutil
import struct
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .. import core
from . import jobs as jobs_mod
from . import sessions

router = APIRouter()

# Set by shimmer/server.py when it includes this router: the version the
# export's provenance note names.
VERSION = "dev"


def configure(version: str) -> None:
    global VERSION
    VERSION = str(version)


# ── Requests to settings (the transition rule) ─────────────────────────

def settings_from_request(params: Optional[Dict[str, Any]], *, output_format: Optional[str] = None,
                          preserve_volume: bool = True, trim_silence: bool = False) -> core.Settings:
    """Settings from a request that may carry the 1.x fields, the new ones,
    or both. New fields win."""
    p = dict(params or {})
    s = core.migrate({
        "preset": p.get("preset"),
        "mastering": p.get("mastering") or {},
        "eq": p.get("eq") or {},
        "output_format": output_format or p.get("output_format") or "wav",
        "trim_silence": trim_silence,
    })
    changes: Dict[str, Any] = {"preserve_volume": bool(preserve_volume)}
    if isinstance(p.get("fixes"), dict):
        changes["fixes"] = p["fixes"]
    if "auto" in p:
        changes["auto"] = bool(p["auto"])
    repair = p.get("repair")
    if isinstance(repair, dict) and repair.get("enabled") is False:
        # 1.x "static repair off": no Fixed tones, found or chosen.
        changes["auto"] = False
        changes["fixes"] = {k: v for k, v in changes.get("fixes", s.fixes).items() if k != "tones"}
    return s.replace(**changes)


def explicit_notches(params: Optional[Dict[str, Any]], sr: int) -> Optional[List[core.Notch]]:
    """The notch list the screen sent (Analyze's lines, some unticked), or
    None to let the engine scan."""
    repair = (params or {}).get("repair")
    if isinstance(repair, dict) and isinstance(repair.get("notches"), list):
        return core.NotchPlan.from_dict(repair, sr).notches
    return None


# ── Small helpers ───────────────────────────────────────────────────────

_FILENAME_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
_MEDIA = {".wav": "audio/wav", ".flac": "audio/flac", ".mp3": "audio/mpeg",
          ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".zip": "application/zip"}


def safe_filename_stem(s: str) -> str:
    """Strip filesystem-hostile characters: spaces and brackets become
    underscores, anything else outside a small allowlist is dropped."""
    out = []
    for c in (s or ""):
        if c in _FILENAME_SAFE:
            out.append(c)
        elif c in " ()[]":
            out.append("_")
    return "".join(out).strip("._-")[:64]


def download_name(job: jobs_mod.Job, kind: str, ext: Optional[str] = None) -> str:
    """{song}_{processed|removed|trimmed}_{id8}.ext; a stems bundle keeps
    {song}_stems_{model}_{id8}.zip (docs/API.md §4)."""
    ext = ext if ext is not None else job.output_ext
    stem = safe_filename_stem(job.source_stem) or "audio"
    if ext == ".zip":
        return f"{stem}_{safe_filename_stem(job.preset_name) or 'stems'}_{job.id[:8]}{ext}"
    suffix = {"diff": "removed", "trimmed": "trimmed"}.get(kind, "processed")
    return f"{stem}_{suffix}_{job.id[:8]}{ext}"


def validated_save_folder(raw: str) -> str:
    """'' when unset; otherwise an existing (or just created) folder, or a
    400 that names the problem before a long run starts."""
    folder = (raw or "").strip()
    if not folder:
        return ""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        raise HTTPException(400, f"Save folder not usable: {folder} ({e.strerror or e})")
    if not os.path.isdir(folder):
        raise HTTPException(400, f"Save folder is not a folder: {folder}")
    return os.path.abspath(folder)


def _finite(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _json_safe(v: Any) -> Any:
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (np.floating,)):
        return _json_safe(float(v))
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, dict):
        return {k: _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    return v


def _measure(x: np.ndarray) -> Dict[str, float]:
    a = np.asarray(x, dtype=np.float64)
    peak = float(np.max(np.abs(a))) if a.size else 0.0
    rms = float(np.sqrt(np.mean(a ** 2))) if a.size else 0.0
    return {"peak_dbfs": 20.0 * math.log10(peak + 1e-12), "rms_dbfs": 20.0 * math.log10(rms + 1e-12),
            "peak_linear": peak, "rms_linear": rms}


def _slice_loudness_db(x: np.ndarray, sr: int) -> float:
    """Integrated LUFS of a preview slice; RMS dB for windows too short for
    BS.1770 gating."""
    v = core.meters.loudness(x, sr)
    if math.isfinite(v):
        return float(v)
    return float(20.0 * math.log10(float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2))) + 1e-9))


def _pass_label(source_path: str) -> str:
    """One more than the Shimmer notes already in the source's comment."""
    comment = core.tags.read_tags(source_path).get("comment", "") if source_path else ""
    prior = sum(1 for ln in comment.splitlines() if ln.strip().startswith("Shimmer"))
    return f"pass {prior + 1}"


def _eq_moves(s: core.Settings, sr: int) -> List[str]:
    """The EQ as applied, for the note: `5.6kHz +3.0dB Q0.8`."""
    if not s.eq_enabled:
        return []
    out = []
    for b in s.eq_bands:
        if not b.enabled or b.freq_hz >= 0.49 * sr:
            continue
        if b.type in ("bell", "low_shelf", "high_shelf") and abs(b.gain_db) < 0.05:
            continue
        f = f"{b.freq_hz / 1000:g}kHz" if b.freq_hz >= 1000 else f"{b.freq_hz:g}Hz"
        out.append(f"{f} {b.type}" if b.type not in ("bell", "low_shelf", "high_shelf")
                   else f"{f} {b.gain_db:+.1f}dB Q{b.q:g}")
    return out


def _note(pass_label: str, rendered: core.Rendered, eq_moves: List[str]) -> str:
    """One provenance line for the comment tag, e.g.
    `Shimmer 2.0.0: pass 1, Fixed tones 2 notches, mastered -9 LUFS / -1 dBTP`."""
    parts = [pass_label]
    tones = rendered.report.get("fixes", {}).get("tones")
    if isinstance(tones, dict) and tones.get("enabled"):
        n = int(tones.get("notches") or 0)
        parts.append(f"Fixed tones {n} notch{'es' if n != 1 else ''}")
    else:
        parts.append("no fixes")
    if eq_moves:
        parts.append("EQ " + "; ".join(eq_moves))
    m = rendered.report.get("mastering", {})
    if m.get("enabled"):
        parts.append(f"mastered {m['target_lufs']:g} LUFS / {m['ceiling_dbtp']:g} dBTP")
    else:
        parts.append("cleaning only")
    return f"Shimmer {VERSION}: " + ", ".join(parts)


def _loudness_block(x: np.ndarray, sr: int) -> Dict[str, Optional[float]]:
    return {"lufs_i": _finite(core.meters.loudness(x, sr)),
            "true_peak_dbtp": _finite(core.meters.true_peak_db(x, sr)),
            "lra": _finite(core.loudness_range(x, sr))}


def _build_tags(source_path: str, tags_req: Optional[Dict[str, Any]],
                note: str) -> Optional[Dict[str, str]]:
    """The tags to write, or None when the request turned tags off. The
    title falls back to the file name, an upload's "input_" prefix dropped."""
    if isinstance(tags_req, dict) and tags_req.get("enabled") is False:
        return None
    stem = Path(source_path).stem
    stem = stem[len("input_"):] if stem.startswith("input_") else stem
    req = dict(tags_req or {})
    return core.tags.build_tags(core.tags.read_tags(source_path), req, title_hint=stem,
                                note=note if req.get("notes", True) else "",
                                software=f"Shimmer {VERSION}")


# ── The export job ──────────────────────────────────────────────────────

def _run_export(job: jobs_mod.Job, source_path: str, s: core.Settings,
                notches: Optional[List[core.Notch]], trim_in_s: float,
                trim_out_s: Optional[float], tags_req: Optional[Dict[str, Any]],
                save_folder: str) -> None:
    """The worker: runs in a thread. Every stage checks for cancel."""
    prog = job.run
    prog.stage("load", "Reading the file")
    x, sr = core.load_audio(source_path)
    if float(trim_in_s or 0.0) > 0 or trim_out_s is not None:
        prog.stage("edit", "Trimming the edges",
                   f"in at {float(trim_in_s or 0.0):.2f} s"
                   + (f" · out at {float(trim_out_s):.2f} s" if trim_out_s is not None else ""))
    x, edge_trim = core.apply_trim(x, sr, trim_in_s, trim_out_s)
    src = core.Source.from_array(x, sr, path=source_path)

    rendered = core.render(src, s, progress=prog, with_removed=True, notches=notches)
    y, out_sr = rendered.audio, rendered.sr
    x_at = src.at_rate(out_sr)
    fmt = core.catalog.output_format(s.format)

    note = _note(_pass_label(source_path), rendered, _eq_moves(s, out_sr))
    tags = _build_tags(source_path, tags_req, note)
    tags_on = tags is not None

    prog.stage("export", "Writing the file",
               f"{fmt.label}" + (" · tags" if tags_on else "")
               + (" · silence trim" if s.trim_silence else "")
               + (" · saving to your folder" if save_folder else ""))
    processed_path = os.path.join(job.workdir, f"processed{fmt.ext}")
    diff_path = os.path.join(job.workdir, f"removed{fmt.ext}")
    exp = core.export(rendered, processed_path, source_path=source_path, tags=tags)
    # The removed signal is written as it is: any audition boost is the
    # screen's monitoring gain, never baked into a file.
    core.export(core.Rendered(rendered.removed, out_sr, {}, s, source_path), diff_path,
                source_path=source_path)

    trim_report: Dict[str, Any] = {"enabled": False}
    y_export, export_report = y, exp
    if s.trim_silence:
        y_trim, head, tail = core.trim_silence(y, out_sr)
        trimmed_path = os.path.join(job.workdir, f"trimmed{fmt.ext}")
        export_report = core.export(core.Rendered(y_trim, out_sr, {}, s, source_path),
                                    trimmed_path, source_path=source_path, tags=tags)
        job.trimmed_path = trimmed_path
        y_export = y_trim
        trim_report = {"enabled": True, "cut_head_s": round(head, 3), "cut_tail_s": round(tail, 3)}

    saved: Dict[str, Any] = {"enabled": False}
    if save_folder:
        kind = "trimmed" if s.trim_silence else "processed"
        src_path = job.trimmed_path if s.trim_silence else processed_path
        dest = os.path.join(save_folder, download_name(job, kind))
        try:
            os.makedirs(save_folder, exist_ok=True)
            shutil.copyfile(src_path, dest)
            job.saved_path = dest
            saved = {"enabled": True, "path": dest, "folder": save_folder, "name": os.path.basename(dest)}
        except OSError as e:
            saved = {"enabled": True, "folder": save_folder, "error": str(e.strerror or e)}

    prog.stage("report", "Measuring the result")
    before = _loudness_block(x_at, out_sr)
    after = {"lufs_i": _finite(export_report["lufs"]),
             "true_peak_dbtp": _finite(export_report["true_peak_dbtp"]),
             "lra": _finite(core.loudness_range(y_export, out_sr))}
    m = rendered.report.get("mastering", {})
    mastering: Dict[str, Any] = {"enabled": bool(m.get("enabled"))}
    if m.get("enabled"):
        mastering.update({
            "target_lufs": m["target_lufs"], "ceiling_dbtp": m["ceiling_dbtp"],
            "gain_db": m["gain_db"], "intensity": s.intensity, "tilt": s.tilt,
            "eq_bands_db": m.get("tone_curve_db", []),
            "before": before, "after": after,
            "limiter": {"max_gain_reduction_db": m["limiter_gain_reduction_db"]},
            "limiter_gain_reduction": m["limiter_gain_reduction_db"],
            "estimated_true_peak": after["true_peak_dbtp"],
            "ab_match_gain_db": (before["lufs_i"] - after["lufs_i"])
            if before["lufs_i"] is not None and after["lufs_i"] is not None else 0.0,
            "lufs_error": (after["lufs_i"] - m["target_lufs"]) if after["lufs_i"] is not None else None,
        })
    corr_in, corr_out = core.stereo_correlation(x_at), core.stereo_correlation(y_export)
    loudness = {"input_lufs_i": before["lufs_i"], "output_lufs_i": after["lufs_i"],
                "input_plr_db": core.plr_db(x_at, out_sr, before["lufs_i"]),
                "output_plr_db": core.plr_db(y_export, out_sr, after["lufs_i"]),
                "input_correlation": corr_in, "output_correlation": corr_out}
    tag_report = dict(export_report.get("tags") or {})
    if tags is not None:
        tag_report["tags"] = {k: v for k, v in tags.items() if k != "software"}
    export = {
        "format": fmt.ext.lstrip("."), "format_key": fmt.key,
        "subtype": fmt.subtype, "bit_depth": fmt.bits, "dither": fmt.bits == 16,
        "sample_rate": int(out_sr), "bitrate": fmt.bitrate,
        "lossy_trim_db": export_report.get("lossy_trim_db", 0.0),
        "clipped_samples": export_report.get("clipped_samples", 0),
        "tags": tag_report, "saved": saved,
        "name": download_name(job, "trimmed" if s.trim_silence else "processed"),
        "size_bytes": os.path.getsize(job.trimmed_path if s.trim_silence else processed_path),
    }
    release = None
    if m.get("enabled"):
        release = core.release_check(
            y_export, out_sr, x_in=x_at, mastering=mastering, export=export,
            correlation=corr_out, duration_s=float(y_export.shape[0] / out_sr),
            tags=tag_report.get("tags"), tags_written=bool(tag_report.get("written")))
    tones = rendered.report.get("fixes", {}).get("tones")
    eq_bands = [b for b in s.eq_bands if b.enabled] if s.eq_enabled else []

    job.processed_path = processed_path
    job.diff_path = diff_path
    job.metrics = _json_safe({
        "spectra": core.spectra_report(x_at, y, rendered.removed, out_sr),
        "export": export,
        "release": release,
        "sample_rate": out_sr,
        "channels": int(y.shape[1]),
        "duration_s": float(y.shape[0] / out_sr),
        "input": _measure(x_at),
        "output": _measure(y),
        "pipeline": {"tone_curve_db": m.get("tone_curve_db", []), "side_width_compensation": {}},
        "mastering": mastering,
        "loudness": loudness,
        "trim": trim_report,
        "edge_trim": edge_trim,
        "repair": tones if isinstance(tones, dict) else {"enabled": False, "notches": 0},
        "declick": {"enabled": False},
        "cutoff_hz": float(core.estimate_cutoff_hz(x_at, out_sr).get("cutoff_hz") or 0.0),
        "eq": {"enabled": bool(eq_bands), "bands": len(eq_bands)},
        "fixes": rendered.report.get("fixes", {}),
    })


async def _run_export_async(job: jobs_mod.Job, *args) -> None:
    loop = asyncio.get_running_loop()
    jobs_mod.pusher(job, loop)
    job.status = "running"
    try:
        await loop.run_in_executor(None, _run_export, job, *args)
    except Exception as e:  # noqa: BLE001  (Cancelled included)
        await jobs_mod.finish(job, e)
        return
    await jobs_mod.finish(job)


# ── Batch: one file at a time, the Master tab's way ─────────────────────

def _findings_json(src: core.Source, s: core.Settings) -> List[Dict[str, Any]]:
    return [dataclasses.asdict(f) for f in core.findings(src, s.loudness_target)]


def measure_file(source_path: str, s: core.Settings) -> Dict[str, Any]:
    """Album mode's first pass for one file: its level just before
    mastering's gain, and its findings. Nothing is written."""
    x, sr = core.load_audio(source_path)
    src = core.Source.from_array(x, sr, path=source_path)
    levels = core.premaster_levels(src, s)
    return _json_safe({
        "duration_s": float(x.shape[0] / sr),
        "input": _measure(x),
        "lufs_clean": _finite(levels["lufs_i"]),
        "true_peak_clean": _finite(levels["true_peak_dbtp"]),
        "findings": _findings_json(src, s),
    })


def export_file(source_path: str, s: core.Settings, dst: str, *,
                tags_req: Optional[Dict[str, Any]] = None,
                gain_db: Optional[float] = None,
                expected_lufs: Optional[float] = None,
                with_findings: bool = True) -> Dict[str, Any]:
    """One song rendered and written to `dst`, for Batch: the same render,
    tags, silence trim and release check as the Master tab's export.
    `gain_db` and `expected_lufs` are album mode's one gain and this song's
    level under it. Returns what the batch log shows."""
    x, sr = core.load_audio(source_path)
    src = core.Source.from_array(x, sr, path=source_path)
    rendered = core.render(src, s, gain_db=gain_db)
    y, out_sr = rendered.audio, rendered.sr
    x_at = src.at_rate(out_sr)
    fmt = core.catalog.output_format(s.format)
    tags = _build_tags(source_path, tags_req,
                       _note(_pass_label(source_path), rendered, _eq_moves(s, out_sr)))
    trim_report: Dict[str, Any] = {"enabled": False}
    if s.trim_silence:
        y, head, tail = core.trim_silence(y, out_sr)
        trim_report = {"enabled": True, "cut_head_s": round(head, 3), "cut_tail_s": round(tail, 3)}
    exp = core.export(core.Rendered(y, out_sr, rendered.report, s, source_path), dst,
                      source_path=source_path, tags=tags)
    written = bool((exp.get("tags") or {}).get("written"))
    m = rendered.report.get("mastering", {})
    lufs_out, tp_out = _finite(exp["lufs"]), _finite(exp["true_peak_dbtp"])
    release = None
    if m.get("enabled"):
        release = core.release_check(
            y, out_sr, x_in=x_at,
            mastering={"enabled": True, "target_lufs": m["target_lufs"],
                       "ceiling_dbtp": m["ceiling_dbtp"],
                       "after": {"lufs_i": lufs_out, "true_peak_dbtp": tp_out}},
            export={"format": fmt.ext.lstrip("."), "bit_depth": fmt.bits},
            correlation=core.stereo_correlation(y), duration_s=float(y.shape[0] / out_sr),
            tags={k: v for k, v in tags.items() if k != "software"} if tags else None,
            tags_written=written, expected_lufs=expected_lufs)
    return _json_safe({
        "duration_s": float(y.shape[0] / out_sr),
        "input": _measure(x_at),
        "output": _measure(y),
        "lufs_out": lufs_out,
        "true_peak_out": tp_out,
        "limiter_gr_db": m.get("limiter_gain_reduction_db"),
        "gain_db": m.get("gain_db"),
        "trim": trim_report,
        "tags_written": written,
        "release": release,
        "fixes": rendered.report.get("fixes", {}),
        "findings": _findings_json(src, s) if with_findings else None,
    })


# ── Routes ──────────────────────────────────────────────────────────────

@router.post("/api/process")
async def process(background: BackgroundTasks,
                  file: Optional[UploadFile] = File(None),
                  session_id: str = Form(""),
                  params: str = Form("{}"),
                  preserve_volume: bool = Form(True),
                  output_format: str = Form("wav"),
                  trim_silence: bool = Form(False),
                  trim_in_s: float = Form(0.0),
                  trim_out_s: Optional[float] = Form(None),
                  save_folder: str = Form("")) -> JSONResponse:
    try:
        p = json.loads(params or "{}")
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid params JSON: {e}")
    try:
        fmt = core.catalog.output_format(output_format)
    except KeyError:
        raise HTTPException(400, f"Unsupported output format: {output_format}")
    folder = validated_save_folder(save_folder)
    s = settings_from_request(p, output_format=fmt.key, preserve_volume=preserve_volume,
                              trim_silence=trim_silence)

    sess = sessions.SESSIONS.get(session_id) if session_id else None
    if session_id and sess is None and file is None:
        raise HTTPException(404, "Session expired; send the file again")

    job = jobs_mod.JOB_STORE.create(output_ext=fmt.ext)
    if sess is not None:
        name, source_path = sess.original_name, sess.original_path
    else:
        if file is None:
            raise HTTPException(400, "Send a file or a session_id")
        name = Path(file.filename or "upload").name
        source_path = os.path.join(job.workdir, "input_" + name)
        with open(source_path, "wb") as f:
            while True:
                chunk = await file.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
    # Exports never chain suffixes: a pass-2 file is named from the song.
    job.source_stem = core.tags.strip_shimmer_suffix(Path(name).stem) or "audio"
    job.original_path = source_path
    asyncio.create_task(_run_export_async(
        job, source_path, s, explicit_notches(p, 48000 if sess is None else sess.sr),
        trim_in_s, trim_out_s, p.get("tags") if isinstance(p.get("tags"), dict) else None,
        folder))
    jobs_mod.JOB_STORE.sweep()
    return JSONResponse({"job_id": job.id})


@router.get("/api/progress/{job_id}")
async def progress(job_id: str, request: Request) -> StreamingResponse:
    job = jobs_mod.JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")

    async def stream():
        # The current status first, so a late listener has context.
        yield f"data: {json.dumps({'fraction': job.progress, 'status': job.status})}\n\n"
        async for msg in jobs_mod.events(job, request.is_disconnected):
            yield ": keepalive\n\n" if msg is None else f"data: {json.dumps(_json_safe(msg))}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/api/cancel/{job_id}")
async def cancel(job_id: str) -> JSONResponse:
    job = jobs_mod.JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    if job.cancel():
        return JSONResponse({"cancelled": True})
    reason = ("it has already finished" if job.status in ("done", "error", "cancelled")
              else "this kind of job cannot be stopped early yet")
    return JSONResponse({"cancelled": False, "reason": reason})


@router.get("/api/metrics/{job_id}")
async def metrics(job_id: str) -> JSONResponse:
    job = jobs_mod.JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    if job.status == "error":
        raise HTTPException(500, job.error or "Job failed")
    if job.status == "cancelled":
        return JSONResponse({"status": "cancelled"}, status_code=409)
    if job.status != "done":
        return JSONResponse({"status": job.status}, status_code=202)
    return JSONResponse({"status": "done", "metrics": job.metrics})


@router.get("/api/result/{job_id}")
async def result(job_id: str, kind: str = "processed"):
    job = jobs_mod.JOB_STORE.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    if job.status == "error":
        raise HTTPException(500, job.error or "Job failed")
    if job.status != "done":
        return JSONResponse({"status": job.status, "detail": "Job not finished"}, status_code=409)
    path = {"processed": job.processed_path, "diff": job.diff_path,
            "trimmed": job.trimmed_path}.get(kind)
    if not path or not os.path.isfile(path):
        raise HTTPException(404, f"No {kind} file for this job")
    ext = os.path.splitext(path)[1].lower()
    return FileResponse(path, media_type=_MEDIA.get(ext, "application/octet-stream"),
                        filename=download_name(job, kind, ext))


@router.post("/api/preview")
async def preview(payload: Dict[str, Any]) -> Response:
    """A looped window for live A/B, rendered by the same path as the export.

    One binary body per call, little-endian:
        [u32 json_len][json meta][u32 wav_len][processed wav][removed wav]
    """
    sess = sessions.SESSIONS.get(payload.get("session_id") or "")
    if sess is None:
        raise HTTPException(404, "Unknown session_id")
    try:
        start_s = float(payload.get("start_s", 0.0))
        end_s = float(payload.get("end_s", min(10.0, sess.duration_s)))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"Invalid start_s/end_s: {e}")
    s = settings_from_request(payload, output_format=payload.get("output_format") or "wav",
                              preserve_volume=bool(payload.get("preserve_volume", True)))
    notches = explicit_notches(payload, sess.sr)
    if notches is None:
        notches = core.plan_from_lines(sess.repair_lines, sess.sr).notches

    def work() -> Tuple[core.Rendered, np.ndarray]:
        r = core.render(sess.source, s, window=(start_s, end_s), with_removed=True, notches=notches)
        a, b = round(start_s * r.sr), round(end_s * r.sr)
        return r, sess.source.at_rate(r.sr)[a:b]

    loop = asyncio.get_running_loop()
    t0 = time.time()
    try:
        rendered, original = await loop.run_in_executor(None, work)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Preview render failed: {e}")
    meta = json.dumps({
        "duration_s": rendered.audio.shape[0] / rendered.sr,
        "sample_rate": rendered.sr,
        "render_ms": int((time.time() - t0) * 1000),
        "start_s": start_s,
        "end_s": end_s,
        "lufs_original": _slice_loudness_db(original, rendered.sr),
        "lufs_processed": _slice_loudness_db(rendered.audio, rendered.sr),
    }).encode("utf-8")
    processed = core.wav_bytes(rendered.audio, rendered.sr)
    removed = core.wav_bytes(np.clip(rendered.removed, -1.0, 1.0), rendered.sr)
    body = b"".join([struct.pack("<I", len(meta)), meta,
                     struct.pack("<I", len(processed)), processed, removed])
    return Response(content=body, media_type="application/octet-stream")
