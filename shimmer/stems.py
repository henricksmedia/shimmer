"""
stems.py — Stem separation: quality tiers, the side-venv bootstrap, the
worker subprocess, a per-model cache, and the stem-level measurements
the Remix mixer shows (residual, null test, share, peaks, loop hint).

Torch + Demucs are ~6 GB installed, so they NEVER go in the app venv.
This module manages a dedicated side venv and talks to it only through
`stems_runner.py`, launched as a subprocess:

    env resolution order:
      1. $SHIMMER_STEMS_PYTHON   — explicit python.exe override
      2. <app>/.venv-stems       — created on demand with uv (or venv+pip)

    GPU: if nvidia-smi is present, torch installs from the cu121 index;
    the worker itself picks CUDA when torch can see it, else the CPU.

Quality tiers (`TIERS`) name the model and the number of shift passes.
Results are cached by content hash AND model at

    <app>/stem_cache/<sha1>/<model>/{vocals,drums,bass,other[,guitar,piano]}.wav

as 32-bit float WAVs at Demucs' 44.1 kHz, exactly as the model produced
them (no clipping, no rescaling, no 16-bit truncation). `separate()`
resamples them to the session rate so downstream code never sees a
rate change. The pre-tier layout (<sha1>/vocals.wav, 16-bit) is
migrated into <sha1>/htdemucs/ the first time it is touched.

The residual — mix minus the sum of the stems — is what the separator
dropped: reverb tails, room, and most of the generator's junk. It is
kept as a stem of its own so the unchanged mix nulls against the
original exactly (docs/PLAN.md, decision 2).
"""

from __future__ import annotations

from . import _winfix  # noqa: F401

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

HERE = Path(__file__).resolve().parent.parent   # project root; package is one level down
RUNNER = Path(__file__).resolve().parent / "stems_runner.py"
STEMS_VENV = HERE / ".venv-stems"
STEM_CACHE = HERE / "stem_cache"
DEMUCS_MODEL = "htdemucs"                       # the pre-tier model; legacy cache entries
STEM_NAMES = ("vocals", "drums", "bass", "other")
RESIDUAL = "residual"
# Display order for any stem set: the classic four, the 6-stem extras,
# the catch-all, then what the separator dropped.
STEM_ORDER = ("vocals", "drums", "bass", "guitar", "piano", "other", RESIDUAL)
STEM_LABELS = {
    "vocals": "Vocals", "drums": "Drums", "bass": "Bass", "other": "Other",
    "guitar": "Guitar", "piano": "Piano", RESIDUAL: "Residual",
}

ProgressCb = Optional[Callable[..., None]]


@dataclass(frozen=True)
class Tier:
    key: str
    label: str
    model: str           # a Demucs model name, or several joined with '+' (ensemble)
    shifts: int          # Demucs shift passes (each is a full pass over the track)
    stems: int
    blurb: str
    download_mb: int     # checkpoint download on first use
    gpu_s_per_min: float  # rough separation time per minute of audio
    cpu_s_per_min: float
    overlap: float = 0.25  # segment overlap; more = fewer seams, slower
    engine: str = "demucs"  # demucs | hybrid: a RoFormer vocal model, then Demucs on the rest
    vocal_model: str = ""   # audio-separator checkpoint for the hybrid engine
    # Who trained the weights and under what terms: shown on the chooser
    # card and in Help, mirrored in NOTICE. Only licences that permit use
    # on released, sold music are offered.
    author: str = "Meta Platforms (Demucs)"
    license: str = "MIT"
    license_url: str = "https://github.com/facebookresearch/demucs/blob/main/LICENSE"

    @property
    def models(self) -> List[str]:
        return [m for m in self.model.split("+") if m]

    @property
    def demucs_model(self) -> str:
        """The Demucs part of the spec: all of it, or what follows the
        vocal model's tag in a hybrid ('kim_melroformer+htdemucs_ft')."""
        if self.engine == "hybrid":
            parts = self.models
            return "+".join(parts[1:]) if len(parts) > 1 else DEMUCS_MODEL
        return self.model


# Time estimates measured on an RTX 4070 SUPER with a 4:32 track: Fast
# 9 s, Best 22 s, wall clock including about 3 s of model load. CPU
# figures assume the usual 12× slower. They only feed the "about 20 s"
# hint in the dock (`LOAD_OVERHEAD_S` is added once per run).
LOAD_OVERHEAD_S = 3.0
TIERS: Dict[str, Tier] = {
    "fast": Tier("fast", "Fast", "htdemucs", 1, 4,
                 "Hybrid Transformer Demucs · one pass",
                 80, 1.4, 20.0),
    "best": Tier("best", "Best", "htdemucs_ft", 1, 4,
                 "fine-tuned · one model per stem · four passes",
                 330, 4.2, 55.0),
    "six": Tier("six", "6 stems", "htdemucs_6s", 1, 6,
                "adds guitar and piano · experimental",
                80, 1.4, 20.0),
    # Everything the installed engine can still give, the MDX23 recipe:
    # the fine-tuned specialists averaged with the base model and Hybrid
    # Demucs v3 (different training and architecture, so their errors
    # differ), two shift passes, and 50 % segment overlap. Six models ×
    # 2 shifts × the wider overlap is about 4.5× Best.
    "ultra": Tier("ultra", "Ultra", "htdemucs_ft+htdemucs+hdemucs_mmi", 2, 4,
                  "Best averaged with htdemucs and Hybrid Demucs v3 · 2 shift passes · 50 % overlap",
                  570, 19.0, 250.0, overlap=0.5),
    # The step past Demucs for the stem that matters most: Kimberley
    # Jensen's Mel-Band RoFormer (MIT since 2026-04, 12.6 dB vocal SDR
    # against htdemucs_ft's 10.8) takes the vocal out first; Demucs Best
    # then splits only the instrumental, so its vocal output is bleed
    # that folds back into the vocal lane. Needs the RoFormer runner
    # (audio-separator, MIT) in the side venv; installed on first use.
    "studio": Tier("studio", "Studio", "kim_melroformer+htdemucs_ft", 1, 4,
                   "Mel-Band RoFormer vocals (Kimberley Jensen, MIT) · Best splits the rest",
                   915, 18.0, 200.0, engine="hybrid",
                   vocal_model="vocals_mel_band_roformer.ckpt",
                   author="Kimberley Jensen (vocal model) · Meta (Demucs)",
                   license="MIT",
                   license_url="https://github.com/KimberleyJensen/Mel-Band-Roformer-Vocal-Model"),
}


def models_dir() -> Path:
    """Where the RoFormer runner keeps its checkpoints (next to the
    Demucs ones, off the system drive)."""
    return STEM_CACHE / "models"


def roformer_ready() -> Optional[bool]:
    """Whether audio-separator imports in the side venv: None until the
    engine check has run."""
    if not _ENV_STATE["checked"]:
        return None
    return bool((_ENV_STATE.get("info") or {}).get("roformer"))


def install_roformer(progress: ProgressCb = None) -> None:
    """Add audio-separator[gpu] (MIT) to the side venv. One-time, about
    300 MB; torch stays as it is (the resolver keeps the installed one)."""
    py = stems_python()
    if not py:
        raise RuntimeError("Separation engine is not installed")
    _report(progress, 0.06, "Installing the RoFormer runner… one-time, about 300 MB",
            stage="setup")
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install", "--python", py, "audio-separator[gpu]"]
    else:
        cmd = [py, "-m", "pip", "install", "audio-separator[gpu]"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"RoFormer runner install failed: {(r.stderr or r.stdout)[-500:]}")
    if not env_ready(force=True) or not roformer_ready():
        raise RuntimeError("RoFormer runner installed but failed to import")


def tier_downloaded(t: Tier) -> Optional[bool]:
    """Checkpoint state for a whole tier: every Demucs member, and the
    vocal model file for a hybrid."""
    demucs_state = model_downloaded(t.demucs_model)
    if t.engine != "hybrid":
        return demucs_state
    vocal = (models_dir() / t.vocal_model).is_file() if t.vocal_model else False
    if not vocal or demucs_state is False:
        return False
    return None if demucs_state is None else True


def resolve_tier(key: Optional[str]) -> Tier:
    return TIERS.get(str(key or "").lower()) or TIERS[default_tier()]


def default_tier() -> str:
    """Best when a GPU is present (about a minute), Fast on a CPU."""
    return "best" if has_cuda() else "fast"


def _venv_python(venv: Path) -> Path:
    """Interpreter path inside `venv`.

    Windows venvs put it in Scripts/python.exe; POSIX venvs use bin/python.
    """
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _report(cb: ProgressCb, frac: float, msg: str, stage: Optional[str] = None) -> None:
    if cb:
        if stage is None:
            cb(float(frac), msg)
        else:
            try:
                cb(float(frac), msg, stage)
            except TypeError:
                cb(float(frac), msg)


# ── Environment ──────────────────────────────────────────────────────────

def stems_python() -> Optional[str]:
    """Path to the separation env's python, or None if not installed."""
    override = os.environ.get("SHIMMER_STEMS_PYTHON", "").strip()
    if override and Path(override).is_file():
        return override
    exe = _venv_python(STEMS_VENV)
    if exe.is_file():
        return str(exe)
    return None


def torch_home() -> Path:
    """Where the model checkpoints live: next to the cache, off the
    system drive, unless the user points TORCH_HOME elsewhere."""
    return Path(os.environ.get("TORCH_HOME") or (STEM_CACHE / "torch-home"))


def _runner_env() -> Dict[str, str]:
    env = dict(os.environ)
    env.setdefault("TORCH_HOME", str(torch_home()))
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# The import check costs a torch import (about two seconds), so it runs
# once per process and the answer is kept.
_ENV_STATE: Dict[str, Any] = {"checked": False, "ok": False, "info": {}}


def env_ready(force: bool = False) -> bool:
    if _ENV_STATE["checked"] and not force:
        return bool(_ENV_STATE["ok"])
    py = stems_python()
    ok, info = False, {}
    if py:
        try:
            r = subprocess.run([py, str(RUNNER), "check"], capture_output=True,
                               text=True, timeout=180, env=_runner_env(),
                               cwd=str(HERE))
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("{"):
                    try:
                        info = json.loads(line)
                    except ValueError:
                        continue
            ok = bool(info.get("ok"))
        except (OSError, subprocess.TimeoutExpired):
            ok = False
    _ENV_STATE.update({"checked": True, "ok": ok, "info": info})
    return ok


def has_cuda() -> bool:
    return shutil.which("nvidia-smi") is not None


_GPU_NAME: Optional[str] = None


def gpu_name() -> str:
    """The first NVIDIA adapter's marketing name, or '' without one."""
    global _GPU_NAME
    if _GPU_NAME is not None:
        return _GPU_NAME
    name = ""
    if has_cuda():
        try:
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=10)
            name = (r.stdout or "").strip().splitlines()[0].strip() if r.stdout else ""
        except (OSError, subprocess.TimeoutExpired, IndexError):
            name = ""
    _GPU_NAME = name
    return name


def _demucs_remote_dir() -> Optional[Path]:
    """The demucs package's `remote/` folder inside the side venv: the
    model manifests live there (no torch import needed to read them)."""
    py = stems_python()
    roots: List[Path] = []
    if py:
        venv = Path(py).resolve().parent.parent
        roots.append(venv / "Lib" / "site-packages")
        lib = venv / "lib"
        if lib.is_dir():
            roots.extend(p / "site-packages" for p in lib.glob("python3*"))
    for root in roots:
        d = root / "demucs" / "remote"
        if (d / "files.txt").is_file():
            return d
    return None


def model_downloaded(model: str) -> Optional[bool]:
    """True/False when the checkpoint state is knowable, None otherwise.
    An ensemble ('a+b') is downloaded when every member is."""
    names = [m for m in str(model).split("+") if m]
    if len(names) > 1:
        states = [model_downloaded(n) for n in names]
        if any(s is False for s in states):
            return False
        return None if any(s is None for s in states) else True
    remote = _demucs_remote_dir()
    if remote is None:
        return None
    manifest = remote / f"{model}.yaml"
    if not manifest.is_file():
        return None
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"models:\s*\[([^\]]*)\]", text)
    if not m:
        return None
    sigs = re.findall(r"[0-9a-f]{8}", m.group(1))
    if not sigs:
        return None
    ckpt = torch_home() / "hub" / "checkpoints"
    return all(any(ckpt.glob(f"{sig}-*.th")) for sig in sigs)


def engine_info(check: bool = True) -> Dict[str, Any]:
    """What the Remix tab shows before the first separation: is the
    engine installed and importable, is there a GPU, and per tier the
    model, its checkpoint state and a time estimate."""
    py = stems_python()
    cuda = has_cuda()
    info: Dict[str, Any] = {
        "installed": bool(py),
        "ready": None,
        "cuda": cuda,
        "gpu": gpu_name(),
        "torch": "",
        "demucs": "",
        "default_tier": default_tier(),
        "cache_dir": str(STEM_CACHE),
        "load_overhead_s": LOAD_OVERHEAD_S,
    }
    info["roformer"] = None
    if py and check:
        info["ready"] = env_ready()
        st = _ENV_STATE.get("info") or {}
        info["torch"] = st.get("torch", "")
        info["demucs"] = st.get("demucs", "")
        info["roformer"] = bool(st.get("roformer"))
        if st.get("gpu"):
            info["gpu"] = st["gpu"]
        if "cuda" in st:
            info["cuda"] = bool(st["cuda"])
    tiers = []
    for t in TIERS.values():
        d = asdict(t)
        d["downloaded"] = tier_downloaded(t) if py else False
        tiers.append(d)
    info["tiers"] = tiers
    return info


def install_env(progress: ProgressCb = None) -> str:
    """Create .venv-stems and install torch + demucs. Returns python path.

    One-time cost: several GB of downloads. Raises RuntimeError with a
    readable message on failure.
    """
    _report(progress, 0.02, "Creating separation environment…", stage="setup")
    uv = shutil.which("uv")
    py = _venv_python(STEMS_VENV)

    if not py.is_file():
        if uv:
            r = subprocess.run(
                [uv, "venv", str(STEMS_VENV), "--python", "3.11"],
                capture_output=True, text=True)
        else:
            r = subprocess.run(
                [sys.executable, "-m", "venv", str(STEMS_VENV)],
                capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"venv creation failed: {r.stderr[-500:]}")

    def _pip(args, frac, msg):
        _report(progress, frac, msg, stage="setup")
        if uv:
            cmd = [uv, "pip", "install", "--python", str(py)] + args
        else:
            cmd = [str(py), "-m", "pip", "install"] + args
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"install failed ({msg}): {r.stderr[-500:]}")

    if has_cuda():
        _pip(["torch", "torchaudio",
              "--index-url", "https://download.pytorch.org/whl/cu121"],
             0.10, "Installing PyTorch (GPU)… this is a one-time ~3 GB download")
    else:
        _pip(["torch", "torchaudio"],
             0.10, "Installing PyTorch (CPU)… one-time download")
    _pip(["demucs", "soundfile"], 0.16, "Installing Demucs…")
    _report(progress, 0.19, "Verifying separation engine…", stage="setup")
    if not env_ready(force=True):
        raise RuntimeError("Separation engine installed but failed to import")
    return str(py)


# ── Cache ────────────────────────────────────────────────────────────────

def file_digest(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def cache_dir_for(digest: str, model: str = DEMUCS_MODEL) -> Path:
    return STEM_CACHE / digest / model


def _legacy_migrate(digest: str) -> None:
    """Pre-tier layout (<sha1>/vocals.wav …, always htdemucs) → the
    per-model folder. Done in place, once, the first time it is seen."""
    root = STEM_CACHE / digest
    if not (root / "vocals.wav").is_file():
        return
    dest = root / DEMUCS_MODEL
    dest.mkdir(parents=True, exist_ok=True)
    for name in STEM_NAMES + ("meta.json",):
        src = root / (name if name.endswith(".json") else f"{name}.wav")
        if src.is_file():
            try:
                shutil.move(str(src), str(dest / src.name))
            except OSError:
                pass


def _read_meta(d: Path) -> Dict[str, Any]:
    try:
        data = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _sources_in(d: Path) -> List[str]:
    meta = _read_meta(d)
    srcs = meta.get("sources")
    if isinstance(srcs, list) and srcs:
        return [str(s) for s in srcs]
    return list(STEM_NAMES)


def cache_complete(digest: str, model: str = DEMUCS_MODEL) -> bool:
    _legacy_migrate(digest)
    d = cache_dir_for(digest, model)
    return d.is_dir() and all((d / f"{n}.wav").is_file() for n in _sources_in(d))


def cached_models(digest: str) -> List[str]:
    """Models that already have a complete stem set for this file."""
    _legacy_migrate(digest)
    root = STEM_CACHE / digest
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and not p.name.endswith(".work")
                  and cache_complete(digest, p.name))


def cached_tiers(digest: str) -> List[str]:
    models = set(cached_models(digest))
    return [t.key for t in TIERS.values() if t.model in models]


def library(limit: int = 200) -> List[Dict[str, Any]]:
    """Every cached stem set on disk, newest first: what the Recent
    sessions list uses to badge tracks whose stems are already done."""
    if not STEM_CACHE.is_dir():
        return []
    out = []
    for root in STEM_CACHE.iterdir():
        if not root.is_dir() or not re.fullmatch(r"[0-9a-f]{40}", root.name):
            continue
        models = cached_models(root.name)
        if not models:
            continue
        name, newest = "", 0.0
        for m in models:
            meta = _read_meta(cache_dir_for(root.name, m))
            src = str(meta.get("source") or "")
            if src.startswith("input_"):
                src = src[len("input_"):]
            name = name or src
            try:
                newest = max(newest, (cache_dir_for(root.name, m) / "meta.json").stat().st_mtime)
            except OSError:
                pass
        out.append({"digest": root.name, "name": name, "models": models,
                    "tiers": [t.key for t in TIERS.values() if t.model in models],
                    "updated_at": newest})
    out.sort(key=lambda r: -float(r["updated_at"]))
    return out[:limit]


# ── The worker ───────────────────────────────────────────────────────────

def _parse_runner_line(line: str) -> Optional[Dict[str, Any]]:
    """One stdout line from the worker → its JSON event, or None for
    anything else (download bars, warnings). tqdm redraws with '\\r', so
    a physical line can hold many frames; the last one counts."""
    line = line.rstrip("\r\n").split("\r")[-1].strip()
    if not line.startswith("{"):
        return None
    try:
        ev = json.loads(line)
    except ValueError:
        return None
    return ev if isinstance(ev, dict) and "event" in ev else None


def _run_runner(py: str, args: List[str],
                on_event: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
    """Run stems_runner.py, stream its events, return the `done` event.
    Raises RuntimeError with the worker's own message on failure."""
    proc = subprocess.Popen(
        [py, str(RUNNER)] + args,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=_runner_env(), cwd=str(HERE))
    log: deque = deque(maxlen=40)
    done: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    assert proc.stdout is not None
    for raw in iter(proc.stdout.readline, b""):
        line = raw.decode("utf-8", "replace")
        ev = _parse_runner_line(line)
        if ev is None:
            text = line.rstrip("\r\n").split("\r")[-1].strip()
            if text:
                log.append(text[-300:])
            continue
        kind = ev.get("event")
        if kind == "done":
            done = ev
        elif kind == "error":
            error = str(ev.get("message") or "separation failed")
        else:
            on_event(ev)
    rc = proc.wait()
    if error:
        raise RuntimeError(error)
    if done is None:
        tail = " | ".join(list(log)[-6:])
        raise RuntimeError(
            f"Separation worker exited ({rc}) without a result"
            + (f": {tail}" if tail else ""))
    return done


# ── Separation ───────────────────────────────────────────────────────────

def separate(input_path: str, target_sr: int,
             tier: Optional[str] = None,
             progress: ProgressCb = None,
             digest: Optional[str] = None,
             ) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
    """Separate `input_path` into stems, resampled to `target_sr`.

    Uses the cache when possible. Returns ({name: (n, ch) float32},
    info) where info carries tier, model, shifts, cached, device,
    elapsed_s and the stem order.
    """
    import soundfile as sf
    from scipy.signal import resample_poly

    t = resolve_tier(tier)
    digest = digest or file_digest(input_path)
    out_dir = cache_dir_for(digest, t.model)
    cached = cache_complete(digest, t.model)
    info: Dict[str, Any] = {
        "tier": t.key, "label": t.label, "model": t.model, "shifts": t.shifts,
        "cached": cached, "device": "", "elapsed_s": 0.0, "format": "float32",
    }

    if not cached:
        py = stems_python()
        if not py or not env_ready():
            py = install_env(progress)
        if t.engine == "hybrid" and not roformer_ready():
            install_roformer(progress)
        dl = tier_downloaded(t)
        note = (f" · downloading it first (one time, about {t.download_mb} MB)"
                if dl is False else "")
        what = (f"{t.vocal_model} + {t.demucs_model}" if t.engine == "hybrid"
                else t.model)
        _report(progress, 0.22, f"Loading the {t.label} model ({what}){note}",
                stage="separate")

        STEM_CACHE.mkdir(exist_ok=True)
        work = STEM_CACHE / digest / f"{t.model}.work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        state = {"frac": 0.25}

        def on_event(ev: Dict[str, Any]) -> None:
            if ev.get("event") == "progress":
                f = float(ev.get("fraction") or 0.0)
                state["frac"] = 0.25 + 0.63 * max(0.0, min(1.0, f))
                _report(progress, state["frac"],
                        f"Separating · {int(round(f * 100))}%", stage="separate")
            elif ev.get("event") == "status":
                _report(progress, state["frac"], str(ev.get("message") or ""),
                        stage="separate")

        args = [
            "separate", str(input_path),
            "--model", t.demucs_model, "--shifts", str(t.shifts),
            "--overlap", str(t.overlap),
            "--device", "auto", "--out", str(work),
        ]
        if t.engine == "hybrid":
            models_dir().mkdir(parents=True, exist_ok=True)
            args += ["--engine", "hybrid", "--vocal-model", t.vocal_model,
                     "--models-dir", str(models_dir())]
        try:
            done = _run_runner(py, args, on_event)
        except Exception:
            shutil.rmtree(work, ignore_errors=True)
            raise
        sources = [str(s) for s in (done.get("sources") or [])]
        missing = [s for s in sources if not (work / f"{s}.wav").is_file()]
        if not sources or missing:
            shutil.rmtree(work, ignore_errors=True)
            raise RuntimeError("Separation produced no usable stems"
                               + (f" (missing {', '.join(missing)})" if missing else ""))
        shutil.rmtree(out_dir, ignore_errors=True)
        os.replace(str(work), str(out_dir))
        meta = {
            "model": t.model, "tier": t.key, "shifts": t.shifts,
            "overlap": t.overlap, "engine": t.engine,
            "vocal_model": t.vocal_model,
            "vocal_s": float(done.get("vocal_s") or 0.0),
            "sources": sources, "sr": int(done.get("sr") or 44100),
            "input_sr": int(done.get("input_sr") or 0),
            "source": os.path.basename(input_path),
            "device": str(done.get("device") or ""),
            "elapsed_s": float(done.get("elapsed_s") or 0.0),
            "passes": int(done.get("passes") or 1),
            "format": "float32", "created": time.time(),
        }
        (out_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        info.update(device=meta["device"], elapsed_s=meta["elapsed_s"])
    else:
        meta = _read_meta(out_dir)
        info.update(device=str(meta.get("device") or ""),
                    elapsed_s=float(meta.get("elapsed_s") or 0.0),
                    format=str(meta.get("format") or "int16"))

    _report(progress, 0.90, "Loading stems…", stage="load")
    stems: Dict[str, np.ndarray] = {}
    for name in _sources_in(out_dir):
        x, sr = sf.read(str(out_dir / f"{name}.wav"),
                        dtype="float32", always_2d=True)
        if sr != target_sr:
            from math import gcd
            g = gcd(target_sr, sr)
            x = resample_poly(
                x, target_sr // g, sr // g, axis=0).astype(np.float32)
        stems[name] = x
    info["order"] = order_stems(stems)
    _report(progress, 0.94, "Stems loaded", stage="load")
    return stems, info


# ── Measurements ─────────────────────────────────────────────────────────

def order_stems(stems: Dict[str, Any]) -> List[str]:
    """Canonical display order for whatever stem names are present."""
    known = [n for n in STEM_ORDER if n in stems]
    extra = sorted(n for n in stems if n not in STEM_ORDER)
    return known + extra


def add_residual(stems: Dict[str, np.ndarray], mix: np.ndarray
                 ) -> Tuple[np.ndarray, float]:
    """residual = mix − Σ stems, trimmed to the common length.

    Returns (residual, null_db): the residual's RMS relative to the
    mix in dB. −∞ would be a perfect split; Demucs lands near −30.
    """
    mix = np.asarray(mix, dtype=np.float32)
    if mix.ndim == 1:
        mix = mix[:, None]
    parts = [np.asarray(v, dtype=np.float32) for k, v in stems.items() if k != RESIDUAL]
    if not parts:
        raise ValueError("No stems to subtract from the mix")
    n = min([mix.shape[0]] + [p.shape[0] for p in parts])
    ch = mix.shape[1]
    total = np.zeros((n, ch), dtype=np.float32)
    for p in parts:
        if p.shape[1] != ch:
            p = np.repeat(p[:, :1], ch, axis=1) if p.shape[1] == 1 else p[:, :ch]
        total += p[:n]
    residual = (mix[:n] - total).astype(np.float32)
    return residual, _rel_db(residual, mix[:n])


def _rms(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    return float(np.sqrt(np.mean(x ** 2))) if x.size else 0.0


def _rel_db(a: np.ndarray, ref: np.ndarray) -> float:
    return float(20.0 * np.log10((_rms(a) + 1e-12) / (_rms(ref) + 1e-12)))


def _peaks(x: np.ndarray, columns: int) -> List[float]:
    """Per-column max |x| over both channels: the lane waveform."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 2:
        x = np.max(np.abs(x), axis=1)
    else:
        x = np.abs(x)
    n = x.shape[0]
    columns = max(1, int(columns))
    if n == 0:
        return [0.0] * columns
    step = int(np.ceil(n / columns))
    pad = step * columns - n
    if pad:
        x = np.concatenate([x, np.zeros(pad, dtype=np.float32)])
    return [round(float(v), 4) for v in x.reshape(columns, step).max(axis=1)]


def suggested_loop_s(stems: Dict[str, np.ndarray], sr: int,
                     win_s: float = 10.0) -> float:
    """Start of the busiest `win_s` window: the section where every
    stem is playing (a chorus), not a drums-only breakdown. Scores each
    second by the sum of the stems' log energies, so one silent part
    pulls a window down hard."""
    names = [n for n in stems if n != RESIDUAL] or list(stems)
    if not names:
        return 0.0
    n = min(stems[k].shape[0] for k in names)
    bin_n = max(1, int(sr))
    bins = n // bin_n
    if bins < 2:
        return 0.0
    score = np.zeros(bins, dtype=np.float64)
    floor = 1e-8   # −80 dB: silence costs, but not infinitely
    for k in names:
        x = np.asarray(stems[k][:bins * bin_n], dtype=np.float32)
        if x.ndim == 2:
            x = x.mean(axis=1)
        e = (x.reshape(bins, bin_n).astype(np.float64) ** 2).mean(axis=1)
        score += np.log10(e + floor)
    win = max(1, min(bins, int(round(win_s))))
    csum = np.concatenate([[0.0], np.cumsum(score)])
    sums = csum[win:] - csum[:-win]
    start = int(np.argmax(sums))
    return float(start)


def measure_stems(stems: Dict[str, np.ndarray], mix: np.ndarray, sr: int,
                  columns: int = 600, loop_s: float = 10.0,
                  null_db: Optional[float] = None) -> Dict[str, Any]:
    """Everything the mixer draws: order, per-stem level/peak/share,
    lane peaks, the mix's peaks, the null-test figure and a loop hint."""
    order = order_stems(stems)
    energies = {k: float(np.mean(np.asarray(stems[k], dtype=np.float64) ** 2))
                for k in order}
    total = sum(energies.values()) or 1e-20
    items = []
    for k in order:
        x = stems[k]
        peak = float(np.max(np.abs(x))) if x.size else 0.0
        items.append({
            "key": k,
            "label": STEM_LABELS.get(k, k.replace("_", " ").title()),
            "rms_db": round(float(10.0 * np.log10(energies[k] + 1e-20)), 2),
            "peak_db": round(float(20.0 * np.log10(peak + 1e-12)), 2),
            "share": round(energies[k] / total, 4),
            "peaks": _peaks(x, columns),
        })
    n = min([mix.shape[0]] + [stems[k].shape[0] for k in order]) if order else mix.shape[0]
    out: Dict[str, Any] = {
        "order": order,
        "stems": items,
        "mix_peaks": _peaks(mix, columns),
        "duration_s": round(float(n / sr), 3),
        "suggested_loop_s": suggested_loop_s(stems, sr, loop_s),
        "columns": int(columns),
    }
    if null_db is None and RESIDUAL in stems:
        null_db = _rel_db(stems[RESIDUAL][:n], mix[:n])
    if null_db is not None:
        out["null_db"] = round(float(null_db), 2)
    return out
