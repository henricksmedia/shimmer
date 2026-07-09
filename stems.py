"""
stems.py — Demucs stem separation: environment bootstrap, runner, cache.

Torch + Demucs are ~6 GB installed, so they NEVER go in the app venv.
This module manages a dedicated side venv and talks to it via
subprocess only:

    env resolution order:
      1. $SHIMMER_STEMS_PYTHON   — explicit python.exe override
      2. <app>/.venv-stems       — created on demand with uv (or venv+pip)

    GPU: if nvidia-smi is present, torch installs from the cu121 index
    and separation runs with `-d cuda`; otherwise CPU (slower but fine).

Separation results are cached by content hash at <app>/stem_cache/<sha1>/
as vocals/drums/bass/other WAVs at the ORIGINAL sample rate (Demucs works
at 44.1 kHz; we resample back so downstream code never sees a rate change).
"""

from __future__ import annotations

import _winfix  # noqa: F401

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

import numpy as np

HERE = Path(__file__).resolve().parent
STEMS_VENV = HERE / ".venv-stems"
STEM_CACHE = HERE / "stem_cache"
DEMUCS_MODEL = "htdemucs"
STEM_NAMES = ("vocals", "drums", "bass", "other")

ProgressCb = Optional[Callable[[float, str], None]]


def _report(cb: ProgressCb, frac: float, msg: str) -> None:
    if cb:
        cb(float(frac), msg)


# ── Environment ──────────────────────────────────────────────────────────

def stems_python() -> Optional[str]:
    """Path to the separation env's python, or None if not installed."""
    override = os.environ.get("SHIMMER_STEMS_PYTHON", "").strip()
    if override and Path(override).is_file():
        return override
    exe = STEMS_VENV / "Scripts" / "python.exe"
    if exe.is_file():
        return str(exe)
    return None


def env_ready() -> bool:
    py = stems_python()
    if not py:
        return False
    try:
        r = subprocess.run([py, "-c", "import demucs.separate"],
                           capture_output=True, timeout=120)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def has_cuda() -> bool:
    return shutil.which("nvidia-smi") is not None


def install_env(progress: ProgressCb = None) -> str:
    """Create .venv-stems and install torch + demucs. Returns python path.

    One-time cost: several GB of downloads. Raises RuntimeError with a
    readable message on failure.
    """
    _report(progress, 0.02, "Creating separation environment…")
    uv = shutil.which("uv")
    py = STEMS_VENV / "Scripts" / "python.exe"

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
        _report(progress, frac, msg)
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
    _pip(["demucs", "soundfile"], 0.75, "Installing Demucs…")
    _report(progress, 0.95, "Verifying separation engine…")
    if not env_ready():
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


def cache_dir_for(digest: str) -> Path:
    return STEM_CACHE / digest


def cache_complete(digest: str) -> bool:
    d = cache_dir_for(digest)
    return all((d / f"{n}.wav").is_file() for n in STEM_NAMES)


# ── Separation ───────────────────────────────────────────────────────────

def separate(input_path: str, target_sr: int,
             progress: ProgressCb = None) -> Dict[str, np.ndarray]:
    """Separate `input_path` into stems, resampled to `target_sr`.

    Uses the cache when possible. Returns {name: (n, ch) float32}.
    """
    import soundfile as sf
    from scipy.signal import resample_poly

    digest = file_digest(input_path)
    out_dir = cache_dir_for(digest)

    if not cache_complete(digest):
        py = stems_python()
        if not py or not env_ready():
            py = install_env(progress)

        device = "cuda" if has_cuda() else "cpu"
        _report(progress, 0.30,
                f"Separating stems ({device.upper()})…"
                + ("" if device == "cuda" else " CPU mode takes a few minutes"))

        STEM_CACHE.mkdir(exist_ok=True)
        work = out_dir.parent / f"{digest}.work"
        shutil.rmtree(work, ignore_errors=True)
        env = dict(os.environ)
        # Keep model checkpoints next to the cache, off the system drive.
        env.setdefault("TORCH_HOME", str(STEM_CACHE / "torch-home"))
        r = subprocess.run(
            [py, "-m", "demucs", "-n", DEMUCS_MODEL, "-d", device,
             "-o", str(work), str(input_path)],
            capture_output=True, text=True, env=env)
        if r.returncode != 0:
            shutil.rmtree(work, ignore_errors=True)
            raise RuntimeError(
                f"Demucs failed: {(r.stderr or r.stdout)[-800:]}")

        # demucs writes <work>/<model>/<track stem>/<stem>.wav
        produced = list((work / DEMUCS_MODEL).glob("*/"))
        if not produced:
            shutil.rmtree(work, ignore_errors=True)
            raise RuntimeError("Demucs produced no output")
        shutil.rmtree(out_dir, ignore_errors=True)
        shutil.move(str(produced[0]), str(out_dir))
        shutil.rmtree(work, ignore_errors=True)
        meta = {"model": DEMUCS_MODEL, "source": os.path.basename(input_path)}
        (out_dir / "meta.json").write_text(json.dumps(meta))

    _report(progress, 0.90, "Loading stems…")
    stems: Dict[str, np.ndarray] = {}
    for name in STEM_NAMES:
        x, sr = sf.read(str(out_dir / f"{name}.wav"),
                        dtype="float32", always_2d=True)
        if sr != target_sr:
            from math import gcd
            g = gcd(target_sr, sr)
            x = resample_poly(
                x, target_sr // g, sr // g, axis=0).astype(np.float32)
        stems[name] = x
    _report(progress, 1.0, "Stems ready")
    return stems
