"""
audio_io.py — Audio file I/O, measurements, and volume management.

Provides format-agnostic load/save for WAV / FLAC / OGG (via soundfile) and
MP3 / M4A / AAC (via ffmpeg subprocess).  The engine never touches the
filesystem.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from typing import Dict, Any, Optional, Callable, Tuple

import numpy as np
import soundfile as sf

from dsp import as_2d, lin_to_db, trim_silence as dsp_trim_silence
from params import Params, MasterParams
from engine import process
from mastering import master, master_params_from_json, tpdf_dither


# Extensions soundfile handles natively (depends on libsndfile version,
# but these are always supported).
_SOUNDFILE_EXTS = {".wav", ".flac", ".ogg", ".aiff", ".aif"}

# Extensions that require ffmpeg.
_FFMPEG_EXTS = {".mp3", ".m4a", ".aac", ".mp4"}


class AudioIOError(RuntimeError):
    """Raised when an audio file cannot be read or written."""


def _ffmpeg_path() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def _ffmpeg_decode(path: str) -> Tuple[np.ndarray, int]:
    """Decode arbitrary audio to float32 stereo/mono via ffmpeg pipe."""
    ffmpeg = _ffmpeg_path()
    cmd = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", path,
        "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, check=True, timeout=600)
    except FileNotFoundError as e:
        raise AudioIOError(
            "ffmpeg is required for MP3/M4A support. Install ffmpeg and add it to PATH."
        ) from e
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace")
        raise AudioIOError(
            f"Failed to decode '{path}' with ffmpeg.\n{err}"
        ) from e

    raw = np.frombuffer(proc.stdout, dtype=np.float32)
    if raw.size == 0:
        raise AudioIOError(f"ffmpeg returned no audio data for '{path}'")
    # Probe channel layout from ffprobe if possible; default stereo interleaved.
    n_ch = 2
    if raw.size % n_ch != 0:
        n_ch = 1
    if n_ch > 1:
        x = raw.reshape(-1, n_ch)
    else:
        x = raw.reshape(-1, 1)
    # Sample rate via ffprobe.
    sr = _ffprobe_sample_rate(path)
    return x.astype(np.float32, copy=False), int(sr)


def _ffprobe_sample_rate(path: str) -> int:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    cmd = [
        ffprobe, "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=30)
        return int(float(out.decode().strip()))
    except Exception:
        return 44100


def _ffmpeg_encode(path: str, y: np.ndarray, sr: int,
                   fmt: str, bitrate: str = "320k") -> None:
    """Encode float32 audio to MP3/M4A via ffmpeg."""
    ffmpeg = _ffmpeg_path()
    y = as_2d(np.asarray(y, dtype=np.float32))
    y_clip = np.clip(y, -1.0, 1.0)
    n_ch = y_clip.shape[1]

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        sf.write(tmp_path, y_clip, sr, subtype="PCM_16")
        ext = os.path.splitext(path)[1].lower()
        out_fmt = "mp4" if ext == ".m4a" else fmt
        cmd = [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", tmp_path,
            "-ac", str(n_ch),
        ]
        if out_fmt in ("mp3",):
            cmd += ["-b:a", bitrate]
        cmd += [path]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=600)
        except FileNotFoundError as e:
            raise AudioIOError(
                "ffmpeg is required for MP3/M4A export. Install ffmpeg and add it to PATH."
            ) from e
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", errors="replace")
            raise AudioIOError(
                f"Failed to write '{path}' with ffmpeg.\n{err}"
            ) from e
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_audio(path: str) -> Tuple[np.ndarray, int]:
    """Load an audio file as float32 (samples, channels) and sample rate.

    Tries soundfile first (WAV/FLAC/OGG/AIFF; MP3 works on libsndfile >= 1.1).
    Falls back to ffmpeg for MP3/M4A/AAC.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in _SOUNDFILE_EXTS or ext not in _FFMPEG_EXTS:
        try:
            x, sr = sf.read(path, always_2d=True)
            return x.astype(np.float32, copy=False), int(sr)
        except Exception:
            if ext in _SOUNDFILE_EXTS:
                raise

    return _ffmpeg_decode(path)


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def save_audio(path: str, y: np.ndarray, sr: int,
               subtype: str = "PCM_24",
               mp3_bitrate: str = "320k",
               dither: bool = False) -> None:
    """Write audio to `path`, dispatching on file extension.

    WAV / FLAC / OGG / AIFF → soundfile with the given `subtype`.
    MP3 / M4A / AAC → ffmpeg at `mp3_bitrate`.
    When `dither` is True and subtype is PCM_16, applies TPDF dither.
    """
    ext = os.path.splitext(path)[1].lower()
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 1:
        y = y[:, None]

    if dither and subtype.upper() in ("PCM_16", "PCM16"):
        y = tpdf_dither(y, bits=16)

    if ext in _SOUNDFILE_EXTS or ext not in _FFMPEG_EXTS:
        sf.write(path, y, sr, subtype=subtype)
        return

    fmt = "mp4" if ext == ".m4a" else ext.lstrip(".")
    _ffmpeg_encode(path, y, sr, fmt=fmt, bitrate=mp3_bitrate)


def encode_wav_bytes(y: np.ndarray, sr: int, subtype: str = "PCM_16") -> bytes:
    """Encode audio to an in-memory WAV. Used by the live-preview API so
    renders never touch the filesystem."""
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 1:
        y = y[:, None]
    buf = io.BytesIO()
    sf.write(buf, y, sr, format="WAV", subtype=subtype)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------

def measure(x: np.ndarray) -> Dict[str, float]:
    """Compute basic audio measurements on a (samples, channels) array."""
    x = as_2d(np.asarray(x, dtype=np.float32))
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x ** 2)))
    return {
        "peak_dbfs": float(lin_to_db(peak)),
        "rms_dbfs": float(lin_to_db(rms)),
        "peak_linear": peak,
        "rms_linear": rms,
    }


# ---------------------------------------------------------------------------
# Volume preservation
# ---------------------------------------------------------------------------

def preserve_volume(y: np.ndarray, input_peak: float,
                    input_rms: Optional[float] = None,
                    max_scale: float = 4.0,
                    peak_ceiling: float = 0.999) -> np.ndarray:
    """Scale output to preserve perceived loudness."""
    y = np.asarray(y, dtype=np.float32)
    if input_peak < 1e-6:
        return y
    output_peak = float(np.max(np.abs(y)))
    if output_peak < 1e-6:
        return y

    if input_rms is not None and input_rms > 1e-6:
        output_rms = float(np.sqrt(np.mean(y ** 2)))
        if output_rms < 1e-6:
            return y
        scale = float(input_rms / output_rms)
        peak_limit = peak_ceiling / output_peak
        if scale > peak_limit:
            scale = peak_limit
        scale = float(np.clip(scale, 1.0 / max_scale, max_scale))
        return (y * scale).astype(np.float32)

    scale = float(np.clip(input_peak / output_peak, 1.0 / max_scale, max_scale))
    return (y * scale).astype(np.float32)


def clip_protect(y: np.ndarray, ceiling: float = 0.999) -> np.ndarray:
    """Normalize to ceiling if any sample exceeds it."""
    peak = float(np.max(np.abs(y)))
    if peak > ceiling:
        return (y / peak * ceiling).astype(np.float32)
    return y


# ---------------------------------------------------------------------------
# File-level processing
# ---------------------------------------------------------------------------

def process_file(
    input_path: str,
    output_path: str,
    params: Params,
    write_diff: Optional[str] = None,
    do_preserve_volume: bool = True,
    subtype: str = "PCM_24",
    mp3_bitrate: str = "320k",
    progress_callback: Optional[Callable[[float], None]] = None,
    master_params: Optional[MasterParams] = None,
    mastering_analysis: Optional[Dict[str, Any]] = None,
    use_pipeline: bool = True,
    trim_silence: bool = False,
    eq_params: Optional["EqParams"] = None,
) -> Dict[str, Any]:
    """Read an audio file, process it, write the result.

    `use_pipeline=True` (default) runs the safe band-split/M-S pipeline:
    the low/mid body bypasses the STFT engine, only the high band is
    cleaned, and mastering is single-pass true-peak safe. Set False to
    fall back to the legacy full-mix engine.

    `eq_params` is the optional user parametric EQ (see eq.py), applied
    post-clean / pre-master inside the pipeline.
    """
    from engine import apply_post_filters

    x, sr = load_audio(input_path)

    meas_in = measure(x)
    mastering_report: Dict[str, Any] = {"enabled": False}
    use_mastering = master_params is not None and master_params.enabled

    if use_pipeline:
        from pipeline import clean_and_master

        y2, removed, pipe_report = clean_and_master(
            x, sr, params,
            master_params=master_params if use_mastering else None,
            progress_callback=progress_callback,
            raw_analysis=mastering_analysis,
            eq_params=eq_params,
        )
        mastering_report = pipe_report.get("mastering", {"enabled": False})

        if write_diff:
            save_audio(write_diff, removed, sr,
                       subtype=subtype, mp3_bitrate=mp3_bitrate)

        if not use_mastering and do_preserve_volume:
            y2 = preserve_volume(
                y2, meas_in["peak_linear"], input_rms=meas_in["rms_linear"])
            y2 = clip_protect(y2)

        trim_report: Dict[str, Any] = {"enabled": False}
        if trim_silence:
            y2, cut_head, cut_tail = dsp_trim_silence(y2, sr)
            trim_report = {
                "enabled": True,
                "cut_head_s": round(cut_head, 3),
                "cut_tail_s": round(cut_tail, 3),
            }

        use_dither = subtype.upper() in ("PCM_16", "PCM16")
        save_audio(
            output_path, y2, sr, subtype=subtype, mp3_bitrate=mp3_bitrate,
            dither=use_dither)

        meas_out = measure(y2)
        return {
            "sr": sr,
            "channels": x.shape[1],
            "duration_s": float(x.shape[0] / sr),
            "input": meas_in,
            "output": meas_out,
            "mastering": mastering_report,
            "trim": trim_report,
            "pipeline": {
                "tone_curve_db": pipe_report.get("tone_curve_db", []),
                "side_width_compensation": pipe_report.get(
                    "side_width_compensation", {}),
            },
        }

    # ── Legacy full-mix engine path ───────────────────────────────────────
    y = process(x, sr, params, progress_callback=progress_callback)
    y2 = as_2d(y)

    if write_diff:
        n = min(x.shape[0], y2.shape[0])
        x_ref = apply_post_filters(x[:n, :].astype(np.float32), sr, params)
        diff = (x_ref - y2[:n, :]).astype(np.float32)
        save_audio(write_diff, diff, sr, subtype=subtype, mp3_bitrate=mp3_bitrate)

    if use_mastering:
        y2, mastering_report = master(
            y2, sr, master_params, analysis=mastering_analysis)
    elif do_preserve_volume:
        y2 = preserve_volume(
            y2, meas_in["peak_linear"], input_rms=meas_in["rms_linear"])
        y2 = clip_protect(y2)

    trim_report = {"enabled": False}
    if trim_silence:
        y2, cut_head, cut_tail = dsp_trim_silence(y2, sr)
        trim_report = {
            "enabled": True,
            "cut_head_s": round(cut_head, 3),
            "cut_tail_s": round(cut_tail, 3),
        }

    use_dither = subtype.upper() in ("PCM_16", "PCM16")
    save_audio(
        output_path, y2, sr, subtype=subtype, mp3_bitrate=mp3_bitrate,
        dither=use_dither)

    meas_out = measure(y2)

    return {
        "sr": sr,
        "channels": x.shape[1],
        "duration_s": float(x.shape[0] / sr),
        "input": meas_in,
        "output": meas_out,
        "mastering": mastering_report,
        "trim": trim_report,
    }
