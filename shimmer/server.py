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

from . import _winfix  # noqa: F401  # must precede scipy/numpy import on Windows

import asyncio
import glob
import json
import math
import os
import shutil
import struct
import zipfile
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from fastapi import (
    FastAPI, UploadFile, File, Form, HTTPException, Request,
    BackgroundTasks,
)
from fastapi.responses import (
    FileResponse, JSONResponse, StreamingResponse, HTMLResponse, Response,
)
from fastapi.staticfiles import StaticFiles

from .audio_io import (
    load_audio, save_audio, measure, preserve_volume, clip_protect,
    process_file, encode_wav_bytes, resolve_output_format, resample_to,
)
from .chain import folder_label
from .engine import process, apply_post_filters
from .release import (
    add_check, count_clipped, release_check, summary as release_summary,
    tags_check,
)
from .dsp import as_2d, trim_silence as dsp_trim_silence
from .edges import apply_trim, detect_edge_artifacts
from .repair import NotchPlan, estimate_cutoff_hz, plan_from_lines
from .detect import scan_fixed_lines
from .eq import EqParams, eq_params_from_json
from .jobs import JOB_STORE, Job
from .params import Params, apply_preset_strength, preset_overrides, MasterParams
from .mastering import (
    master, master_params_from_json, analyze_track, measure_loudness,
    get_export_ceiling_dbtp,
)
from .pipeline import clean_and_master
from .presets import (
    PRESETS, PRESET_NAMES, VISIBLE_PRESETS,
    get_preset, describe_preset, label_for, is_visible,
)
from .report import plr_db, spectra_report, stereo_correlation
from .autoeq import family_list, moves_to_eq_payload, normalize_family, plan_tone
from .mastering import compute_tone_curve, resolve_eq_strength
from .tags import (
    build_tags, read_tags, shimmer_note, strip_shimmer_suffix, title_from_stem,
    write_tags,
)
from . import __version__ as SHIMMER_VERSION
from .preview_store import PREVIEW_STORE, clamp_samples_for_preview
from .settings_store import load_settings, save_settings
from . import stems as stems_mod
from .stem_effects import (
    apply_fx_only, apply_gain_mute, fx_signature,
    remix_settings_from_json, render_remix, render_stems,
)
from .projects_store import list_projects, load_project, save_project


HERE = Path(__file__).resolve().parent.parent   # project root; package is one level down
STATIC_DIR = HERE / "static"

class _NoCacheStaticFiles(StaticFiles):
    """Static files that always revalidate so UI updates take effect
    immediately after a server upgrade (files are tiny; cost is nil)."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app = FastAPI(title="Shimmer by The Treq")
# html=True so a folder URL serves its index.html. Without it
# /static/marketing/ and /static/references/ both returned FastAPI's
# {"detail":"Not Found"} and only worked with index.html spelled out — which
# is not what anything links to, and not what the CHANGELOG said shipped.
app.mount("/static", _NoCacheStaticFiles(directory=str(STATIC_DIR), html=True),
          name="static")

# Routes of the new engine (shimmer.api), included as each area moves over
# (docs/REBUILD-TRACKER.md Step 4).
from .api import rules as _api_rules  # noqa: E402

app.include_router(_api_rules.router)


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
    from a worker thread. `_cb.stage(key, label, detail)` pushes a chain
    stage event (same queue), so the UI can show where the audio is."""
    def _cb(fraction: float) -> None:
        job.progress = float(fraction)
        asyncio.run_coroutine_threadsafe(
            job.queue.put({"fraction": float(fraction)}), loop)

    def _stage(key: str, label: str, detail: str = "") -> None:
        asyncio.run_coroutine_threadsafe(
            job.queue.put({"fraction": float(job.progress), "stage": key,
                           "status": label, "detail": detail}), loop)
    _cb.stage = _stage  # type: ignore[attr-defined]
    return _cb


def _master_params_from_request(data: Dict[str, Any]) -> MasterParams:
    return master_params_from_json(data.get("mastering") or {})


def _eq_params_from_request(data: Dict[str, Any]) -> EqParams:
    return eq_params_from_json(data.get("eq") or {})


def _tone_plan_for(x: np.ndarray, sr: int, analysis: Dict[str, Any],
                   preset_name: str, strength: float, family: str,
                   mp: Optional[MasterParams],
                   repair_dict: Optional[Dict[str, Any]] = None,
                   overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The Tone plan (autoeq.plan_tone) judged the way the chain will run:
    the loudest excerpt is cleaned with the chosen preset first, and the
    mastering tone curve (when mastering is on) is subtracted, so the
    plan never corrects what cleaning or mastering already handles."""
    import copy
    try:
        p = get_preset(preset_name or "generic")
    except KeyError:
        p = get_preset("generic")
    if abs(float(strength) - 1.0) > 1e-6:
        apply_preset_strength(p, float(strength))
    for key, value in (overrides or {}).items():
        if hasattr(p, key) and isinstance(value, (int, float)):
            setattr(p, key, float(value))
    cutoff = analysis.get("cutoff_hz")
    p.cutoff_hz = float(cutoff or 0.0)
    repair = None
    notches = None
    if isinstance(repair_dict, dict) and isinstance(repair_dict.get("notches"), list):
        repair = NotchPlan.from_dict(repair_dict, sr)
        notches = [{"hz": n.hz} for n in repair.notches]
    tone_curve = None
    if mp is not None and mp.enabled:
        tone_curve = compute_tone_curve(
            x, sr, strength=resolve_eq_strength(mp),
            raw_spectrum=analysis.get("spectrum"), tilt=mp.tilt,
            cutoff_hz=cutoff)
    p_clean = copy.deepcopy(p)
    p_clean.pad = False
    p_clean.fade_ms = 0.0

    def cleaner(ex: np.ndarray) -> np.ndarray:
        y, _removed, _rep = clean_and_master(
            ex, sr, copy.deepcopy(p_clean), master_params=None,
            raw_analysis=analysis, repair=repair)
        return y

    plan = plan_tone(x, sr, family=normalize_family(family),
                     cutoff_hz=cutoff, tone_curve_db=tone_curve,
                     notches=notches, cleaner=cleaner)
    plan["preset"] = preset_name
    plan["preset_label"] = label_for(preset_name) if preset_name in PRESET_NAMES else preset_name
    plan["preset_strength"] = float(strength)
    plan["mastering_on"] = bool(mp is not None and mp.enabled)
    return plan


def _download_name(job: Job, kind: str, ext: Optional[str] = None) -> str:
    """The filename a download of `kind` gets, and the name a copy saved
    into the user's folder gets, so the two never disagree:
    `{stem}_{preset}_{processed|removed|trimmed}_{jobid8}{ext}`. The
    short job id keeps successive runs of one song apart."""
    ext = ext if ext is not None else job.output_ext
    safe_stem = _safe_filename_stem(job.source_stem) or "audio"
    safe_preset = _safe_filename_stem(job.preset_name) or "preset"
    short_id = job.id[:8]
    if kind == "original":
        return f"{safe_stem}_original{ext}"
    if ext == ".zip":
        # A stems bundle: {track}_stems_{model|mixed}_{id}.zip
        return f"{safe_stem}_{safe_preset}_{short_id}{ext}"
    suffix = {"diff": "removed", "trimmed": "trimmed"}.get(kind, "processed")
    return f"{safe_stem}_{safe_preset}_{suffix}_{short_id}{ext}"


def _file_size(path: str) -> Optional[int]:
    try:
        return int(os.path.getsize(path)) if path and os.path.isfile(path) else None
    except OSError:
        return None


def _reveal_in_file_manager(path: str) -> bool:
    """Show `path` in the OS file manager, selected where the platform
    can: Explorer on Windows, Finder on macOS, the folder elsewhere."""
    import subprocess
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])
        return True
    except OSError:
        return False


# Swapped out by tests; the route reads it at call time.
_REVEAL_LAUNCHER = _reveal_in_file_manager


def _validated_save_folder(raw: str) -> str:
    """Normalise the optional "Save to folder" target: '' when unset,
    otherwise an existing (or just created) directory, or a 400 that
    names the problem before a long run starts."""
    folder = (raw or "").strip()
    if not folder:
        return ""
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        raise HTTPException(
            400, f"Save folder not usable: {folder} ({e.strerror or e})")
    if not os.path.isdir(folder):
        raise HTTPException(400, f"Save folder is not a folder: {folder}")
    return os.path.abspath(folder)


def _tag_export(path: str, source_path: str, req: Optional[Dict[str, Any]],
                note: str) -> Dict[str, Any]:
    """Write tags onto an export: the source's own tags, the user's
    defaults for the blanks, and Shimmer's note in the comment."""
    req = dict(req or {})
    if req.get("enabled", True) is False:
        return {"written": False, "reason": "off"}
    source = read_tags(source_path) if source_path and os.path.exists(source_path) else {}
    stem = Path(source_path).stem if source_path else ""
    if stem.startswith("input_"):
        stem = stem[len("input_"):]
    tags = build_tags(source, req, title_hint=stem,
                      note=note if req.get("notes", True) else "",
                      software=f"Shimmer {SHIMMER_VERSION}")
    rep = write_tags(path, tags)
    rep["tags"] = {k: v for k, v in tags.items() if k != "software"}
    rep["source_had_tags"] = bool(source)
    return rep


def _eq_moves(eq_params: Optional[EqParams], sr: int) -> List[str]:
    """The EQ as applied, for the export note: `5.6kHz +3.0dB Q0.8`.
    A band count alone cannot tell a brightening plan from a darkening one."""
    if eq_params is None or not eq_params.is_active(sr):
        return []
    out: List[str] = []
    for b in eq_params.active_bands(sr):
        f = f"{b.freq_hz / 1000:g}kHz" if b.freq_hz >= 1000 else f"{b.freq_hz:g}Hz"
        out.append(f"{f} {b.gain_db:+.1f}dB Q{b.q:g}")
    return out


def _tone_label(mp: Optional[MasterParams]) -> str:
    """Mastering tone setting, e.g. `med/neutral` — the pair that decides
    how hard the pre-clean tone curve pulls and in which direction."""
    if mp is None or not mp.enabled:
        return ""
    return f"{mp.intensity}/{mp.tilt}"


def _pass_label(source_path: str) -> str:
    """Pass number for the note: one more than the Shimmer notes already in
    the source's comment (a pass-1 export carries one)."""
    try:
        comment = read_tags(source_path).get("comment", "") if source_path else ""
    except Exception:  # noqa: BLE001
        comment = ""
    prior = sum(1 for ln in comment.splitlines() if ln.strip().startswith("Shimmer"))
    return f"pass {prior + 1}"


def _repair_plan_for(x: Optional[np.ndarray], sr: int,
                     req: Optional[Dict[str, Any]],
                     lines: Optional[list] = None) -> Optional[NotchPlan]:
    """Resolve the static-repair plan for a request.

    `req` is the client's `repair` block: `{"enabled": false}` turns the
    stage off; an explicit `notches` list (from Analyze, possibly with
    lines unticked) is validated and used as-is; otherwise the file is
    scanned (or the session's cached scan is used)."""
    req = req or {}
    if req.get("enabled") is False:
        return None
    if isinstance(req.get("notches"), list):
        return NotchPlan.from_dict(req, sr)
    if lines is None:
        if x is None:
            return None
        lines = scan_fixed_lines(x, sr)
    return plan_from_lines(lines, sr)


def _run_job_sync(job: Job, upload_path: str, params: Params,
                  preserve_vol: bool, progress_cb,
                  master_params: Optional[MasterParams] = None,
                  mastering_analysis: Optional[Dict[str, Any]] = None,
                  trim_silence: bool = False,
                  eq_params: Optional[EqParams] = None,
                  trim_in_s: float = 0.0,
                  trim_out_s: Optional[float] = None,
                  repair_req: Optional[Dict[str, Any]] = None,
                  export_meta: Optional[Dict[str, Any]] = None) -> None:
    """CPU-bound worker: runs in a thread executor."""
    x, sr = load_audio(upload_path)
    export_meta = export_meta or {}
    # The export spec (format key, subtype, delivery rate). A release
    # copy is resampled here, before anything runs, so the chain and the
    # true-peak limiter work at the delivery rate.
    out_spec = export_meta.get("output") or resolve_output_format(job.output_ext)
    x, sr = resample_to(x, sr, out_spec.get("sr"))
    out_dither = bool(out_spec.get("dither"))
    stage_cb = getattr(progress_cb, "stage", None)

    def _stage(key: str, label: str, detail: str = "") -> None:
        if stage_cb:
            stage_cb(key, label, detail)

    # Explicit in/out points are applied to the SOURCE, before anything
    # else runs. A head click is a transient the limiter would otherwise
    # duck the whole intro for, and cutting first keeps every downstream
    # measurement (loudness, tone curve) describing the real music.
    if float(trim_in_s or 0.0) > 0 or trim_out_s is not None:
        _stage("edit", "Trimming the edges",
               f"in at {float(trim_in_s or 0.0):.2f} s" + (f" · out at {float(trim_out_s):.2f} s" if trim_out_s is not None else ""))
    x, edge_trim_report = apply_trim(x, sr, trim_in_s, trim_out_s)

    meas_in = measure(x)
    use_mastering = master_params is not None and master_params.enabled

    # RAW-input analysis: the tone curve must come from the unprocessed
    # signal, never from cleaned audio (post-clean tone match would
    # boost the harshness the cleaner removed).
    if use_mastering and mastering_analysis is None:
        mastering_analysis = analyze_track(x, sr)

    # Deterministic repairs come from the whole file: the fixed-line plan
    # and the bandwidth cutoff (shelves / tone curve never boost above it).
    repair_plan = _repair_plan_for(x, sr, repair_req)
    cut = (mastering_analysis or {}).get("cutoff_hz") if mastering_analysis else None
    if cut is None:
        cut = estimate_cutoff_hz(x, sr).get("cutoff_hz")
    params.cutoff_hz = float(cut or 0.0)

    y2, removed, pipe_report = clean_and_master(
        x, sr, params,
        master_params=master_params if use_mastering else None,
        progress_callback=progress_cb,
        raw_analysis=mastering_analysis,
        eq_params=eq_params,
        repair=repair_plan,
        stage_callback=stage_cb,
    )
    mastering_report: Dict[str, Any] = pipe_report.get(
        "mastering", {"enabled": False})

    if not use_mastering and preserve_vol:
        _stage("level", "Preserve volume", "matching the original level")
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
    save_folder = str(export_meta.get("save_folder") or "")
    _stage("export", "Writing the file",
           f"{job.output_ext.lstrip('.').upper()} · tags"
           + (" · silence trim" if trim_silence else "")
           + (f" · saving to {folder_label(save_folder)}" if save_folder else ""))
    save_audio(processed_path, y2, sr, subtype=out_spec["subtype"], dither=out_dither)
    save_audio(diff_path, diff, sr, subtype=out_spec["subtype"], dither=out_dither)

    # Tags: the source's own, the user's defaults, and one note per pass.
    eq_bands = len(eq_params.active_bands(sr)) if eq_params is not None and eq_params.is_active(sr) else 0
    preset_strength = float(export_meta.get("preset_strength", 1.0))
    note = shimmer_note(
        f"Shimmer {SHIMMER_VERSION}", _pass_label(upload_path),
        label_for(job.preset_name) if job.preset_name in PRESET_NAMES else job.preset_name,
        preset_strength, use_mastering,
        float(master_params.target_lufs) if use_mastering else None,
        float(master_params.ceiling_dbtp) if use_mastering else None,
        eq_bands=eq_bands,
        overrides=preset_overrides(params, job.preset_name, preset_strength),
        eq_moves=_eq_moves(eq_params, sr),
        tone=_tone_label(master_params if use_mastering else None))
    tags_report = _tag_export(processed_path, upload_path, export_meta.get("tags"), note)

    # Silence trim is an export-only variant: the playback files above stay
    # full length so the synced A/B/C player keeps a shared clock.
    trim_report: Dict[str, Any] = {"enabled": False}
    y_export = y2
    if trim_silence:
        y_trim, cut_head, cut_tail = dsp_trim_silence(y2, sr)
        y_export = y_trim
        trimmed_path = os.path.join(job.workdir, f"trimmed{job.output_ext}")
        save_audio(trimmed_path, y_trim, sr, subtype=out_spec["subtype"], dither=out_dither)
        _tag_export(trimmed_path, upload_path, export_meta.get("tags"), note)
        job.trimmed_path = trimmed_path
        trim_report = {
            "enabled": True,
            "cut_head_s": round(cut_head, 3),
            "cut_tail_s": round(cut_tail, 3),
        }

    # Save to folder: the file the Download button would give, copied
    # into the user's folder as part of the run (the trimmed variant is
    # the export when silence trim is on). A copy that fails is reported,
    # not fatal: the run's files are still on the server to download.
    saved_report: Dict[str, Any] = {"enabled": False}
    if save_folder:
        src_kind = "trimmed" if trim_silence else "processed"
        src_path = job.trimmed_path if trim_silence else processed_path
        dest = os.path.join(save_folder, _download_name(job, src_kind))
        try:
            os.makedirs(save_folder, exist_ok=True)
            shutil.copyfile(src_path, dest)
            job.saved_path = dest
            saved_report = {"enabled": True, "path": dest,
                            "folder": save_folder,
                            "name": os.path.basename(dest)}
        except OSError as e:
            saved_report = {"enabled": True, "folder": save_folder,
                            "error": str(e.strerror or e)}

    # Report-stage numbers: band spectra before / after / removed, the
    # peak-to-loudness ratio and the stereo correlation, plus what the
    # export actually is. Measurement only.
    try:
        spectra = spectra_report(x, y2, removed, sr)
    except Exception:  # noqa: BLE001
        spectra = None
    try:
        loudness = dict(loudness)
        loudness["input_plr_db"] = plr_db(x, sr, loudness.get("input_lufs_i"))
        loudness["output_plr_db"] = plr_db(y2, sr, loudness.get("output_lufs_i"))
        loudness["input_correlation"] = stereo_correlation(x)
        loudness["output_correlation"] = stereo_correlation(y2)
    except Exception:  # noqa: BLE001
        pass
    ext = job.output_ext.lower()
    export = {
        "format": ext.lstrip("."),
        "format_key": out_spec.get("key", ext.lstrip(".")),
        "subtype": out_spec["subtype"] if ext in (".wav", ".flac") else None,
        "bit_depth": out_spec.get("bit_depth"),
        "dither": out_dither,
        "sample_rate": int(sr),
        "bitrate": "320k" if ext == ".mp3" else None,
        "tags": tags_report,
        "saved": saved_report,
        # What the Download step shows: the download's filename and size.
        "name": _download_name(job, "trimmed" if trim_silence else "processed"),
        "size_bytes": _file_size(job.trimmed_path if trim_silence else processed_path),
    }

    # Release check: the verdict on the file the user downloads.
    release = None
    if use_mastering:
        try:
            release = release_check(
                y_export, sr, x_in=x, mastering=mastering_report, export=export,
                correlation=loudness.get("output_correlation"),
                duration_s=float(y_export.shape[0] / sr),
                tags=tags_report.get("tags"),
                tags_written=bool(tags_report.get("written")))
        except Exception:  # noqa: BLE001
            release = None

    job.processed_path = processed_path
    job.diff_path = diff_path
    job.metrics = {
        "spectra": spectra,
        "export": export,
        "release": release,
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
        "edge_trim": edge_trim_report,
        "repair": pipe_report.get("static_repair", {"enabled": False}),
        "declick": pipe_report.get("declick", {"enabled": False}),
        "cutoff_hz": float(params.cutoff_hz or 0.0),
        "eq": pipe_report.get("eq", {"enabled": False}),
    }


async def _run_job_async(job: Job, upload_path: str, params: Params,
                         preserve_vol: bool,
                         master_params: Optional[MasterParams] = None,
                         mastering_analysis: Optional[Dict[str, Any]] = None,
                         trim_silence: bool = False,
                         eq_params: Optional[EqParams] = None,
                         trim_in_s: float = 0.0,
                         trim_out_s: Optional[float] = None,
                         repair_req: Optional[Dict[str, Any]] = None,
                         export_meta: Optional[Dict[str, Any]] = None) -> None:
    """Schedule the worker on the default executor; push done sentinel."""
    loop = asyncio.get_running_loop()
    cb = _threadsafe_progress_pusher(job, loop)
    job.status = "running"
    try:
        await loop.run_in_executor(
            None, _run_job_sync,
            job, upload_path, params, preserve_vol, cb,
            master_params, mastering_analysis, trim_silence, eq_params,
            trim_in_s, trim_out_s, repair_req, export_meta)
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


@app.post("/api/chain")
async def api_chain(payload: Dict[str, Any]) -> JSONResponse:
    """Describe the processing chain for the given settings (Signal Chain
    tab). Uses the same resolvers as /api/process — preset, strength,
    overrides, mastering, EQ, export format — so the view shows exactly
    what a run would do. Reads settings only; touches no audio."""
    from .chain import build_chain
    data = payload or {}
    p = _params_from_json(data)
    mp = _master_params_from_request(data)
    output_format = str(data.get("output_format") or "wav")
    if (data.get("mastering") or {}).get("ceiling_dbtp") is None:
        mp.ceiling_dbtp = get_export_ceiling_dbtp(output_format)
    eqp = _eq_params_from_request(data)
    eq_bands = len(eqp.active_bands(44100)) if eqp.is_active(44100) else 0
    return JSONResponse(build_chain(
        p, mp,
        eq_bands=eq_bands,
        preserve_volume=bool(data.get("preserve_volume", True)),
        trim_silence=bool(data.get("trim_silence", False)),
        output_format=output_format,
        trim_armed=bool(data.get("trim_armed", False)),
        repair=data.get("repair"),
        save_folder=str(data.get("save_folder") or ""),
    ))


# ── Reference library (developer tooling) ───────────────────────────────
#
# Builds the tone target from music playing on this machine. Reachable at
# /static/references/ and deliberately NOT in the app's navigation — the same
# arrangement as /static/marketing/. Users get the constant this produces,
# not the machine that produces it. See shimmer/references.py.


@app.get("/api/dev/references/devices")
async def api_ref_devices() -> JSONResponse:
    from . import references as refs
    if not refs.available():
        return JSONResponse({"available": False, "devices": [],
                             "hint": "pip install soundcard"})
    try:
        return JSONResponse({"available": True, "devices": refs.devices()})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"available": False, "devices": [], "hint": str(e)})


@app.post("/api/dev/references/start")
async def api_ref_start(payload: Dict[str, Any]) -> JSONResponse:
    from . import references as refs
    return JSONResponse(refs.start(str(payload.get("device_id") or ""),
                                   str(payload.get("label") or "")))


@app.get("/api/dev/references/status")
async def api_ref_status() -> JSONResponse:
    from . import references as refs
    return JSONResponse(refs.status())


@app.post("/api/dev/references/stop")
async def api_ref_stop(payload: Dict[str, Any]) -> JSONResponse:
    from . import references as refs
    return JSONResponse(refs.stop(str(payload.get("label") or ""),
                                  str(payload.get("genre") or "")))


@app.get("/api/dev/references/library")
async def api_ref_library() -> JSONResponse:
    from . import references as refs
    return JSONResponse(refs.summary())


@app.get("/api/dev/references/report")
async def api_ref_report() -> JSONResponse:
    from . import references as refs
    return JSONResponse(refs.report())


@app.post("/api/dev/references/delete")
async def api_ref_delete(payload: Dict[str, Any]) -> JSONResponse:
    from . import references as refs
    return JSONResponse(refs.delete(int(payload.get("index", -1))))


# ── Listening bench (dev) ───────────────────────────────────────────────
# Instant, level-matched, blind A/B. The answer key is behind its own route
# so the page cannot leak it by accident.

@app.get("/api/dev/ab/sets")
async def api_ab_sets() -> JSONResponse:
    from . import abtest
    return JSONResponse({"sets": abtest.sets()})


@app.get("/api/dev/ab/set/{set_id}")
async def api_ab_set(set_id: str) -> JSONResponse:
    from . import abtest
    m = abtest.manifest(set_id)
    if not m:
        return JSONResponse({"error": "no such set"}, status_code=404)
    m["scores"] = abtest.scores(set_id).get("rounds", [])
    return JSONResponse(m)


@app.get("/api/dev/ab/audio/{set_id}/{filename}")
async def api_ab_audio(set_id: str, filename: str) -> Response:
    from . import abtest
    p = abtest.audio_path(set_id, filename)
    if not p:
        return JSONResponse({"error": "no such file"}, status_code=404)
    return FileResponse(p, media_type="audio/wav")


@app.get("/api/dev/ab/reveal/{set_id}")
async def api_ab_reveal(set_id: str) -> JSONResponse:
    from . import abtest
    k = abtest.reveal(set_id)
    if not k:
        return JSONResponse({"error": "no such set"}, status_code=404)
    return JSONResponse(k)


@app.post("/api/dev/ab/score/{set_id}")
async def api_ab_score(set_id: str, payload: Dict[str, Any]) -> JSONResponse:
    from . import abtest
    return JSONResponse(abtest.score(set_id, payload or {}))


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


@app.post("/api/reveal")
async def api_reveal(payload: Dict[str, Any]) -> JSONResponse:
    """Show a file the server wrote (a "Save to folder" export) in the OS
    file manager. Shimmer runs on the user's own machine, so this is the
    Download step's "Show in folder". `{"path": "..."}` → `{"ok": bool}`;
    404 when the path does not exist."""
    path = str((payload or {}).get("path") or "").strip()
    if not path:
        raise HTTPException(400, "No path given")
    if not os.path.exists(path):
        raise HTTPException(404, f"Not found: {path}")
    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, _REVEAL_LAUNCHER, os.path.abspath(path))
    return JSONResponse({"ok": bool(ok)})


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
    trim_in_s: float = Form(0.0),
    trim_out_s: Optional[float] = Form(None),
    save_folder: str = Form(""),
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
    eqp = _eq_params_from_request(params_data)
    mastering_analysis = params_data.get("mastering_analysis")

    try:
        out_spec = resolve_output_format(output_format)
    except ValueError as e:
        raise HTTPException(400, str(e))
    output_ext = out_spec["ext"]
    # "Save to folder": checked now so a bad folder fails in a second,
    # not after a full run.
    save_folder = _validated_save_folder(save_folder)

    # Codec-aware true-peak ceiling: lossy encoders overshoot on decode,
    # so MP3/OGG/M4A exports get -1.5 dBTP unless the user explicitly
    # chose a ceiling.
    if (params_data.get("mastering") or {}).get("ceiling_dbtp") is None:
        mp.ceiling_dbtp = get_export_ceiling_dbtp(output_ext)

    job = JOB_STORE.create(output_ext=output_ext)
    job.preset_name = params_data.get("preset") or "generic"

    orig_name = Path(file.filename or "upload").name
    # Exports never chain suffixes: a pass-2 file is named from the
    # original stem, and the pass ledger lives in the tags instead.
    job.source_stem = strip_shimmer_suffix(Path(orig_name).stem) or "audio"
    job.original_path = os.path.join(job.workdir, "input_" + orig_name)
    with open(job.original_path, "wb") as f:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)

    # Fire-and-forget worker task; progress flows via job.queue → SSE.
    try:
        preset_strength = float(params_data.get("preset_strength", 1.0))
    except (TypeError, ValueError):
        preset_strength = 1.0
    export_meta = {
        "tags": params_data.get("tags") if isinstance(params_data.get("tags"), dict) else None,
        "preset_strength": preset_strength,
        "save_folder": save_folder,
        "output": out_spec,
    }
    asyncio.create_task(_run_job_async(
        job, job.original_path, p, preserve_volume, mp, mastering_analysis,
        trim_silence, eqp, trim_in_s, trim_out_s,
        params_data.get("repair"), export_meta))
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
        ".m4a": "audio/mp4", ".zip": "application/zip",
    }.get(ext, "application/octet-stream")
    # Make download filenames informative + unique-per-run so successive
    # downloads of different presets / different songs don't all collide on
    # `processed.wav` in the user's Downloads folder. Filesystem-safe stem +
    # short job id so old/new runs are visually distinguishable.
    download_name = _download_name(job, kind, ext)
    return FileResponse(path, media_type=media, filename=download_name)


# ───────────────────────────────────────────────────────────────────────────
# Suggest preset
# ───────────────────────────────────────────────────────────────────────────

@app.post("/api/suggest")
async def api_suggest(file: UploadFile = File(...),
                      tone_family: str = Form("neutral"),
                      mastering: str = Form(""),
                      tone: bool = Form(True),
                      overrides: str = Form("")) -> JSONResponse:
    """Artifact preset suggestion + loudness/spectrum analysis, the
    source file's tags, and the Tone plan (suggested EQ) judged for the
    picked preset and the current mastering settings."""
    from .probe import suggest_preset

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
        result["source_tags"] = await loop.run_in_executor(None, read_tags, tmp_path)
        if tone:
            mp = _parse_master_form(mastering)
            ov = _parse_json_form(overrides)
            try:
                result["tone_plan"] = await loop.run_in_executor(
                    None, _tone_plan_for, x, sr, analysis,
                    result.get("preset") or "generic",
                    float(result.get("strength") or 1.0),
                    tone_family, mp, result.get("repair_plan"), ov)
            except Exception as e:  # noqa: BLE001
                result["tone_plan"] = {"error": str(e)}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return JSONResponse(result)


@app.post("/api/analyze")
async def api_analyze(file: UploadFile = File(...),
                      tone_family: str = Form("neutral"),
                      mastering: str = Form(""),
                      tone: bool = Form(True),
                      overrides: str = Form("")) -> JSONResponse:
    """Combined artifact detect + mastering analysis (alias of suggest)."""
    return await api_suggest(file, tone_family, mastering, tone, overrides)


def _parse_json_form(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _parse_master_form(raw: str) -> Optional[MasterParams]:
    data = _parse_json_form(raw)
    if not data:
        return None
    return master_params_from_json(data)


@app.get("/api/tone/families")
async def api_tone_families() -> JSONResponse:
    return JSONResponse({"families": family_list()})


@app.post("/api/tone")
async def api_tone(file: UploadFile = File(...),
                   preset: str = Form("generic"),
                   preset_strength: float = Form(1.0),
                   tone_family: str = Form("neutral"),
                   mastering: str = Form(""),
                   repair: str = Form(""),
                   overrides: str = Form("")) -> JSONResponse:
    """Re-plan the Tone step for a file with the current preset, strength,
    family and mastering settings (family picker, pass 2 of a two-pass run)."""
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
        x, sr = await loop.run_in_executor(None, load_audio, tmp_path)
        analysis = await loop.run_in_executor(None, analyze_track, x, sr)
        source_tags = await loop.run_in_executor(None, read_tags, tmp_path)
        repair_dict = _parse_json_form(repair) or None
        if repair_dict is None:
            plan_obj = await loop.run_in_executor(
                None, lambda: plan_from_lines(scan_fixed_lines(x, sr), sr))
            repair_dict = plan_obj.as_dict()
        plan = await loop.run_in_executor(
            None, _tone_plan_for, x, sr, analysis, preset,
            float(preset_strength), tone_family, _parse_master_form(mastering),
            repair_dict, _parse_json_form(overrides))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Tone plan failed: {e}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return JSONResponse({"tone_plan": plan, "analysis": analysis,
                         "source_tags": source_tags})


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
    try:
        out_spec = resolve_output_format(output_format)
    except ValueError as e:
        raise HTTPException(400, str(e))
    auto_detect = bool(payload.get("auto_detect", False))
    trim_silence = bool(payload.get("trim_silence", False))
    static_repair = bool(payload.get("static_repair", True))
    mp = master_params_from_json(payload.get("mastering") or {})
    eqp = eq_params_from_json(payload.get("eq") or {})
    auto_eq = bool(payload.get("auto_eq", False))
    tone_family = normalize_family(payload.get("tone_family"))
    tags_req = payload.get("tags") if isinstance(payload.get("tags"), dict) else None
    # Codec-aware ceiling unless the user explicitly chose one.
    if (payload.get("mastering") or {}).get("ceiling_dbtp") is None:
        mp.ceiling_dbtp = get_export_ceiling_dbtp(out_spec["ext"])
    # Album mode: one gain for the whole folder (see _album_gain). Only
    # meaningful with mastering on.
    album_mode = bool(payload.get("album_mode", False)) and bool(mp.enabled)

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
            "album_mode": album_mode,
        })
        if not files:
            yield _sse_event({"type": "end",
                              "message": "No audio files found"})
            return
        loop = asyncio.get_running_loop()

        if album_mode:
            # Two passes. Pass 1 cleans every track with mastering held
            # back and parks the pre-master signal on disk; the album's
            # gain is then decided from the loudest track; pass 2
            # masters each track with that one gain. The parked files
            # go when the run ends, however it ends.
            tmp_dir = tempfile.mkdtemp(prefix="shimmer_album_")
            try:
                infos: List[Dict[str, Any]] = []
                yield _sse_event({
                    "type": "phase", "phase": "clean", "total": len(files),
                    "message": "Pass 1 of 2: cleaning every track; mastering waits until the album's level is known",
                })
                for i, src in enumerate(files):
                    name = os.path.basename(src)
                    yield _sse_event({"type": "file_start", "phase": "clean",
                                      "index": i, "name": name})
                    tmp = os.path.join(tmp_dir, f"{i:03d}.wav")
                    try:
                        info = await loop.run_in_executor(
                            None, _album_clean_one, src, tmp, preset,
                            auto_detect, preset_strength, mp, eqp,
                            static_repair, auto_eq, tone_family, out_spec["sr"])
                        info.update({"index": i, "name": name, "src": src})
                        infos.append(info)
                        yield _sse_event({
                            "type": "file_done", "phase": "clean",
                            "index": i, "name": name,
                            "duration_s": info["duration_s"],
                            "lufs_clean": info["lufs_clean"],
                            "true_peak_clean": info["true_peak_clean"],
                            "peak_in_db": info["input"]["peak_dbfs"],
                            "tone_moves": info.get("tone_moves"),
                            "tone_summary": info.get("tone_summary"),
                            "detected_preset": info.get("detected_preset"),
                            "detected_label": info.get("detected_label"),
                            "detected_confidence": info.get("detected_confidence"),
                            "detected_strength": info.get("detected_strength"),
                            "effective_strength": info.get("effective_strength"),
                        })
                    except Exception as e:  # noqa: BLE001
                        yield _sse_event({"type": "file_error", "phase": "clean",
                                          "index": i, "name": name, "error": str(e)})
                album = _album_gain(infos, float(mp.target_lufs))
                yield _sse_event({"type": "album", "target_lufs": float(mp.target_lufs),
                                  "tracks": len(infos), **album})
                if not infos:
                    yield _sse_event({"type": "end", "total": len(files),
                                      "message": "No track could be cleaned"})
                    return
                yield _sse_event({
                    "type": "phase", "phase": "master", "total": len(infos),
                    "message": "Pass 2 of 2: mastering every track with the album's gain",
                })
                for info in infos:
                    i, name, src = info["index"], info["name"], info["src"]
                    dst = os.path.join(
                        output_folder, os.path.splitext(name)[0] + out_spec["ext"])
                    yield _sse_event({"type": "file_start", "phase": "master",
                                      "index": i, "name": name})
                    try:
                        r = await loop.run_in_executor(
                            None, _album_master_one, info, src, dst, mp,
                            float(album["gain_db"]), trim_silence, tags_req,
                            out_spec["subtype"])
                        after = (r.get("mastering") or {}).get("after") or {}
                        yield _sse_event({
                            "type": "file_done", "phase": "master",
                            "index": i, "name": name,
                            "duration_s": r["duration_s"],
                            "tags_written": r.get("tags_written"),
                            "trim": r.get("trim"),
                            "peak_in_db": (r.get("input") or {}).get("peak_dbfs"),
                            "peak_out_db": r["output"]["peak_dbfs"],
                            "lufs_out": _finite_or_none(after.get("lufs_i")),
                            "true_peak_out": _finite_or_none(after.get("true_peak_dbtp")),
                            "limiter_gr_db": (r.get("mastering") or {}).get("limiter_gain_reduction"),
                            "gain_db": float(album["gain_db"]),
                            "release": release_summary(r.get("release")),
                        })
                    except Exception as e:  # noqa: BLE001
                        yield _sse_event({"type": "file_error", "phase": "master",
                                          "index": i, "name": name, "error": str(e)})
                yield _sse_event({"type": "end", "total": len(files)})
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            return

        for i, src in enumerate(files):
            name = os.path.basename(src)
            dst = os.path.join(
                output_folder, os.path.splitext(name)[0] + out_spec["ext"])
            yield _sse_event({"type": "file_start", "index": i, "name": name})
            try:
                r = await loop.run_in_executor(
                    None, _batch_one, src, dst, preset, preserve_vol,
                    auto_detect, preset_strength, mp, trim_silence, eqp,
                    static_repair, auto_eq, tone_family, tags_req,
                    out_spec["subtype"], out_spec["sr"])
                yield _sse_event({
                    "type": "file_done", "index": i, "name": name,
                    "duration_s": r["duration_s"],
                    "tone_moves": r.get("tone_moves"),
                    "tone_summary": r.get("tone_summary"),
                    "tags_written": r.get("tags_written"),
                    "trim": r.get("trim"),
                    "peak_in_db": r["input"]["peak_dbfs"],
                    "peak_out_db": r["output"]["peak_dbfs"],
                    "detected_preset": r.get("detected_preset"),
                    "detected_label": r.get("detected_label"),
                    "detected_confidence": r.get("detected_confidence"),
                    "detected_strength": r.get("detected_strength"),
                    "effective_strength": r.get("effective_strength"),
                    # Per-file verification when mastering ran.
                    "lufs_out": _finite_or_none(
                        ((r.get("mastering") or {}).get("after") or {}).get("lufs_i")),
                    "true_peak_out": _finite_or_none(
                        ((r.get("mastering") or {}).get("after") or {}).get("true_peak_dbtp")),
                    "limiter_gr_db": (r.get("mastering") or {}).get("limiter_gain_reduction"),
                    "release": release_summary(r.get("release")),
                })
            except Exception as e:  # noqa: BLE001
                yield _sse_event({
                    "type": "file_error", "index": i, "name": name,
                    "error": str(e),
                })
        yield _sse_event({"type": "end", "total": len(files)})

    return StreamingResponse(stream(), media_type="text/event-stream")


def _batch_prepare(src: str, preset_name: str, auto_detect: bool,
                   preset_strength: float,
                   master_params: Optional[MasterParams],
                   eq_params: Optional[EqParams],
                   auto_eq: bool, tone_family: str
                   ) -> Tuple[Params, Optional[EqParams], Dict[str, Any], float]:
    """The per-file choices every batch pass makes before touching the
    audio: the preset (fixed, or auto-detected with its own strength),
    the strength scaling, and the suggested EQ judged after that file's
    cleaning. Returns (params, eq_params, detected_info, strength)."""
    detected_info: Dict[str, Any] = {}

    if auto_detect:
        from .probe import suggest_preset as _suggest
        from .presets import label_for
        suggestion = _suggest(src)
        chosen = suggestion.get("preset") or "generic"
        ranked = suggestion.get("ranked") or []
        confidence = ranked[0]["confidence"] if ranked else 0.0
        # The analysis recommends a strength for its pick.  In auto mode
        # the batch strength slider multiplies it (100% = trust the
        # analysis), and the product goes through the same
        # apply_preset_strength hook as a manual strength choice.
        detected_strength = float(suggestion.get("strength") or 1.0)
        effective_strength = max(0.0, min(2.0, detected_strength * preset_strength))
        detected_info = {
            "detected_preset": chosen,
            "detected_label": label_for(chosen),
            "detected_confidence": round(float(confidence), 2),
            "detected_strength": round(detected_strength, 2),
            "effective_strength": round(effective_strength, 2),
        }
        params = get_preset(chosen)
        preset_strength = effective_strength
    else:
        params = get_preset(preset_name)

    # Apply preset strength scaling.
    if abs(preset_strength - 1.0) > 1e-6:
        apply_preset_strength(params, preset_strength)

    # Suggested EQ per file: the Tone plan for this track, judged after
    # its own cleaning, added to any EQ the user set on the Master tab.
    if auto_eq:
        x, sr = load_audio(src)
        analysis = analyze_track(x, sr)
        chosen_name = detected_info.get("detected_preset") or preset_name
        plan = _tone_plan_for(x, sr, analysis, chosen_name, preset_strength,
                              tone_family, master_params)
        moves = plan.get("moves") or []
        detected_info["tone_moves"] = len(moves)
        detected_info["tone_summary"] = plan.get("summary", "")
        if moves:
            base = eq_params.bands if (eq_params is not None and eq_params.enabled) else []
            merged = eq_params_from_json(moves_to_eq_payload(moves))
            eq_params = EqParams(enabled=True, bands=list(base) + list(merged.bands))
    return params, eq_params, detected_info, preset_strength


def _batch_one(src: str, dst: str, preset_name: str, preserve_vol: bool,
               auto_detect: bool = False, preset_strength: float = 1.0,
               master_params: Optional[MasterParams] = None,
               trim_silence: bool = False,
               eq_params: Optional[EqParams] = None,
               static_repair: bool = True,
               auto_eq: bool = False,
               tone_family: str = "neutral",
               tags_req: Optional[Dict[str, Any]] = None,
               subtype: str = "PCM_24",
               target_sr: Optional[int] = None):
    params, eq_params, detected_info, preset_strength = _batch_prepare(
        src, preset_name, auto_detect, preset_strength, master_params,
        eq_params, auto_eq, tone_family)

    result = process_file(
        input_path=src, output_path=dst,
        params=params, do_preserve_volume=preserve_vol,
        master_params=master_params,
        trim_silence=trim_silence,
        eq_params=eq_params,
        static_repair=static_repair,
        subtype=subtype,
        target_sr=target_sr,
    )
    result.update(detected_info)

    mastered = master_params is not None and master_params.enabled
    eq_bands = len(eq_params.active_bands(44100)) if eq_params is not None and eq_params.is_active(44100) else 0
    chosen = detected_info.get("detected_preset") or preset_name
    eff_strength = float(detected_info.get("effective_strength", preset_strength))
    note = shimmer_note(
        f"Shimmer {SHIMMER_VERSION}", _pass_label(src),
        label_for(chosen) if chosen in PRESET_NAMES else chosen,
        eff_strength, mastered,
        float(master_params.target_lufs) if mastered else None,
        float(master_params.ceiling_dbtp) if mastered else None,
        eq_bands=eq_bands,
        # Diff against the EXACT strength the scaling used, not the rounded
        # copy in detected_info. `_batch_prepare` scales with the unrounded
        # value and rounds only for display, so rebuilding the baseline from
        # the rounded number makes every scaled field differ by a hair and the
        # note then lists the whole preset recipe as if the user typed it.
        overrides=preset_overrides(params, chosen, preset_strength),
        eq_moves=_eq_moves(eq_params, 44100),
        tone=_tone_label(master_params if mastered else None))
    tag_rep = _tag_export(dst, src, tags_req, note)
    result["tags_written"] = bool(tag_rep.get("written"))
    if result.get("release"):
        result["release"] = add_check(
            result["release"], tags_check(tag_rep.get("tags"), bool(tag_rep.get("written"))))
    return result


# ── Album mode ───────────────────────────────────────────────────────────
# A folder mastered as one record. Normalising each track on its own
# flattens the album: the quiet song ends up as loud as the single.
# Album mode cleans every track first (pass 1), parks the pre-master
# signal, decides one gain from the loudest track, and masters each
# track with that gain (pass 2), so the tracks keep their distance and
# no track is limited harder than it would be on its own.

def _album_clean_one(src: str, tmp_dst: str, preset_name: str,
                     auto_detect: bool, preset_strength: float,
                     master_params: MasterParams,
                     eq_params: Optional[EqParams], static_repair: bool,
                     auto_eq: bool, tone_family: str,
                     target_sr: Optional[int] = None) -> Dict[str, Any]:
    """Pass 1 for one file: clean with mastering deferred, park the
    pre-master signal as a float WAV, and measure its loudness."""
    params, eqp, detected_info, strength = _batch_prepare(
        src, preset_name, auto_detect, preset_strength, master_params,
        eq_params, auto_eq, tone_family)
    x, sr = load_audio(src)
    x, sr = resample_to(x, sr, target_sr)
    plan = plan_from_lines(scan_fixed_lines(x, sr), sr) if static_repair else None
    params.cutoff_hz = float(estimate_cutoff_hz(x, sr).get("cutoff_hz") or 0.0)
    y, _removed, rep = clean_and_master(
        x, sr, params, master_params=master_params, eq_params=eqp,
        repair=plan, defer_master=True)
    save_audio(tmp_dst, y, sr, subtype="FLOAT")
    loud = (rep.get("mastering") or {}).get("before") or measure_loudness(y, sr)
    info: Dict[str, Any] = {
        "tmp": tmp_dst, "sr": sr,
        "duration_s": float(x.shape[0] / sr),
        "input": measure(x),
        "lufs_clean": _finite_or_none(loud.get("lufs_i")),
        "true_peak_clean": _finite_or_none(loud.get("true_peak_dbtp")),
        "clipped_samples": count_clipped(x),
        "strength": float(strength),
        "eq_bands": len(eqp.active_bands(sr)) if eqp is not None and eqp.is_active(sr) else 0,
        "preset": detected_info.get("detected_preset") or preset_name,
        # Carried to pass 2, which writes the tags but no longer holds the
        # params: without these the album note names a preset the run may
        # not have used unmodified.
        # The exact strength, not detected_info's rounded copy — see the note
        # in _batch_one for why the rounded one fabricates tweaks.
        "overrides": preset_overrides(
            params, detected_info.get("detected_preset") or preset_name,
            strength),
        "eq_moves": _eq_moves(eqp, sr),
    }
    info.update(detected_info)
    return info


def _album_gain(infos: List[Dict[str, Any]], target_lufs: float) -> Dict[str, Any]:
    """One gain for the whole album: the loudest cleaned track lands on
    the target and every other track keeps its distance below it. Also
    reports the album's overall loudness (the duration-weighted energy
    mean of the tracks' integrated loudness, close to a gated
    measurement of the record played end to end) and the spread."""
    rows = [(i, float(i["lufs_clean"]), float(i.get("duration_s") or 0.0))
            for i in infos if i.get("lufs_clean") is not None]
    if not rows:
        return {"gain_db": 0.0, "loudest": None, "loudest_lufs": None,
                "album_lufs": None, "spread_lu": None}
    loudest = max(rows, key=lambda r: r[1])
    total = sum(d for _, _, d in rows) or 1.0
    energy = sum(d * 10.0 ** (l / 10.0) for _, l, d in rows) / total
    return {
        "gain_db": float(target_lufs - loudest[1]),
        "loudest": loudest[0].get("name"),
        "loudest_lufs": loudest[1],
        "album_lufs": float(10.0 * math.log10(max(energy, 1e-20))),
        "spread_lu": float(loudest[1] - min(l for _, l, _ in rows)),
    }


def _album_master_one(info: Dict[str, Any], src: str, dst: str,
                      master_params: MasterParams, gain_db: float,
                      trim_silence: bool,
                      tags_req: Optional[Dict[str, Any]],
                      subtype: str = "PCM_24") -> Dict[str, Any]:
    """Pass 2 for one file: master the parked track with the album's
    gain (shaper and limiter still per track), trim, write, tag."""
    y, sr = load_audio(info["tmp"])
    y2, m_report = master(y, sr, master_params, fixed_gain_db=gain_db)
    trim_report: Dict[str, Any] = {"enabled": False}
    if trim_silence:
        y2, cut_head, cut_tail = dsp_trim_silence(y2, sr)
        trim_report = {"enabled": True, "cut_head_s": round(cut_head, 3),
                       "cut_tail_s": round(cut_tail, 3)}
    save_audio(dst, y2, sr, subtype=subtype,
               dither=str(subtype).upper() in ("PCM_16", "PCM16"))
    chosen = str(info.get("preset") or "generic")
    note = shimmer_note(
        f"Shimmer {SHIMMER_VERSION}", _pass_label(src),
        label_for(chosen) if chosen in PRESET_NAMES else chosen,
        float(info.get("effective_strength", info.get("strength", 1.0))), True,
        float(master_params.target_lufs), float(master_params.ceiling_dbtp),
        eq_bands=int(info.get("eq_bands", 0)),
        overrides=list(info.get("overrides") or []),
        eq_moves=list(info.get("eq_moves") or []),
        tone=_tone_label(master_params))
    tag_rep = _tag_export(dst, src, tags_req, note)
    ext = os.path.splitext(dst)[1].lstrip(".").lower()
    # This track's level under album mode: its cleaned loudness plus the
    # album's one gain. The loudest track lands on the target; the rest
    # sit below it by design, so the release check grades against that.
    clean_lufs = _finite_or_none(info.get("lufs_clean"))
    expected = (float(clean_lufs) + float(gain_db)) if clean_lufs is not None else None
    release = release_check(
        y2, sr, mastering=m_report,
        export={"format": ext,
                "bit_depth": ((16 if str(subtype).upper() in ("PCM_16", "PCM16") else 24)
                              if ext in ("wav", "flac") else None)},
        clipped_samples=info.get("clipped_samples"),
        correlation=stereo_correlation(y2),
        duration_s=float(y2.shape[0] / sr),
        tags=tag_rep.get("tags"), tags_written=bool(tag_rep.get("written")),
        expected_lufs=expected)
    return {
        "duration_s": float(y2.shape[0] / sr),
        "input": info.get("input") or {},
        "output": measure(y2),
        "mastering": m_report,
        "trim": trim_report,
        "tags_written": bool(tag_rep.get("written")),
        "release": release,
    }


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
    # Scan both edges for render glitches. Reported, never auto-applied —
    # the UI raises it and the user decides.
    edges = await loop2.run_in_executor(None, detect_edge_artifacts, x, sr)
    # Content digest: keys both the stem cache and the per-track project
    # store, so the client can restore prior work for this exact file.
    digest = await loop2.run_in_executor(
        None, stems_mod.file_digest, orig_path)

    sess = PREVIEW_STORE.create(
        samples=x, sr=sr,
        original_path=orig_path,
        original_name=orig_name,
    )
    sess.track_analysis = track_analysis
    sess.digest = digest
    # Whole-file scan for the generator's fixed lines: the static-repair
    # plan every preview slice and run for this session starts from.
    lines = await loop2.run_in_executor(None, scan_fixed_lines, x, sr)
    sess.repair_lines = lines
    source_tags = await loop2.run_in_executor(None, read_tags, orig_path)
    PREVIEW_STORE.sweep()
    return JSONResponse({
        "session_id": sess.id,
        "source_tags": source_tags,
        "title_hint": title_from_stem(Path(orig_name).stem),
        "sample_rate": sr,
        "channels": sess.channels,
        "duration_s": sess.duration_s,
        "name": orig_name,
        "analysis": track_analysis,
        "edges": edges,
        "repair": {"lines": lines, "plan": plan_from_lines(lines, sr).as_dict()},
        "digest": digest,
        # Any tier with a finished stem set for this exact file: the
        # Remix tab separates instantly on those.
        "stems_cached": bool(stems_mod.cached_models(digest)),
        "stems_tiers": stems_mod.cached_tiers(digest),
        "project": load_project(digest),
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


def _whole_file_lufs(sess) -> Optional[float]:
    """Integrated LUFS of the whole uploaded track, cached on the session."""
    loud = (sess.track_analysis or {}).get("loudness") or {}
    v = loud.get("lufs_i")
    if v is not None and np.isfinite(float(v)):
        return float(v)
    try:
        v = measure_loudness(sess.samples, sess.sr).get("lufs_i")
    except Exception:  # noqa: BLE001
        return None
    if v is None or not np.isfinite(float(v)):
        return None
    ta = dict(sess.track_analysis or {})
    ta.setdefault("loudness", {})
    ta["loudness"] = dict(ta["loudness"], lufs_i=float(v))
    sess.track_analysis = ta
    return float(v)


def _master_loudness_ref(sess, block: np.ndarray, sr: int
                         ) -> Optional[Dict[str, float]]:
    """Whole-file loudness reference for mastering a preview slice.

    Mastering normalises whatever it is given to the target.  Given a
    slice on its own, a quiet verse is boosted to the target while the
    full run leaves it quiet, so the preview plays a level the export
    never has — and the A/B loudness match then turns the Processed
    monitor down by that difference.  With this reference `master()`
    applies the gain the whole file will get.
    """
    whole = _whole_file_lufs(sess)
    if whole is None:
        return None
    try:
        sl = measure_loudness(block, sr).get("lufs_i")
    except Exception:  # noqa: BLE001
        return None
    if sl is None or not np.isfinite(float(sl)):
        return None
    return {"whole_lufs": float(whole), "slice_lufs": float(sl)}


def _render_preview_sync(sess, start_s: float, end_s: float, p: Params,
                         preserve_vol: bool,
                         master_params: Optional[MasterParams] = None,
                         eq_params: Optional[EqParams] = None,
                         repair: Optional[NotchPlan] = None) -> Dict[str, Any]:
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
        eq_params=eq_params,
        master_loudness_ref=(
            _master_loudness_ref(sess, in_slice, sr) if use_mastering else None),
        repair=repair,
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
    eqp = eq_params_from_json(payload.get("eq") or {})
    # Static repair from the session's whole-file scan (or the client's
    # explicit list), so a preview slice gets the same notches the run will.
    repair_plan = _repair_plan_for(
        None, sess.sr, payload.get("repair"), lines=sess.repair_lines)

    try:
        p = _params_from_json({
            "preset": payload.get("preset") or "generic",
            "preset_strength": payload.get("preset_strength"),
            "overrides": payload.get("overrides") or {},
        })
    except KeyError as e:
        raise HTTPException(400, f"Unknown preset: {e}")
    p.cutoff_hz = float((sess.track_analysis or {}).get("cutoff_hz") or 0.0)

    loop = asyncio.get_running_loop()
    t0 = time.time()
    try:
        result = await loop.run_in_executor(
            None, _render_preview_sync, sess, start_s, end_s, p,
            preserve_vol, mp, eqp, repair_plan)
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


@app.get("/api/envelope/{session_id}")
async def api_envelope(session_id: str, start_s: float = 0.0,
                       end_s: float = 1.0, points: int = 600) -> JSONResponse:
    """Peak envelope in dBFS over a time range, for the Trim view.

    Returned in dB rather than linear amplitude on purpose: the artifacts
    this view exists to show sit near -50 dBFS, which is a flat line on a
    linear waveform. Served from the resident session, so scrubbing zoom
    levels costs no upload and no decode.
    """
    sess = PREVIEW_STORE.get(session_id)
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
    peaks = np.array([
        seg[idx[i]:max(idx[i] + 1, idx[i + 1])].max() for i in range(points)
    ], dtype=np.float64)
    db = 20.0 * np.log10(peaks + 1e-9)

    return JSONResponse({
        "start_s": a / sr,
        "end_s": b / sr,
        "sample_rate": sr,
        "db": [round(float(v), 2) for v in db],
    })


@app.delete("/api/upload/{session_id}")
async def api_upload_drop(session_id: str) -> JSONResponse:
    PREVIEW_STORE.drop(session_id)
    return JSONResponse({"ok": True})


# ───────────────────────────────────────────────────────────────────────────
# Projects — per-track persisted work (keyed by file content digest)
# ───────────────────────────────────────────────────────────────────────────

@app.get("/api/projects")
async def api_projects_list() -> JSONResponse:
    return JSONResponse({"projects": list_projects()})


@app.get("/api/project/{digest}")
async def api_project_get(digest: str) -> JSONResponse:
    return JSONResponse(load_project(digest))


@app.post("/api/project/{digest}")
async def api_project_save(digest: str,
                           payload: Dict[str, Any]) -> JSONResponse:
    if not save_project(digest, payload):
        raise HTTPException(400, "Invalid project digest")
    return JSONResponse({"ok": True})


# ───────────────────────────────────────────────────────────────────────────
# Stems / Remix — Demucs separation + per-stem effects
# ───────────────────────────────────────────────────────────────────────────

def _stem_order(sess) -> List[str]:
    """Display/mix order of the session's stems (stems.measure_stems
    decided it at separation; fall back to the canonical order)."""
    if not sess.stems:
        return []
    order = (sess.stems_info or {}).get("order")
    if order and all(n in sess.stems for n in order):
        return [n for n in order if n in sess.stems]
    return stems_mod.order_stems(sess.stems)


# Files the separation worker reads directly with libsndfile. Anything
# else (M4A/AAC needs ffmpeg) is handed over as a float WAV of the
# already-decoded session audio.
_SF_INPUT_EXTS = {".wav", ".flac", ".ogg", ".aiff", ".aif", ".mp3"}


def _separation_input(sess) -> str:
    ext = os.path.splitext(sess.original_path)[1].lower()
    if ext in _SF_INPUT_EXTS and os.path.isfile(sess.original_path):
        return sess.original_path
    path = os.path.join(sess.workdir, "stems_input.wav")
    if not os.path.isfile(path):
        save_audio(path, sess.samples, sess.sr, subtype="FLOAT")
    return path


@app.get("/api/stems/engine")
async def api_stems_engine(check: bool = True) -> JSONResponse:
    """Engine state for the Remix tab before anything is uploaded: is
    the side venv installed and importable, is there a GPU, and per
    quality tier the model, its checkpoint state and a time estimate.
    The import check costs a torch import, so it runs once per process."""
    loop = asyncio.get_running_loop()
    info = await loop.run_in_executor(None, stems_mod.engine_info, check)
    return JSONResponse(info)


@app.get("/api/stems/library")
async def api_stems_library() -> JSONResponse:
    """Every cached stem set on disk (digest, source name, models):
    the Recent sessions list badges tracks whose stems are done."""
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, stems_mod.library)
    return JSONResponse({"items": rows})


@app.get("/api/stems/status/{session_id}")
async def api_stems_status(session_id: str) -> JSONResponse:
    sess = PREVIEW_STORE.get(session_id)
    if sess is None:
        raise HTTPException(404, "Unknown session_id")
    digest = sess.digest
    if not digest:
        try:
            digest = stems_mod.file_digest(sess.original_path)
        except OSError:
            digest = ""
    return JSONResponse({
        "ready": sess.stems is not None,
        "cached": bool(digest and stems_mod.cached_models(digest)),
        "cached_tiers": stems_mod.cached_tiers(digest) if digest else [],
        "env_ready": stems_mod.stems_python() is not None,
        "cuda": stems_mod.has_cuda(),
        "info": sess.stems_info or {},
    })


@app.get("/api/stems/info/{session_id}")
async def api_stems_info(session_id: str) -> JSONResponse:
    """What the mixer draws after separation: tier and model, timing,
    the stem order, per-stem level/peak/share and lane peaks, the mix's
    peaks, the null-test figure and the suggested loop start."""
    sess = PREVIEW_STORE.get(session_id)
    if sess is None:
        raise HTTPException(404, "Unknown session_id")
    if not sess.stems:
        raise HTTPException(409, "Stems not separated yet")
    return JSONResponse(sess.stems_info or {})


@app.post("/api/stems/separate")
async def api_stems_separate(payload: Dict[str, Any]) -> JSONResponse:
    """Kick off separation for an upload session at a quality tier
    (`tier`: fast | best | six; default per stems.default_tier). Returns
    a job_id whose progress streams over the existing /api/progress SSE
    route with stages setup (first run only: the engine install),
    separate, load and null. When it finishes the session holds the
    stems plus the residual (mix − stems) and /api/stems/info has the
    measurements."""
    sid = payload.get("session_id") or ""
    sess = PREVIEW_STORE.get(sid)
    if sess is None:
        raise HTTPException(404, "Unknown session_id")
    tier = stems_mod.resolve_tier(payload.get("tier"))

    job = JOB_STORE.create()
    job.source_stem = Path(sess.original_name).stem or "audio"
    job.preset_name = tier.model
    loop = asyncio.get_running_loop()

    details = {
        "setup": "one-time install of the separation engine",
        "separate": f"{tier.label} · {tier.model} · {tier.stems} stems",
        "load": "reading the stems back at the session's sample rate",
        "null": "whatever the separator dropped becomes the Residual lane, "
                "so stems + residual = the original",
    }

    def _progress(frac: float, msg: str, stage: Optional[str] = None) -> None:
        job.progress = float(frac)
        event: Dict[str, Any] = {"fraction": float(frac), "message": msg}
        if stage:
            event["stage"] = stage
            event["status"] = msg
            event["detail"] = details.get(stage, "")
        asyncio.run_coroutine_threadsafe(job.queue.put(event), loop)

    def _work() -> None:
        src = _separation_input(sess)
        stems, info = stems_mod.separate(
            src, sess.sr, tier=tier.key, progress=_progress,
            digest=sess.digest or None)
        # Clamp stems to the preview cap like the main samples.
        for k in list(stems):
            stems[k] = clamp_samples_for_preview(stems[k], sess.sr)
        # The residual is a stem of its own, so the unchanged mix nulls
        # against the original exactly (docs/PLAN.md, decision 2).
        _progress(0.95, "Checking the split", "null")
        residual, null_db = stems_mod.add_residual(stems, sess.samples)
        stems[stems_mod.RESIDUAL] = residual
        info.update(stems_mod.measure_stems(
            stems, sess.samples, sess.sr, null_db=null_db))
        info["name"] = sess.original_name
        sess.stems = stems
        sess.stems_info = info
        # A new stem set invalidates every cached per-stem fx render.
        sess._remix_fx_cache = {}
        job.metrics = {k: v for k, v in info.items()
                       if k not in ("stems", "mix_peaks")}

    async def _run() -> None:
        job.status = "running"
        try:
            await loop.run_in_executor(None, _work)
            job.status = "done"
            job.progress = 1.0
            await job.queue.put({"fraction": 1.0, "done": True})
        except Exception as e:  # noqa: BLE001
            job.status = "error"
            job.error = str(e)
            await job.queue.put({"error": str(e), "done": True})

    asyncio.create_task(_run())
    return JSONResponse({"job_id": job.id})


@app.post("/api/stems/export")
async def api_stems_export(payload: Dict[str, Any]) -> JSONResponse:
    """Download the stems as a ZIP of 24-bit WAVs at the session's rate.

    `processed: false` (default) writes them as separated, residual
    included, so they sum back to the original. `processed: true`
    writes each stem through its strip (gain, effects; muted or
    un-soloed stems are left out), so a DAW session starts from the mix
    built here. Returns a job_id; the ZIP comes from /api/result.
    """
    sid = payload.get("session_id") or ""
    sess = PREVIEW_STORE.get(sid)
    if sess is None:
        raise HTTPException(404, "Unknown session_id")
    if not sess.stems:
        raise HTTPException(409, "Stems not separated yet")
    processed = bool(payload.get("processed"))
    names = _stem_order(sess)
    settings = remix_settings_from_json(payload.get("stems") or {}, names)

    job = JOB_STORE.create(output_ext=".zip")
    job.source_stem = (Path(sess.original_name).stem or "audio") + "_stems"
    job.preset_name = "mixed" if processed else str(
        (sess.stems_info or {}).get("model") or "stems")
    loop = asyncio.get_running_loop()
    cb = _threadsafe_progress_pusher(job, loop)
    stage_cb = getattr(cb, "stage", None)

    def _stage(key: str, label: str, detail: str = "") -> None:
        if stage_cb:
            stage_cb(key, label, detail)

    def _work() -> None:
        sr = sess.sr
        cb(0.05)
        stems = {n: sess.stems[n] for n in names}
        if processed:
            _stage("mix", "Rendering each stem", "gain, effects and mutes from the mixer")
            stems = {n: v for n, v in stems.items() if not settings[n].mute}
            if not stems:
                raise RuntimeError("Every stem is muted — nothing to export")
            out = render_stems(stems, sr, settings)
        else:
            _stage("mix", "Collecting the stems", "as separated, residual included")
            n = min(v.shape[0] for v in stems.values())
            out = {k: v[:n] for k, v in stems.items()}
        cb(0.25)
        safe = _safe_filename_stem(Path(sess.original_name).stem) or "audio"
        zip_path = os.path.join(job.workdir, "processed.zip")
        _stage("export", "Packing the ZIP", f"{len(out)} × 24-bit WAV · {sr} Hz")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
            for i, (name, arr) in enumerate(out.items()):
                tmp = os.path.join(job.workdir, f"{name}.wav")
                save_audio(tmp, arr, sr, subtype="PCM_24")
                zf.write(tmp, arcname=f"{safe}_{name}.wav")
                os.unlink(tmp)
                cb(0.25 + 0.7 * (i + 1) / max(1, len(out)))
        job.processed_path = zip_path
        first = next(iter(out.values()))
        job.metrics = {
            "stems": list(out), "processed": processed, "sample_rate": sr,
            "bit_depth": 24, "size_bytes": os.path.getsize(zip_path),
            "duration_s": float(first.shape[0] / sr),
        }
        cb(1.0)

    async def _run() -> None:
        job.status = "running"
        try:
            await loop.run_in_executor(None, _work)
            job.status = "done"
            await job.queue.put({"fraction": 1.0, "done": True})
        except Exception as e:  # noqa: BLE001
            job.status = "error"
            job.error = str(e)
            await job.queue.put({"error": str(e), "done": True})

    asyncio.create_task(_run())
    return JSONResponse({"job_id": job.id})


@app.post("/api/remix/preview")
async def api_remix_preview(payload: Dict[str, Any]) -> Response:
    """Render a remix slice: per-stem effects + sum over the loop window,
    optionally through the mastering chain so preview matches export.

    Response format matches /api/preview but with a single WAV:
        [u32 json_len][json meta][wav remix]
    Meta includes per-slice loudness of the original mix and the remix so
    the client can loudness-match A/B.
    """
    sid = payload.get("session_id") or ""
    sess = PREVIEW_STORE.get(sid)
    if sess is None:
        raise HTTPException(404, "Unknown session_id")
    if not sess.stems:
        raise HTTPException(409, "Stems not separated yet")

    try:
        start_s = float(payload.get("start_s", 0.0))
        end_s = float(payload.get("end_s", min(10.0, sess.duration_s)))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, f"Invalid start_s/end_s: {e}")

    order = _stem_order(sess)
    settings = remix_settings_from_json(payload.get("stems") or {}, order)
    master_json = payload.get("mastering") or {}
    mp = master_params_from_json(master_json)
    # No mastering block in the payload = old client = no mastering
    # (master_params_from_json defaults `enabled` to True).
    use_master = bool(master_json) and mp.enabled

    def _render() -> Dict[str, Any]:
        sr = sess.sr
        # Per-stem fx cache: the expensive rack render is keyed by
        # (window, stem, fx settings) and reused across requests, so
        # mute/solo/gain toggles and single-stem edits re-render only
        # what actually changed. Mastering runs on the summed slice after
        # this cache, so master-setting changes never invalidate it.
        cache: Dict[Any, np.ndarray] = getattr(sess, "_remix_fx_cache", None)
        if cache is None:
            cache = {}
            sess._remix_fx_cache = cache

        out = None
        head_pad = audible_len = 0
        for name in order:
            arr = sess.stems.get(name)
            if arr is None:
                continue
            s = settings[name]
            block, head_pad, audible_len = extract_preview_block(
                arr, sr, start_s, end_s, extra_margin_s=0.0)
            if s.mute:
                continue  # skip the rack entirely for muted stems
            key = (round(start_s, 3), round(end_s, 3), name, fx_signature(s))
            y = cache.get(key)
            if y is None:
                y = apply_fx_only(block, sr, s)
                cache[key] = y
                while len(cache) > 24:
                    cache.pop(next(iter(cache)))
            y = apply_gain_mute(y, s)
            out = y if out is None else out + y

        # Original-mix slice loudness for client-side A/B matching.
        orig_block, o_pad, o_len = extract_preview_block(
            sess.samples, sr, start_s, end_s, extra_margin_s=0.0)
        orig_audible = orig_block[o_pad:o_pad + o_len, :]
        lufs_original = _slice_loudness_db(orig_audible, sr)

        if out is None:  # everything muted — ship silence
            n = int(max(1, round((end_s - start_s) * sr)))
            return {
                "wav": encode_wav_bytes(
                    np.zeros((n, sess.channels), dtype=np.float32), sr),
                "lufs_original": lufs_original,
                "lufs_remix": -120.0,
                "mastered": False,
            }

        if use_master:
            # Master the padded block (limiter/HP warm up in the
            # discarded preroll), then trim to the audible window. The
            # whole-file reference keeps the slice at the level the full
            # render will have instead of normalising it on its own.
            out, _ = master(out, sr, mp,
                            loudness_ref=_master_loudness_ref(sess, orig_block, sr))
        else:
            peak = float(np.max(np.abs(out)))
            if peak > 0.999:
                out = out / peak * 0.999
        y = trim_processed_preview(out, head_pad, audible_len)
        return {
            "wav": encode_wav_bytes(y, sr),
            "lufs_original": lufs_original,
            "lufs_remix": _slice_loudness_db(y, sr),
            "mastered": use_master,
        }

    loop = asyncio.get_running_loop()
    t0 = time.time()
    try:
        result = await loop.run_in_executor(None, _render)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Remix preview failed: {e}")
    wav = result["wav"]

    meta = json.dumps({
        "sample_rate": sess.sr,
        "render_ms": int((time.time() - t0) * 1000),
        "start_s": start_s,
        "end_s": end_s,
        "lufs_original": result["lufs_original"],
        "lufs_remix": result["lufs_remix"],
        "mastered": result["mastered"],
    }).encode("utf-8")
    return Response(
        content=b"".join([struct.pack("<I", len(meta)), meta, wav]),
        media_type="application/octet-stream")


@app.post("/api/remix/render")
async def api_remix_render(payload: Dict[str, Any]) -> JSONResponse:
    """Render the full-length remix as a download job.

    Optional stages after the stem sum, mirroring the single-file flow:
      * `cleaning: {"preset": "auto" | "<preset_key>" | "off"}` — run the
        summed remix through the full safe pipeline (tone curve, band
        split, M/S artifact cleaning). "auto" analyzes the remix itself,
        because Demucs redistributes the source artifacts into the stems
        and the effects rack can reshape them.
      * `mastering: {...}` — the standard mastering chain, inside the
        pipeline when cleaning is on, standalone otherwise.
    """
    sid = payload.get("session_id") or ""
    sess = PREVIEW_STORE.get(sid)
    if sess is None:
        raise HTTPException(404, "Unknown session_id")
    if not sess.stems:
        raise HTTPException(409, "Stems not separated yet")

    order = _stem_order(sess)
    settings = remix_settings_from_json(payload.get("stems") or {}, order)
    mp = master_params_from_json(payload.get("mastering") or {})
    output_format = (payload.get("output_format") or "wav").lstrip(".").lower()
    try:
        out_spec = resolve_output_format(output_format)
    except ValueError as e:
        raise HTTPException(400, str(e))
    output_ext = out_spec["ext"]
    if (payload.get("mastering") or {}).get("ceiling_dbtp") is None:
        mp.ceiling_dbtp = get_export_ceiling_dbtp(output_ext)

    clean_choice = str((payload.get("cleaning") or {}).get("preset")
                       or "off").lower()
    do_clean = clean_choice not in ("off", "none", "")
    if do_clean and clean_choice != "auto":
        try:
            get_preset(clean_choice)
        except KeyError:
            raise HTTPException(400, f"Unknown cleaning preset: {clean_choice}")

    job = JOB_STORE.create(output_ext=output_ext)
    job.source_stem = (Path(sess.original_name).stem or "audio") + "_remix"
    job.preset_name = "remix"
    loop = asyncio.get_running_loop()
    cb = _threadsafe_progress_pusher(job, loop)
    stage_cb = getattr(cb, "stage", None)

    def _stage(key: str, label: str, detail: str = "") -> None:
        if stage_cb:
            stage_cb(key, label, detail)

    def _work() -> None:
        sr = sess.sr
        cb(0.05)
        _stage("mix", "Mixing the stems", "each stem's effects, then the sum")
        y = render_remix({n: sess.stems[n] for n in order}, sr, settings)
        # A release copy runs the rest of the chain at the delivery rate.
        y, sr = resample_to(y, sr, out_spec.get("sr"))
        cb(0.15)

        cleaning_info: Dict[str, Any] = {"enabled": do_clean}
        m_report: Dict[str, Any] = {"enabled": False}
        if do_clean:
            preset_name = clean_choice
            if preset_name == "auto":
                from .probe import suggest_preset
                _stage("analyze", "Picking the cleanup preset", "listening to the summed remix")
                tmp = os.path.join(job.workdir, "remix_sum.wav")
                save_audio(tmp, y, sr)
                sug = suggest_preset(tmp)
                preset_name = sug["preset"]
                ranked = sug.get("ranked") or []
                cleaning_info["detected_confidence"] = float(
                    ranked[0].get("confidence", 0.0)) if ranked else 0.0
                cleaning_info["detected_strength"] = float(
                    sug.get("strength") or 1.0)
            cleaning_info["preset"] = preset_name
            cleaning_info["label"] = label_for(preset_name)
            p = get_preset(preset_name)
            # Auto mode: the analysis chose the strength too; scale the
            # preset through the standard hook before cleaning.
            auto_strength = cleaning_info.get("detected_strength")
            if auto_strength is not None and abs(auto_strength - 1.0) > 1e-6:
                apply_preset_strength(p, float(auto_strength))
            # Deterministic repairs on the summed remix: fixed lines and
            # the bandwidth cutoff, measured on what is about to be cleaned.
            remix_plan = plan_from_lines(scan_fixed_lines(y, sr), sr)
            p.cutoff_hz = float(estimate_cutoff_hz(y, sr).get("cutoff_hz") or 0.0)
            cleaning_info["repair_notches"] = len(remix_plan.notches)
            cb(0.2)
            y, _removed, rep = clean_and_master(
                y, sr, p,
                repair=remix_plan,
                master_params=mp if mp.enabled else None,
                progress_callback=lambda f: cb(0.2 + 0.7 * f),
                stage_callback=stage_cb,
            )
            m_report = rep.get("mastering", {"enabled": False})
        elif mp.enabled:
            _stage("master", "Mastering",
                   f"level to {float(mp.target_lufs):g} LUFS · peak shaper · true-peak limiter")
            y, m_report = master(y, sr, mp)
        cb(0.9)

        processed = os.path.join(job.workdir, f"processed{job.output_ext}")
        _stage("export", "Writing the file", job.output_ext.lstrip(".").upper())
        save_audio(processed, y, sr, subtype=out_spec["subtype"],
                   dither=bool(out_spec.get("dither")))
        job.processed_path = processed
        if m_report.get("enabled"):
            out_lufs = _finite_or_none((m_report.get("after") or {}).get("lufs_i"))
        else:
            out_lufs = _finite_or_none(measure_loudness(y, sr).get("lufs_i"))
        job.metrics = {
            "sample_rate": sr,
            "channels": int(y.shape[1]),
            "duration_s": float(y.shape[0] / sr),
            "input": measure(sess.samples),
            "output": measure(y),
            "cleaning": cleaning_info,
            "mastering": m_report,
            "loudness": {"output_lufs_i": out_lufs},
        }
        cb(1.0)

    async def _run() -> None:
        job.status = "running"
        try:
            await loop.run_in_executor(None, _work)
            job.status = "done"
            await job.queue.put({"fraction": 1.0, "done": True})
        except Exception as e:  # noqa: BLE001
            job.status = "error"
            job.error = str(e)
            await job.queue.put({"error": str(e), "done": True})

    asyncio.create_task(_run())
    return JSONResponse({"job_id": job.id})


# ───────────────────────────────────────────────────────────────────────────
# SSE helper
# ───────────────────────────────────────────────────────────────────────────

def _sse_event(data: Dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"
