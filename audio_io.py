"""
audio_io.py — Audio file I/O, measurements, and volume management.

Provides format-agnostic load/save for WAV / FLAC / OGG (via soundfile) and
MP3 / M4A / AAC (via pydub + system ffmpeg).  The engine never touches the
filesystem.
"""

from __future__ import annotations

import io
import os
from typing import Dict, Any, Optional, Callable, Tuple

import numpy as np
import soundfile as sf

from dsp import as_2d, lin_to_db
from params import Params
from engine import process


# Extensions soundfile handles natively (depends on libsndfile version,
# but these are always supported).
_SOUNDFILE_EXTS = {".wav", ".flac", ".ogg", ".aiff", ".aif"}

# Extensions that require ffmpeg (via pydub).
_FFMPEG_EXTS = {".mp3", ".m4a", ".aac", ".mp4"}


class AudioIOError(RuntimeError):
    """Raised when an audio file cannot be read or written."""


# ---------------------------------------------------------------------------
# Lazy pydub import (optional dependency)
# ---------------------------------------------------------------------------

def _import_pydub():
    try:
        from pydub import AudioSegment
        return AudioSegment
    except ImportError as e:
        raise AudioIOError(
            "pydub is required for MP3/M4A support. "
            "Install with: pip install pydub. Also requires ffmpeg on PATH."
        ) from e


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_audio(path: str) -> Tuple[np.ndarray, int]:
    """Load an audio file as float32 (samples, channels) and sample rate.

    Tries soundfile first (WAV/FLAC/OGG/AIFF; MP3 works on libsndfile >= 1.1).
    Falls back to pydub + ffmpeg for MP3/M4A/AAC.
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in _SOUNDFILE_EXTS or ext not in _FFMPEG_EXTS:
        try:
            x, sr = sf.read(path, always_2d=True)
            return x.astype(np.float32, copy=False), int(sr)
        except Exception:
            if ext in _SOUNDFILE_EXTS:
                raise

    AudioSegment = _import_pydub()
    try:
        seg = AudioSegment.from_file(path)
    except Exception as e:
        raise AudioIOError(
            f"Failed to decode '{path}'. If this is an MP3/M4A file, ensure "
            f"ffmpeg is installed and on PATH.\nUnderlying error: {e}"
        ) from e

    sr = int(seg.frame_rate)
    channels = int(seg.channels)
    sample_width = int(seg.sample_width)  # bytes per sample
    raw = seg.get_array_of_samples()
    # pydub uses signed int samples; scale to [-1, 1].
    max_val = float(1 << (8 * sample_width - 1))
    x = np.asarray(raw, dtype=np.float32) / max_val
    if channels > 1:
        x = x.reshape(-1, channels)
    else:
        x = x.reshape(-1, 1)
    return x, sr


# ---------------------------------------------------------------------------
# Saving
# ---------------------------------------------------------------------------

def save_audio(path: str, y: np.ndarray, sr: int,
               subtype: str = "PCM_24",
               mp3_bitrate: str = "320k") -> None:
    """Write audio to `path`, dispatching on file extension.

    WAV / FLAC / OGG / AIFF → soundfile with the given `subtype`.
    MP3 / M4A / AAC → pydub + ffmpeg at `mp3_bitrate`.
    """
    ext = os.path.splitext(path)[1].lower()
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 1:
        y = y[:, None]

    if ext in _SOUNDFILE_EXTS or ext not in _FFMPEG_EXTS:
        sf.write(path, y, sr, subtype=subtype)
        return

    AudioSegment = _import_pydub()
    # pydub needs int16 PCM in memory.  Encode as WAV bytes and re-wrap.
    y_clip = np.clip(y, -1.0, 1.0)
    y_i16 = (y_clip * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    sf.write(buf, y_i16, sr, format="WAV", subtype="PCM_16")
    buf.seek(0)
    seg = AudioSegment.from_file(buf, format="wav")
    fmt = "mp4" if ext == ".m4a" else ext.lstrip(".")
    try:
        seg.export(path, format=fmt, bitrate=mp3_bitrate)
    except Exception as e:
        raise AudioIOError(
            f"Failed to write '{path}'. Ensure ffmpeg is installed and on "
            f"PATH.\nUnderlying error: {e}"
        ) from e


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
    """Scale output to preserve perceived loudness.

    If `input_rms` is provided, scales the output so its broadband RMS
    matches the input RMS (loudness-match), then clamps the scale so the
    output peak never exceeds `peak_ceiling`. This is the right knob
    when stages remove substantial energy from a band the original peak
    didn't live in (e.g. shimmer in 5-12 kHz while peaks are set by a
    kick / vocal): peak-match alone leaves the file sounding quieter
    because total RMS dropped but the peak didn't.

    If `input_rms` is None, falls back to the legacy peak-match
    behaviour for backwards compatibility.

    `max_scale` is a safety clamp on how much amplification is allowed
    (4x = +12 dB) to prevent runaway boosts on near-silent outputs.
    """
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
        # Don't let the boost push the peak above the ceiling — preserve
        # loudness up to the point where it would clip, then back off.
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
) -> Dict[str, Any]:
    """Read an audio file, process it, write the result.

    Input may be WAV / FLAC / OGG / AIFF / MP3 / M4A / AAC.
    Output format is inferred from `output_path` extension.
    """
    x, sr = load_audio(input_path)

    meas_in = measure(x)
    y = process(x, sr, params, progress_callback=progress_callback)
    y2 = as_2d(y)

    if do_preserve_volume:
        y2 = preserve_volume(
            y2, meas_in["peak_linear"], input_rms=meas_in["rms_linear"])
    y2 = clip_protect(y2)

    save_audio(output_path, y2, sr, subtype=subtype, mp3_bitrate=mp3_bitrate)

    if write_diff:
        diff = (x[:y2.shape[0], :] - y2).astype(np.float32)
        save_audio(write_diff, diff, sr, subtype=subtype, mp3_bitrate=mp3_bitrate)

    meas_out = measure(y2)

    return {
        "sr": sr,
        "channels": x.shape[1],
        "duration_s": float(x.shape[0] / sr),
        "input": meas_in,
        "output": meas_out,
    }
