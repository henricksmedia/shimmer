"""
Final-master loudness: the exported file lands on the loudness target.

master() sets loudness with one static gain, then takes the peaks down
with a soft shaper and a true-peak limiter. Whatever those two remove
comes straight out of the integrated loudness, so the target is only
"hit" when that loss stays small — and the file on disk (PCM_24 WAV, MP3
through ffmpeg, the silence-trimmed export variant) must measure the same
as the in-memory report the UI shows.

Measured 2026-09-05 on an 8 s music-like source with a 10 dB
peak-to-loudness ratio (the shape of Suno output, which sits near -14 LUFS
with 3-5 dB of headroom): every target within 0.02 LU, WAV and MP3.
On a dense source with a 17 dB ratio the same chain lands about 0.4 LU low
at -14, 0.9 LU low at -11 and 1.2 LU low at -9; the shortfall is never
compensated, but it is reported as `lufs_error`.

Real tracks: set SHIMMER_REAL_TRACKS=1 to run the last test on
testing/*.wav and assets/reference/*.wav (slow, about 3 min), or run
diag_final_master.py for the full on-disk matrix.

Run:  .venv\\Scripts\\python.exe -m pytest tests/test_master_loudness.py -q
"""

from __future__ import annotations

import glob
import os
import shutil
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.audio_io import load_audio, process_file, save_audio  # noqa: E402
from shimmer.dsp import trim_silence  # noqa: E402
from shimmer.mastering import (  # noqa: E402
    get_export_ceiling_dbtp,
    master,
    measure_loudness,
)
from shimmer.params import LOUDNESS_TARGETS, MasterParams  # noqa: E402
from shimmer.presets import get_preset  # noqa: E402

SR = 44100
TARGETS = sorted(LOUDNESS_TARGETS.values())   # -14, -11, -9
LOSSLESS_CEILING = get_export_ceiling_dbtp("wav")   # -1.0 dBTP
TP_SLACK_DB = 0.05                            # true-peak measurement slack
HAS_FFMPEG = shutil.which("ffmpeg") is not None
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REAL_TRACKS = sorted(glob.glob(os.path.join(_ROOT, "testing", "*.wav"))
                      + glob.glob(os.path.join(_ROOT, "assets", "reference", "*.wav")))


def _headroom_source(seconds: float = 8.0, seed: int = 1,
                     peak: float = 0.5) -> np.ndarray:
    """Music-like stereo bed with a 120 bpm kick, peaks at -6 dBFS,
    peak-to-loudness ratio about 10 dB: what a Suno master looks like."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    bed = (0.5 * np.sin(2 * np.pi * 110 * t) + 0.25 * np.sin(2 * np.pi * 220 * t)
           + 0.15 * np.sin(2 * np.pi * 440 * t) + 0.08 * np.sin(2 * np.pi * 1760 * t))
    bed += 0.05 * rng.standard_normal(n)
    beat = (t * 2.0) % 1.0
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-beat * 12.0)
    x = 0.6 * bed + 0.8 * kick
    left = x + 0.03 * rng.standard_normal(n)
    right = x + 0.03 * rng.standard_normal(n)
    y = np.stack([left, right], axis=1)
    y = y / np.max(np.abs(y)) * peak
    return y.astype(np.float32)


def _dense_source(seconds: float = 8.0, seed: int = 3,
                  peak: float = 0.9) -> np.ndarray:
    """Sustained loud section with a hot noise snare, peaks near -1 dBFS,
    peak-to-loudness ratio about 17 dB: the loudness lives where the
    peaks are, so peak control costs loudness."""
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.arange(n) / SR
    bed = (0.5 * np.sin(2 * np.pi * 82 * t) + 0.4 * np.sin(2 * np.pi * 164 * t)
           + 0.3 * np.sin(2 * np.pi * 330 * t) + 0.2 * np.sin(2 * np.pi * 660 * t)
           + 0.15 * np.sin(2 * np.pi * 1320 * t))
    bed += 0.15 * rng.standard_normal(n)
    beat = (t * 2.0) % 1.0
    snare_beat = (t * 2.0 + 0.5) % 1.0
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-beat * 15.0)
    snare = rng.standard_normal(n) * np.exp(-snare_beat * 25.0)
    x = 0.5 * bed + 0.9 * kick + 0.9 * snare
    y = np.stack([x + 0.03 * rng.standard_normal(n),
                  x + 0.03 * rng.standard_normal(n)], axis=1)
    y = y / np.max(np.abs(y)) * peak
    return y.astype(np.float32)


def _mp(target: float, fmt: str = "wav") -> MasterParams:
    """MasterParams the way the server builds them for an export: the
    user's target plus the codec-aware ceiling for the output format."""
    return MasterParams(enabled=True, target_lufs=float(target),
                        ceiling_dbtp=get_export_ceiling_dbtp(fmt))


# ── In memory ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", TARGETS)
def test_headroom_source_hits_every_target(target):
    x = _headroom_source()
    y, rep = master(x, SR, _mp(target))
    after = measure_loudness(y, SR)
    assert abs(after["lufs_i"] - target) <= 0.1, after
    assert after["true_peak_dbtp"] <= LOSSLESS_CEILING + TP_SLACK_DB, after
    # The report the UI shows is the same measurement.
    assert abs(rep["after"]["lufs_i"] - after["lufs_i"]) < 1e-6
    assert abs(rep["lufs_error"] - (after["lufs_i"] - target)) < 1e-6
    assert abs(rep["target_lufs"] - target) < 1e-9


@pytest.mark.parametrize("target", TARGETS)
def test_dense_source_shortfall_is_bounded_and_reported(target):
    """A source whose loudness sits in its peaks cannot reach the target
    without the limiter taking some of it back. The chain never
    overshoots, keeps the true-peak ceiling under heavy gain reduction,
    reports the real shortfall, and on this 17 dB PLR source stays within
    1.5 LU of the target (1.2 LU measured at -9)."""
    x = _dense_source()
    y, rep = master(x, SR, _mp(target))
    after = measure_loudness(y, SR)
    err = after["lufs_i"] - target
    assert err <= 0.05, rep["lufs_error"]
    assert err >= -1.5, rep["lufs_error"]
    assert after["true_peak_dbtp"] <= LOSSLESS_CEILING + TP_SLACK_DB, after
    assert rep["limiter_gain_reduction"] < 0.0   # the limiter really worked
    assert abs(rep["lufs_error"] - err) < 1e-6


# ── On disk: the file the user downloads ─────────────────────────────────

def test_wav_export_measures_like_the_report(tmp_path):
    x = _headroom_source()
    y, rep = master(x, SR, _mp(-9.0))
    path = tmp_path / "master.wav"
    save_audio(str(path), y, SR)          # PCM_24, the server's export call
    z, sr = load_audio(str(path))
    disk = measure_loudness(z, sr)
    assert sr == SR
    assert abs(disk["lufs_i"] - rep["after"]["lufs_i"]) <= 0.05
    assert abs(disk["true_peak_dbtp"] - rep["after"]["true_peak_dbtp"]) <= 0.05
    assert abs(disk["lufs_i"] - (-9.0)) <= 0.1


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not on PATH")
@pytest.mark.parametrize("target", TARGETS)
def test_mp3_export_stays_on_target(tmp_path, target):
    x = _headroom_source()
    mp = _mp(target, "mp3")
    assert mp.ceiling_dbtp == -1.5
    y, rep = master(x, SR, mp)
    path = tmp_path / "master.mp3"
    save_audio(str(path), y, SR)
    z, sr = load_audio(str(path))
    disk = measure_loudness(z, sr)
    assert abs(disk["lufs_i"] - target) <= 0.3, disk
    # Decoder overshoot has to fit inside the extra 0.5 dB the lossy
    # ceiling reserves: the decoded file still sits under -1 dBTP.
    assert disk["true_peak_dbtp"] <= LOSSLESS_CEILING + TP_SLACK_DB, disk


def test_silence_trimmed_export_keeps_the_target():
    x = _headroom_source()
    pad = np.zeros((int(2.0 * SR), 2), dtype=np.float32)
    padded = np.concatenate([pad, x, pad], axis=0)
    y, rep = master(padded, SR, _mp(-11.0))
    y_trim, cut_head, cut_tail = trim_silence(y, SR)
    assert cut_head > 1.5 and cut_tail > 1.5
    trimmed = measure_loudness(y_trim, SR)
    assert abs(trimmed["lufs_i"] - rep["after"]["lufs_i"]) <= 0.1
    assert abs(trimmed["lufs_i"] - (-11.0)) <= 0.15


@pytest.mark.parametrize("fmt", ["wav"] + (["mp3"] if HAS_FFMPEG else []))
def test_full_pipeline_export_lands_on_target(tmp_path, fmt):
    """process_file() is the CLI / batch export: cleaning, tone curve,
    mastering and the codec write in one call."""
    src = tmp_path / "src.wav"
    save_audio(str(src), _headroom_source(seconds=6.0), SR)
    out = tmp_path / f"out.{fmt}"
    mp = _mp(-14.0, fmt)
    result = process_file(str(src), str(out), get_preset("generic"),
                          master_params=mp, static_repair=False)
    z, sr = load_audio(str(out))
    disk = measure_loudness(z, sr)
    assert abs(disk["lufs_i"] - (-14.0)) <= 0.3, disk
    assert disk["true_peak_dbtp"] <= LOSSLESS_CEILING + TP_SLACK_DB, disk
    rep = result["mastering"]
    assert rep["enabled"] and abs(rep["target_lufs"] - (-14.0)) < 1e-9
    assert abs(rep["after"]["lufs_i"] - disk["lufs_i"]) <= (0.3 if fmt == "mp3" else 0.05)


# ── Real tracks (opt-in, slow) ───────────────────────────────────────────

@pytest.mark.skipif(not os.environ.get("SHIMMER_REAL_TRACKS") or not _REAL_TRACKS,
                    reason="set SHIMMER_REAL_TRACKS=1 with tracks in testing/ (slow)")
@pytest.mark.parametrize("path", _REAL_TRACKS,
                         ids=[os.path.basename(p) for p in _REAL_TRACKS])
@pytest.mark.parametrize("target", TARGETS)
def test_real_track_hits_target(path, target):
    x, sr = load_audio(path)
    _, rep = master(x, sr, _mp(target))
    after = rep["after"]
    assert abs(after["lufs_i"] - target) <= 0.5, rep["lufs_error"]
    assert after["true_peak_dbtp"] <= LOSSLESS_CEILING + TP_SLACK_DB, after
