"""The optional GPU lease (shimmer/gpu_lease_hook.py).

On a machine without the lease library nothing changes: no import, same
output. With it, the stem split holds the lease only while it uses the
GPU, and gives it back after the model is off the GPU: at the end, on an
error, and before the CPU fallback. A mastering render with a fix that needs
the vocal takes the lease through the same split.

The runner runs for real, as the app runs it (a subprocess), with small
stand-ins for torch, demucs and the lease library that write each GPU event
to a log, so the tests read the order things happened in.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from shimmer import gpu_lease_hook, stems

RUNNER = Path(stems.__file__).resolve().parent / "stems_runner.py"

FAKE_TORCH = '''
import os
import numpy as np
__version__ = "0-fake"


def _log(line):
    with open(os.environ["FAKE_GPU_LOG"], "a", encoding="utf-8") as f:
        f.write(line + "\\n")


class Tensor(np.ndarray):
    def cpu(self):
        return self

    def numpy(self):
        return np.asarray(self)


def from_numpy(x):
    return np.asarray(x).view(Tensor)


class cuda:
    @staticmethod
    def is_available():
        return os.environ.get("FAKE_CUDA") == "1"

    @staticmethod
    def get_device_name(i=0):
        return "Fake GPU"

    @staticmethod
    def empty_cache():
        _log("EMPTY_CACHE")
'''

FAKE_DEMUCS_APPLY = '''
import os
import numpy as np
import torch


class _Tqdm:
    @staticmethod
    def tqdm(it, **kw):
        return it


tqdm = _Tqdm


class BagOfModels:
    def __init__(self, models, weights=None):
        self.models, self.weights = models, weights


def apply_model(model, mix, device="cpu", shifts=1, split=True, overlap=0.25,
                progress=False, segment=None):
    torch._log(f"APPLY {device}")
    if device == "cuda" and os.environ.get("FAKE_OOM") == "1":
        raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
    if os.environ.get("FAKE_FAIL") == "1":
        raise RuntimeError("the model broke")
    for _ in tqdm.tqdm(range(3)):
        pass
    x = np.asarray(mix)[0]
    return np.stack([x * w for w in (0.1, 0.2, 0.3, 0.4)])[None].view(torch.Tensor)
'''

FAKE_DEMUCS_PRETRAINED = '''
import torch


class FakeModel:
    samplerate = 44100
    audio_channels = 2
    sources = ["drums", "bass", "other", "vocals"]

    def eval(self):
        return self

    def cpu(self):
        torch._log("MODEL_CPU")
        return self


def get_model(name):
    return FakeModel()
'''

FAKE_LEASE = '''
import os


def _log(line):
    with open(os.environ["FAKE_GPU_LOG"], "a", encoding="utf-8") as f:
        f.write(line + "\\n")


class GpuLease:
    def __init__(self, tool, purpose="", vram_gb=0, on_wait=None, **kw):
        self.tool, self.purpose, self.vram_gb = tool, purpose, vram_gb
        if on_wait:
            on_wait("Waiting for the GPU lease: Test tool | a test")

    def __enter__(self):
        _log(f"ACQUIRE {self.tool} | {self.purpose} | {self.vram_gb}")
        return self

    def __exit__(self, *exc):
        _log("RELEASE")
        return False
'''


def _fakes(tmp: Path) -> Path:
    root = tmp / "fakes"
    (root / "torch").mkdir(parents=True)
    (root / "torch" / "__init__.py").write_text(FAKE_TORCH, encoding="utf-8")
    (root / "demucs").mkdir()
    (root / "demucs" / "__init__.py").write_text('__version__ = "0-fake"\n', encoding="utf-8")
    (root / "demucs" / "apply.py").write_text(FAKE_DEMUCS_APPLY, encoding="utf-8")
    (root / "demucs" / "pretrained.py").write_text(FAKE_DEMUCS_PRETRAINED, encoding="utf-8")
    return root


def _lease_home(tmp: Path) -> Path:
    home = tmp / "GpuLease"
    home.mkdir()
    (home / "gpu_lease.py").write_text(FAKE_LEASE, encoding="utf-8")
    return home


def _song(path: Path, seconds: float = 2.0) -> Path:
    sr = 44100
    t = np.arange(int(seconds * sr)) / sr
    rng = np.random.default_rng(3)
    x = 0.2 * np.sin(2 * np.pi * 220 * t) + 0.05 * rng.standard_normal(t.size)
    sf.write(str(path), np.stack([x, 0.9 * x], axis=1).astype(np.float32), sr, subtype="FLOAT")
    return path


class _Run:
    def __init__(self, tmp: Path, cuda: bool = True, lease: bool = True, **flags):
        self.tmp = tmp
        self.log = tmp / "gpu.log"
        self.env = {**os.environ,
                    "PYTHONPATH": str(_fakes(tmp)),
                    "GPU_LEASE_HOME": str(_lease_home(tmp) if lease else tmp),
                    "FAKE_GPU_LOG": str(self.log),
                    "FAKE_CUDA": "1" if cuda else "0",
                    "PYTHONIOENCODING": "utf-8"}
        self.env.update({k: str(v) for k, v in flags.items()})

    def separate(self, out: str = "out"):
        song = _song(self.tmp / "song.wav")
        r = subprocess.run([sys.executable, str(RUNNER), "separate", str(song), "--model", "htdemucs",
                            "--device", "auto", "--out", str(self.tmp / out)],
                           capture_output=True, text=True, env=self.env, timeout=120)
        events = [json.loads(ln) for ln in r.stdout.splitlines() if ln.startswith("{")]
        return r.returncode, events

    def log_lines(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []


# ── The hook itself ──────────────────────────────────────────────────────

def test_no_lease_library_means_a_no_op_and_no_import(tmp_path, monkeypatch):
    monkeypatch.setenv("GPU_LEASE_HOME", str(tmp_path))          # a folder without gpu_lease.py
    sys.modules.pop("gpu_lease", None)
    assert not gpu_lease_hook.available()
    assert isinstance(gpu_lease_hook.gpu_lease("stems", 4), contextlib.nullcontext)
    assert "gpu_lease" not in sys.modules


def test_the_default_folder_is_used_only_when_it_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("GPU_LEASE_HOME", raising=False)
    monkeypatch.setattr(gpu_lease_hook, "DEFAULT_HOME", str(tmp_path / "missing"))
    assert isinstance(gpu_lease_hook.gpu_lease("stems", 4), contextlib.nullcontext)


def test_with_the_library_it_returns_its_lease_for_shimmer(tmp_path, monkeypatch):
    monkeypatch.setenv("GPU_LEASE_HOME", str(_lease_home(tmp_path)))
    monkeypatch.setenv("FAKE_GPU_LOG", str(tmp_path / "gpu.log"))
    sys.modules.pop("gpu_lease", None)
    try:
        with gpu_lease_hook.gpu_lease("stem split", 4) as lease:
            assert lease.tool == "Shimmer" and lease.vram_gb == 4.0
        assert (tmp_path / "gpu.log").read_text(encoding="utf-8").splitlines() == [
            "ACQUIRE Shimmer | stem split | 4.0", "RELEASE"]
    finally:
        sys.modules.pop("gpu_lease", None)
        if str(tmp_path / "GpuLease") in sys.path:
            sys.path.remove(str(tmp_path / "GpuLease"))


# ── The stem split ───────────────────────────────────────────────────────

def test_the_split_holds_the_lease_while_on_the_gpu(tmp_path):
    run = _Run(tmp_path)
    rc, events = run.separate()
    assert rc == 0
    assert run.log_lines() == ["ACQUIRE Shimmer | stem split (htdemucs) | 4.0", "APPLY cuda",
                               "MODEL_CPU", "EMPTY_CACHE", "RELEASE"]
    # The wait is shown in the app, as the agreement asks.
    assert any(e.get("event") == "status" and "Waiting for the GPU lease" in e.get("message", "")
               for e in events)
    assert {p.name for p in (tmp_path / "out").glob("*.wav")} == {"drums.wav", "bass.wav", "other.wav", "vocals.wav"}


def test_without_the_library_the_split_is_exactly_as_before(tmp_path):
    with_lease, without = tmp_path / "a", tmp_path / "b"
    with_lease.mkdir(); without.mkdir()
    a, b = _Run(with_lease), _Run(without, lease=False)
    assert a.separate()[0] == 0 and b.separate()[0] == 0
    # No lease, and none of the clean-up the lease asks for.
    assert b.log_lines() == ["APPLY cuda"]
    for name in ("drums", "bass", "other", "vocals"):
        x, _ = sf.read(str(with_lease / "out" / f"{name}.wav"))
        y, _ = sf.read(str(without / "out" / f"{name}.wav"))
        assert np.array_equal(x, y)


def test_a_split_on_the_cpu_takes_no_lease(tmp_path):
    run = _Run(tmp_path, cuda=False)
    assert run.separate()[0] == 0
    assert run.log_lines() == ["APPLY cpu"]


def test_the_lease_goes_back_before_the_cpu_fallback(tmp_path):
    run = _Run(tmp_path, FAKE_OOM=1)
    assert run.separate()[0] == 0
    assert run.log_lines() == ["ACQUIRE Shimmer | stem split (htdemucs) | 4.0",
                               "APPLY cuda", "EMPTY_CACHE",           # out of memory: smaller segments
                               "APPLY cuda", "EMPTY_CACHE",           # still out: the CPU
                               "MODEL_CPU", "EMPTY_CACHE", "RELEASE",
                               "APPLY cpu"]


def test_the_lease_goes_back_when_the_split_fails(tmp_path):
    run = _Run(tmp_path, FAKE_FAIL=1)
    rc, events = run.separate()
    assert rc == 5
    assert any(e.get("event") == "error" for e in events)
    assert run.log_lines()[-3:] == ["MODEL_CPU", "EMPTY_CACHE", "RELEASE"]
    assert run.log_lines()[0].startswith("ACQUIRE Shimmer")


# ── Mastering: a fix that needs the vocal splits through the same runner ─

def test_a_vocal_mode_fix_in_mastering_takes_the_lease(tmp_path, monkeypatch):
    import importlib

    from shimmer import core
    from shimmer.api import render as api_render
    core_render = importlib.import_module("shimmer.core.render")   # the module; core.render is the function

    run = _Run(tmp_path)
    for k in ("PYTHONPATH", "GPU_LEASE_HOME", "FAKE_GPU_LOG", "FAKE_CUDA"):
        monkeypatch.setenv(k, run.env[k])
    monkeypatch.setenv("SHIMMER_STEMS_PYTHON", sys.executable)
    monkeypatch.setenv("TORCH_HOME", str(tmp_path / "torch-home"))
    monkeypatch.setattr(stems, "STEM_CACHE", tmp_path / "stem_cache")
    monkeypatch.setitem(stems._ENV_STATE, "checked", False)
    monkeypatch.setattr(core_render, "_VOCAL_SPLITTER", api_render.remix_vocal)

    song = _song(tmp_path / "song.wav", seconds=3.0)
    out = core.render(core.Source.load(str(song)),
                      core.Settings(fixes={"grain": 0.5}, fix_modes={"grain": "vocal"}))
    assert np.isfinite(out.audio).all()
    lines = run.log_lines()
    assert lines[0].startswith("ACQUIRE Shimmer | stem split (")
    assert "APPLY cuda" in lines
    assert lines[-1] == "RELEASE"
