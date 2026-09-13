"""
server.py — Shimmer by The Treq: FastAPI backend.

The engine's routes live in shimmer/api (docs/API.md): upload, envelope,
process, progress, cancel, metrics, result, preview and rules. They are
included first, so they answer before anything here. This file serves the
rest, until each moves:

    GET  /                        the page
    GET  /api/presets             the 1.x preset list (retires with the
                                  preset browser)
    POST /api/chain               the Signal Chain view (1.x stages)
    POST /api/suggest             Analyze: findings, fixed tones, tone plan
    POST /api/tone, GET /api/tone/families
                                  Suggested EQ
    POST /api/batch               a folder, as server-sent events
    GET/POST /api/settings, POST /api/browse-folder, POST /api/reveal
    POST /api/project/{digest}    save a Remix project
    /api/stems/*, /api/remix/*    separation, the Remix mixer and its export
    /api/dev/*                    the listening bench and reference library

CPU-heavy work runs on a thread executor so the event loop stays responsive.
"""

from __future__ import annotations

from . import _winfix  # noqa: F401  # must precede scipy/numpy import on Windows

import asyncio
import glob
import json
import math
import os
import struct
import zipfile
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import (
    FileResponse, JSONResponse, StreamingResponse, HTMLResponse, Response,
)
from fastapi.staticfiles import StaticFiles

from .audio_io import save_audio, measure, encode_wav_bytes
from .release import summary as release_summary
from .dsp import as_2d
from .eq import EqParams, eq_params_from_json
from .jobs import JOB_STORE, Job
from .params import Params, apply_preset_strength, MasterParams
from .mastering import (
    master, master_params_from_json, measure_loudness, get_export_ceiling_dbtp,
)
from .presets import PRESET_NAMES, get_preset, describe_preset, label_for, is_visible
from .core import family_list, moves_to_eq_payload, normalize_family
from .tags import read_tags
from .preview_store import PREVIEW_STORE, clamp_samples_for_preview
from .settings_store import load_settings, save_settings
from . import stems as stems_mod
from .stem_effects import (
    apply_fx_only, apply_gain_mute, fx_signature,
    remix_settings_from_json, render_remix, render_stems,
)
from .projects_store import save_project


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
from . import __version__ as _shimmer_version  # noqa: E402
from .api import render as _api_render  # noqa: E402
from .api import rules as _api_rules  # noqa: E402
from .api import sessions as _api_sessions  # noqa: E402

_api_render.configure(_shimmer_version)
app.include_router(_api_rules.router)
app.include_router(_api_sessions.router)
app.include_router(_api_render.router)


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


def _tone_plan_for(x: np.ndarray, sr: int, family: str, s: Any,
                   repair_dict: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Suggested EQ on the new engine (core.tone_plan): judged after the
    fixes and, with mastering on, after the mastering tone curve, the way
    render() runs, so the plan never corrects what those already handle.
    `repair_dict` is the screen's notch list, when it sent one."""
    from . import core as _c
    notches = None
    if isinstance(repair_dict, dict) and isinstance(repair_dict.get("notches"), list):
        notches = _c.NotchPlan.from_dict(repair_dict, sr).notches
    return _c.tone_plan(_c.Source.from_array(x, sr), s, family=normalize_family(family),
                        notches=notches)


def _tone_settings(preset: Optional[str], mastering_json: Dict[str, Any]) -> Any:
    """The settings a tone plan is judged with: the card an old preset turns
    on, and mastering only when the screen sent a mastering block that is
    on (1.x's rule: no block, no mastering)."""
    return _api_render.settings_from_request(
        {"preset": preset, "mastering": mastering_json or {"enabled": False}})


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
# Analyze
# ───────────────────────────────────────────────────────────────────────────

@app.post("/api/suggest")
async def api_suggest(file: UploadFile = File(...),
                      tone_family: str = Form("neutral"),
                      mastering: str = Form(""),
                      tone: bool = Form(True),
                      overrides: str = Form("")) -> JSONResponse:
    """Analyze, on the new engine: loudness and spectrum, the findings for
    the "What do you hear?" card, fixed tones (the notch plan), where the
    top end is busiest, the source file's tags, and the Tone plan
    (suggested EQ) for the current mastering settings.

    The 1.x preset trial (19 presets on the busiest part) is gone: the cards
    replace presets. The preset fields stay in the answer, empty, until the
    screen stops reading them (docs/API.md §0)."""
    import dataclasses as _dc
    import tempfile

    from . import core as _core
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
        t0 = time.time()
        x, sr = await loop.run_in_executor(None, _core.load_audio, tmp_path)
        analysis = await loop.run_in_executor(None, _core.analyze_track, x, sr)
        lines = await loop.run_in_executor(None, _core.scan_fixed_lines, x, sr)
        found = await loop.run_in_executor(None, _core.findings, _core.Source.from_array(x, sr))
        timeline = await loop.run_in_executor(None, _core.activity_timeline, x, sr)
        result = {
            "findings": [_dc.asdict(f) for f in found],
            "repair_plan": _core.plan_from_lines(lines, sr).as_dict(),
            "timeline": timeline,
            "evidence": {"cutoff_hz": analysis.get("cutoff_hz")},
            "notes": [],
            # 1.x preset fields, empty (see the docstring).
            "preset": "generic", "strength": 1.0, "ranked": [], "follow_up": None,
        }
        result["analysis"] = analysis
        result["source_tags"] = await loop.run_in_executor(None, read_tags, tmp_path)
        result["metrics"] = {"sample_rate": sr, "elapsed_ms": int((time.time() - t0) * 1000)}
        if tone:
            s_tone = _tone_settings(None, _parse_json_form(mastering))
            try:
                result["tone_plan"] = await loop.run_in_executor(
                    None, _tone_plan_for, x, sr, tone_family, s_tone,
                    result.get("repair_plan"))
            except Exception as e:  # noqa: BLE001
                result["tone_plan"] = {"error": str(e)}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return JSONResponse(result)


def _parse_json_form(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


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
    """Re-plan Suggested EQ for a file with the current family and mastering
    settings (family picker, pass 2 of a two-pass run), on the new engine.
    `preset` turns on its card (the transition rule); `preset_strength` and
    `overrides` tuned 1.x's cleaning and are ignored."""
    import tempfile

    from . import core as _core
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
        x, sr = await loop.run_in_executor(None, _core.load_audio, tmp_path)
        analysis = await loop.run_in_executor(None, _core.analyze_track, x, sr)
        source_tags = await loop.run_in_executor(None, read_tags, tmp_path)
        # No notch list from the screen: the engine scans for fixed tones.
        plan = await loop.run_in_executor(
            None, _tone_plan_for, x, sr, tone_family,
            _tone_settings(preset, _parse_json_form(mastering)),
            _parse_json_form(repair) or None)
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

from functools import partial as _partial  # noqa: E402

from . import core as _core  # noqa: E402


@app.post("/api/batch")
async def api_batch(payload: Dict[str, Any]) -> StreamingResponse:
    """A folder through the new engine (docs/API.md §5). Every file is
    rendered with shimmer.core.render() and written with core.export(), with
    the Master tab's tags, silence trim and release check
    (shimmer.api.render.export_file). The 1.x fields still arrive and map
    through the transition rule (API.md §0). `auto_detect` no longer tries
    presets: each file's findings are reported instead."""
    input_folder = (payload.get("input_folder") or "").strip()
    output_folder = (payload.get("output_folder") or "").strip()
    raw_format = payload.get("output_format") or "wav"
    try:
        fmt = _core.catalog.output_format(raw_format)
    except KeyError:
        raise HTTPException(400, f"Unsupported output format: {raw_format}")
    preset = payload.get("preset") or "generic"
    auto_detect = bool(payload.get("auto_detect", False))
    params: Dict[str, Any] = {
        "preset": preset,
        "mastering": payload.get("mastering") or {},
        "eq": payload.get("eq") or {},
        "repair": {"enabled": bool(payload.get("static_repair", True))},
    }
    for key in ("fixes", "auto"):
        if key in payload:
            params[key] = payload[key]
    s = _api_render.settings_from_request(
        params, output_format=fmt.key,
        preserve_volume=bool(payload.get("preserve_volume", True)),
        trim_silence=bool(payload.get("trim_silence", False)))
    auto_eq = bool(payload.get("auto_eq", False))
    tone_family = normalize_family(payload.get("tone_family"))
    tags_req = payload.get("tags") if isinstance(payload.get("tags"), dict) else None
    # Album mode: one gain for the whole folder. Only meaningful with
    # mastering on.
    album_mode = bool(payload.get("album_mode", False)) and s.mastering
    target_lufs = _core.catalog.loudness_target(s.loudness_target).lufs

    if not input_folder or not os.path.isdir(input_folder):
        raise HTTPException(400, f"Input folder not found: {input_folder}")
    if not output_folder:
        output_folder = input_folder.rstrip("/\\") + "_deshimmered"
    os.makedirs(output_folder, exist_ok=True)

    patterns = ["*.wav", "*.WAV", "*.mp3", "*.MP3",
                "*.flac", "*.FLAC", "*.ogg", "*.m4a"]
    files = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(input_folder, pat)))
    files = sorted(set(files))

    def dst_for(name: str) -> str:
        return os.path.join(output_folder, os.path.splitext(name)[0] + fmt.ext)

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
            # Two passes. Pass 1 measures every track just before mastering's
            # gain; the album's gain is then decided from the loudest; pass 2
            # renders each track with that one gain. Nothing is parked on
            # disk: pass 2 renders from the original file again.
            infos: List[Dict[str, Any]] = []
            yield _sse_event({
                "type": "phase", "phase": "clean", "total": len(files),
                "message": "Pass 1 of 2: measuring every track; mastering waits until the album's level is known",
            })
            for i, src in enumerate(files):
                name = os.path.basename(src)
                yield _sse_event({"type": "file_start", "phase": "clean",
                                  "index": i, "name": name})
                try:
                    s_file, eq_info = await loop.run_in_executor(
                        None, _batch_settings_for, src, s, auto_eq, tone_family)
                    info = await loop.run_in_executor(None, _api_render.measure_file, src, s_file)
                    info.update(eq_info)
                    info.update({"index": i, "name": name, "src": src, "settings": s_file})
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
                        "findings": info.get("findings"),
                    })
                except Exception as e:  # noqa: BLE001
                    yield _sse_event({"type": "file_error", "phase": "clean",
                                      "index": i, "name": name, "error": str(e)})
            album = _album_gain(infos, float(target_lufs))
            yield _sse_event({"type": "album", "target_lufs": float(target_lufs),
                              "tracks": len(infos), **album})
            if not infos:
                yield _sse_event({"type": "end", "total": len(files),
                                  "message": "No track could be measured"})
                return
            gain = float(album["gain_db"])
            yield _sse_event({
                "type": "phase", "phase": "master", "total": len(infos),
                "message": "Pass 2 of 2: mastering every track with the album's gain",
            })
            for info in infos:
                i, name, src = info["index"], info["name"], info["src"]
                yield _sse_event({"type": "file_start", "phase": "master",
                                  "index": i, "name": name})
                clean = info.get("lufs_clean")
                # This track's level under album mode: its level before
                # mastering plus the album's one gain. The release check
                # grades against that, since sitting under the target is
                # the point.
                expected = float(clean) + gain if clean is not None else None
                try:
                    r = await loop.run_in_executor(None, _partial(
                        _api_render.export_file, src, info["settings"], dst_for(name),
                        tags_req=tags_req, gain_db=gain, expected_lufs=expected,
                        with_findings=False))
                    yield _sse_event({
                        "type": "file_done", "phase": "master",
                        "index": i, "name": name,
                        "duration_s": r["duration_s"],
                        "tags_written": r.get("tags_written"),
                        "trim": r.get("trim"),
                        "peak_in_db": r["input"]["peak_dbfs"],
                        "peak_out_db": r["output"]["peak_dbfs"],
                        "lufs_out": r.get("lufs_out"),
                        "true_peak_out": r.get("true_peak_out"),
                        "limiter_gr_db": r.get("limiter_gr_db"),
                        "gain_db": gain,
                        "release": release_summary(r.get("release")),
                    })
                except Exception as e:  # noqa: BLE001
                    yield _sse_event({"type": "file_error", "phase": "master",
                                      "index": i, "name": name, "error": str(e)})
            yield _sse_event({"type": "end", "total": len(files)})
            return

        for i, src in enumerate(files):
            name = os.path.basename(src)
            yield _sse_event({"type": "file_start", "index": i, "name": name})
            try:
                s_file, eq_info = await loop.run_in_executor(
                    None, _batch_settings_for, src, s, auto_eq, tone_family)
                r = await loop.run_in_executor(None, _partial(
                    _api_render.export_file, src, s_file, dst_for(name), tags_req=tags_req))
                yield _sse_event({
                    "type": "file_done", "index": i, "name": name,
                    "duration_s": r["duration_s"],
                    "tone_moves": eq_info.get("tone_moves"),
                    "tone_summary": eq_info.get("tone_summary"),
                    "tags_written": r.get("tags_written"),
                    "trim": r.get("trim"),
                    "peak_in_db": r["input"]["peak_dbfs"],
                    "peak_out_db": r["output"]["peak_dbfs"],
                    "findings": r.get("findings"),
                    # Per-file verification when mastering ran.
                    "lufs_out": r.get("lufs_out"),
                    "true_peak_out": r.get("true_peak_out"),
                    "limiter_gr_db": r.get("limiter_gr_db"),
                    "release": release_summary(r.get("release")),
                })
            except Exception as e:  # noqa: BLE001
                yield _sse_event({
                    "type": "file_error", "index": i, "name": name,
                    "error": str(e),
                })
        yield _sse_event({"type": "end", "total": len(files)})

    return StreamingResponse(stream(), media_type="text/event-stream")


def _batch_settings_for(src: str, s: Any, auto_eq: bool,
                        tone_family: str) -> Tuple[Any, Dict[str, Any]]:
    """One file's settings. With Suggested EQ on, the engine's tone plan
    for this file (judged after its fixes and the mastering tone curve)
    adds its moves after the user's EQ bands."""
    if not auto_eq:
        return s, {}
    x, sr = _core.load_audio(src)
    plan = _tone_plan_for(x, sr, tone_family, s)
    moves = plan.get("moves") or []
    info = {"tone_moves": len(moves), "tone_summary": plan.get("summary", "")}
    if moves:
        base = list(s.eq_bands) if s.eq_enabled else []
        extra = moves_to_eq_payload(moves)["bands"]
        s = s.replace(eq_enabled=True, eq_bands=tuple(base) + tuple(extra))
    return s, info


# ── Album mode ───────────────────────────────────────────────────────────
# A folder mastered as one record. Normalising each track on its own
# flattens the album: the quiet song ends up as loud as the single.
# Album mode measures every track first (pass 1), decides one gain from the
# loudest track, and masters each track with that gain (pass 2), so the
# tracks keep their distance and no track is limited harder than it would
# be on its own.

def _album_gain(infos: List[Dict[str, Any]], target_lufs: float) -> Dict[str, Any]:
    """One gain for the whole album: the loudest track lands on the target
    and every other track keeps its distance below it. Also reports the
    album's overall loudness (the duration-weighted energy mean of the
    tracks' integrated loudness, close to a gated measurement of the record
    played end to end) and the spread."""
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


# ───────────────────────────────────────────────────────────────────────────
# Projects — per-track persisted work (keyed by file content digest)
# ───────────────────────────────────────────────────────────────────────────


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
        sess._remix_full = None
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


# ── The whole remix, worked out in the background (Option A) ────────────
# The preview can only match the export if it is rendered from the whole
# remix: the tone curve, the fixed-tone scan and the loudness gain all come
# from the whole song. Mixing a 4-minute song with vocal effects takes about
# 9 s, so the loop keeps playing from its own mix (marked approximate) while
# the whole mix is built here; once it lands, the preview is render() on a
# window of it, which is the export by construction (REBUILD-TRACKER).

import threading as _threading  # noqa: E402


def _remix_settings(payload: Dict[str, Any], fmt_key: str, mastering_off_when_missing: bool) -> Any:
    """The Remix settings, the same for its preview and its export. The
    cleanup menu maps through the transition rule: "off" turns every fix
    off, "auto" applies what the remix shows, a preset turns on its card."""
    choice = str((payload.get("cleaning") or {}).get("preset") or "off").lower()
    do_clean = choice not in ("off", "none", "")
    master = payload.get("mastering") or ({"enabled": False} if mastering_off_when_missing else {})
    return _api_render.settings_from_request(
        {"preset": choice if do_clean and choice != "auto" else None,
         "mastering": master, "repair": {"enabled": do_clean}},
        output_format=fmt_key, preserve_volume=True, trim_silence=False)


def _mix_key(sess, order: List[str], stem_settings: Dict[str, Any]) -> Tuple:
    """Everything the summed remix depends on: each lane's effects, gain,
    pan and mute."""
    return tuple((n, fx_signature(stem_settings[n]), round(float(stem_settings[n].gain_db), 3),
                  round(float(stem_settings[n].pan), 3), bool(stem_settings[n].mute))
                 for n in order if n in (sess.stems or {}))


class _FullMix:
    """One session's whole remix for the latest lane settings, built on a
    background thread. Each lane's full-length effects are kept, so a gain,
    pan or mute change only sums again."""

    def __init__(self) -> None:
        self._lock = _threading.Lock()
        self._key: Optional[Tuple] = None
        self._source = None
        self._want = None
        self._busy = False
        self._failed: Optional[Tuple] = None
        self._fx: Dict[str, Tuple[str, np.ndarray]] = {}

    def get(self, key: Tuple):
        with self._lock:
            return self._source if self._key == key else None

    def building(self, key: Tuple) -> bool:
        """True when asking again gives (or will soon give) the exact
        preview: the whole mix is on its way, or has just landed. False
        only when the build failed for these lanes."""
        with self._lock:
            return self._failed != key and (
                self._key == key or self._busy or self._want is not None)

    def request(self, key: Tuple, stems: Dict[str, np.ndarray], stem_settings: Dict[str, Any],
                sr: int, s: Any) -> None:
        with self._lock:
            if self._key == key or self._failed == key:
                return
            self._want = (key, stems, stem_settings, sr, s)
            if self._busy:
                return
            self._busy = True
        _threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while True:
            with self._lock:
                job, self._want = self._want, None
                if job is None:
                    self._busy = False
                    return
            key, stems, stem_settings, sr, s = job
            try:
                src = _core.Source.from_array(self._mix(stems, stem_settings, sr), sr)
                # The whole-song work (fixed-tone scan, tone curve, gain), so
                # the first exact preview is quick.
                _core.render(src, s, (0.0, 0.1))
                failed = None
            except Exception as e:  # noqa: BLE001
                # The preview stays approximate for these lanes; say why.
                import logging
                logging.getLogger("shimmer.remix").exception("whole remix failed")
                self.error = f"{type(e).__name__}: {e}"
                src, failed = None, key
            with self._lock:
                if src is not None:
                    self._key, self._source = key, src
                self._failed = failed

    def _mix(self, stems: Dict[str, np.ndarray], stem_settings: Dict[str, Any],
             sr: int) -> np.ndarray:
        """stem_effects.render_remix, sample for sample, with each lane's
        full-length effects kept between calls."""
        from .stem_effects import StemSettings, _mix_order
        n = min(v.shape[0] for v in stems.values())
        out = None
        for name in _mix_order(stems):
            st = stem_settings.get(name, StemSettings())
            x = as_2d(np.asarray(stems[name][:n], dtype=np.float32))
            if st.mute:
                y = np.zeros_like(x)
            else:
                sig = fx_signature(st)
                hit = self._fx.get(name)
                if hit is None or hit[0] != sig:
                    hit = (sig, apply_fx_only(x, sr, st))
                    self._fx[name] = hit
                y = apply_gain_mute(hit[1], st)
            out = y if out is None else out + y
        peak = float(np.max(np.abs(out)))
        if peak > 0.999:
            out = out / peak * 0.999
        return out.astype(np.float32)


def _full_mix(sess) -> _FullMix:
    fm = getattr(sess, "_remix_full", None)
    if fm is None:
        fm = _FullMix()
        sess._remix_full = fm
    return fm


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
    try:
        fmt_key = _core.catalog.output_format(payload.get("output_format") or "wav").key
    except KeyError:
        fmt_key = "wav"
    s_exact = _remix_settings(payload, fmt_key, mastering_off_when_missing=True)
    full = _full_mix(sess)
    mix_key = _mix_key(sess, order, settings)

    def _render() -> Dict[str, Any]:
        sr = sess.sr
        live = [n for n in order if n in sess.stems and not settings[n].mute]
        ready = full.get(mix_key) if live else None
        if live and ready is None:
            full.request(mix_key, {n: sess.stems[n] for n in order}, settings, sr, s_exact)
        if ready is not None:
            # The export on a window: exact, level included.
            r = _core.render(ready, s_exact, (start_s, end_s))
            orig_block, o_pad, o_len = extract_preview_block(
                sess.samples, sr, start_s, end_s, extra_margin_s=0.0)
            return {
                "wav": encode_wav_bytes(r.audio, r.sr),
                "lufs_original": _slice_loudness_db(orig_block[o_pad:o_pad + o_len, :], sr),
                "lufs_remix": _slice_loudness_db(r.audio, r.sr),
                "mastered": bool(s_exact.mastering),
                "exact": True, "building": False, "sample_rate": r.sr,
            }
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
                "exact": False, "building": False,
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
            # Approximate: the loop's own mix, its level guessed from the
            # original, until the whole mix lands.
            "exact": False, "building": full.building(mix_key),
        }

    loop = asyncio.get_running_loop()
    t0 = time.time()
    try:
        result = await loop.run_in_executor(None, _render)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"Remix preview failed: {e}")
    wav = result["wav"]

    meta = json.dumps({
        "sample_rate": result.get("sample_rate", sess.sr),
        "render_ms": int((time.time() - t0) * 1000),
        "start_s": start_s,
        "end_s": end_s,
        "lufs_original": result["lufs_original"],
        "lufs_remix": result["lufs_remix"],
        "mastered": result["mastered"],
        "exact": result["exact"],
        "building": result["building"],
    }).encode("utf-8")
    return Response(
        content=b"".join([struct.pack("<I", len(meta)), meta, wav]),
        media_type="application/octet-stream")


from .api import jobs as _api_jobs  # noqa: E402


@app.post("/api/remix/render")
async def api_remix_render(payload: Dict[str, Any]) -> JSONResponse:
    """Render the full-length remix as a download job, on the new engine:
    each stem's effects and the sum (stem_effects), then shimmer.core.render()
    and core.export(), the Master tab's own path.

    `cleaning: {"preset": "off" | "auto" | "<1.x preset>"}` maps through the
    transition rule (docs/API.md §0): "off" turns every fix off, "auto"
    applies what the remix itself shows (Fixed tones today), and a preset
    turns on its card. `mastering: {...}` is the Master tab's mastering.
    The job runs on the job runner, so it can be cancelled.
    """
    sid = payload.get("session_id") or ""
    sess = PREVIEW_STORE.get(sid)
    if sess is None:
        raise HTTPException(404, "Unknown session_id")
    if not sess.stems:
        raise HTTPException(409, "Stems not separated yet")

    order = _stem_order(sess)
    stem_settings = remix_settings_from_json(payload.get("stems") or {}, order)
    raw_format = payload.get("output_format") or "wav"
    try:
        fmt = _core.catalog.output_format(raw_format)
    except KeyError:
        raise HTTPException(400, f"Unsupported output format: {raw_format}")

    clean_choice = str((payload.get("cleaning") or {}).get("preset") or "off").lower()
    do_clean = clean_choice not in ("off", "none", "")
    if do_clean and clean_choice != "auto" and not _known_preset(clean_choice):
        raise HTTPException(400, f"Unknown cleaning preset: {clean_choice}")
    s = _remix_settings(payload, fmt.key, mastering_off_when_missing=False)

    job = JOB_STORE.create(output_ext=fmt.ext)
    job.source_stem = (Path(sess.original_name).stem or "audio") + "_remix"
    job.preset_name = "remix"
    stems = {n: sess.stems[n] for n in order}
    # The upload the remix came from: its tags seed the export's, and the
    # export must never be written over it.
    original_path = sess.original_path if os.path.isfile(sess.original_path or "") else None
    # The whole mix the preview already built for these lanes, if any.
    ready = _full_mix(sess).get(_mix_key(sess, order, stem_settings))
    asyncio.create_task(_run_remix_async(job, stems, sess.sr, stem_settings, s,
                                         clean_choice if do_clean else "off", sess.samples,
                                         original_path,
                                         ready.audio if ready is not None else None))
    return JSONResponse({"job_id": job.id})


def _known_preset(name: str) -> bool:
    """A 1.x preset or alias name (the Remix cleanup menu still sends them)."""
    from .core.settings import LEGACY_ALIASES, LEGACY_PRESETS
    return LEGACY_ALIASES.get(name, name) in LEGACY_PRESETS


def _remix_clean_label(fixes: Dict[str, Any]) -> str:
    """What the cleanup did, in the report's words."""
    parts = []
    tones = fixes.get("tones")
    if isinstance(tones, dict):
        n = int(tones.get("notches") or 0)
        parts.append(f"Fixed tones, {n} notch{'es' if n != 1 else ''}")
    waiting = [_core.catalog.card(k).label for k, v in fixes.items() if v == "not built yet"]
    if waiting:
        parts.append(", ".join(waiting) + ": not built yet")
    return "; ".join(parts) or "nothing found to fix"


def _run_remix(job: Job, stems: Dict[str, np.ndarray], sr: int, stem_settings: Any,
               s: Any, clean_choice: str, original: np.ndarray,
               original_path: Optional[str] = None,
               ready: Optional[np.ndarray] = None) -> None:
    """The worker: runs in a thread. Every stage checks for cancel. Tags and
    the release check as every other tab's export (docs/API.md §4).
    `ready` is the whole mix the preview already built for these lanes."""
    prog = job.run
    if ready is not None:
        prog.stage("mix", "Mixing the stems", "ready from the preview")
        mix = ready
    else:
        prog.stage("mix", "Mixing the stems", "each stem's effects, then the sum")
        mix = render_remix(stems, sr, stem_settings)
    # A Source of its own: the whole-song work is not shared across threads.
    src = _core.Source.from_array(mix, sr)
    rendered = _core.render(src, s, progress=prog)
    out_sr = rendered.sr
    fmt = _core.catalog.output_format(s.format)
    tags = None
    if original_path:
        tags = _api_render._build_tags(
            original_path, None,
            _api_render._note("remix", rendered, _api_render._eq_moves(s, out_sr)))
    prog.stage("export", "Writing the file", fmt.label + (" · tags" if tags else ""))
    processed = os.path.join(job.workdir, f"processed{fmt.ext}")
    exp = _core.export(rendered, processed, source_path=original_path, tags=tags)
    job.processed_path = processed
    written = bool((exp.get("tags") or {}).get("written"))

    prog.stage("report", "Measuring the result")
    fixes = rendered.report.get("fixes", {})
    tones = fixes.get("tones") if isinstance(fixes.get("tones"), dict) else None
    cleaning: Dict[str, Any] = {"enabled": clean_choice != "off"}
    if cleaning["enabled"]:
        cleaning.update({"preset": clean_choice, "label": _remix_clean_label(fixes),
                         "repair_notches": int(tones["notches"]) if tones else 0})
    lufs_out = _finite_or_none(exp["lufs"])
    tp_out = _finite_or_none(exp["true_peak_dbtp"])
    m = rendered.report.get("mastering", {})
    mastering: Dict[str, Any] = {"enabled": False}
    release = None
    if m.get("enabled"):
        mastering = {
            "enabled": True,
            "target_lufs": m["target_lufs"], "ceiling_dbtp": m["ceiling_dbtp"],
            "gain_db": m["gain_db"],
            "before": {"lufs_i": _finite_or_none(_core.meters.loudness(src.at_rate(out_sr), out_sr))},
            "after": {"lufs_i": lufs_out, "true_peak_dbtp": tp_out},
            "limiter": {"max_gain_reduction_db": m["limiter_gain_reduction_db"]},
            "tone_curve_db": m.get("tone_curve_db", []),
        }
        # The clipping check reads the upload, not the stem sum: the sum is
        # peak-scaled to exactly 0.999, which would read as clipped.
        release = _core.release_check(
            rendered.audio, out_sr, x_in=original,
            mastering={"enabled": True, "target_lufs": m["target_lufs"],
                       "ceiling_dbtp": m["ceiling_dbtp"],
                       "after": {"lufs_i": lufs_out, "true_peak_dbtp": tp_out}},
            export={"format": fmt.ext.lstrip("."), "bit_depth": fmt.bits},
            correlation=_core.stereo_correlation(rendered.audio),
            duration_s=float(rendered.audio.shape[0] / out_sr),
            tags={k: v for k, v in tags.items() if k != "software"} if tags else None,
            tags_written=written)
    job.metrics = _api_render._json_safe({
        "sample_rate": out_sr,
        "channels": int(rendered.audio.shape[1]),
        "duration_s": float(rendered.audio.shape[0] / out_sr),
        "input": measure(original),
        "output": measure(rendered.audio),
        "cleaning": cleaning,
        "mastering": mastering,
        "loudness": {"output_lufs_i": lufs_out},
        "release": release,
        "tags_written": written,
        "fixes": fixes,
    })


async def _run_remix_async(job: Job, *args) -> None:
    loop = asyncio.get_running_loop()
    _api_jobs.pusher(job, loop)
    job.status = "running"
    try:
        await loop.run_in_executor(None, _run_remix, job, *args)
    except Exception as e:  # noqa: BLE001  (Cancelled included)
        await _api_jobs.finish(job, e)
        return
    await _api_jobs.finish(job)


# ───────────────────────────────────────────────────────────────────────────
# SSE helper
# ───────────────────────────────────────────────────────────────────────────

def _sse_event(data: Dict[str, Any]) -> str:
    return f"data: {json.dumps(data)}\n\n"
