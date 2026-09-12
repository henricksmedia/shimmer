"""Reading and writing audio files. Nothing else in the engine touches files.

Ported from shimmer/audio_io.py (load/save only), with three fixes:

- **MP3 and M4A are encoded from 32-bit float.** The old path wrote a 16-bit
  temp file with no dither before handing it to ffmpeg, which truncated
  every lossy export to 16 bits.
- **Mono stays mono.** The old ffmpeg decode forced two channels.
- **A sample rate that cannot be read is an error.** The old decode guessed
  44.1 kHz when ffprobe failed, which would play a 48 kHz song too slowly.

Which subtype, codec and bitrate a format uses is decided by the caller
(shimmer.core.export, from shimmer.core.catalog.FORMATS), not here.
"""
from __future__ import annotations

import io as _bytesio
import json
import os
import shutil
import subprocess
import tempfile
from fractions import Fraction
from typing import Optional, Tuple

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SOUNDFILE_EXTS = {".wav", ".flac", ".ogg", ".aiff", ".aif"}
FFMPEG_EXTS = {".mp3", ".m4a", ".aac", ".mp4"}
_FFMPEG_CODEC = {".mp3": ("libmp3lame", "mp3"), ".m4a": ("aac", "mp4"),
                 ".aac": ("aac", "adts"), ".mp4": ("aac", "mp4")}


class AudioIOError(RuntimeError):
    """A file could not be read or written."""


def _tool(name: str) -> str:
    return shutil.which(name) or name


def _as_2d(y: np.ndarray) -> np.ndarray:
    a = np.asarray(y)
    return a[:, None] if a.ndim == 1 else a


# ── Reading ─────────────────────────────────────────────────────────────

def _probe(path: str) -> Tuple[int, int]:
    """(sample rate, channels) of the first audio stream, via ffprobe."""
    cmd = [_tool("ffprobe"), "-v", "error", "-select_streams", "a:0",
           "-show_entries", "stream=sample_rate,channels", "-of", "json", path]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True, timeout=60).stdout
        stream = json.loads(out.decode("utf-8"))["streams"][0]
        return int(stream["sample_rate"]), int(stream["channels"])
    except FileNotFoundError as e:
        raise AudioIOError("ffmpeg is needed for MP3 and M4A files. Install ffmpeg "
                           "and add it to PATH.") from e
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            KeyError, IndexError, ValueError) as e:
        raise AudioIOError(f"Could not read the audio format of '{path}'.") from e


def _ffmpeg_decode(path: str) -> Tuple[np.ndarray, int]:
    sr, channels = _probe(path)
    cmd = [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error",
           "-i", path, "-f", "f32le", "-acodec", "pcm_f32le",
           "-ac", str(channels), "-ar", str(sr), "pipe:1"]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True, timeout=600)
    except FileNotFoundError as e:
        raise AudioIOError("ffmpeg is needed for MP3 and M4A files. Install ffmpeg "
                           "and add it to PATH.") from e
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace")
        raise AudioIOError(f"Could not decode '{path}'.\n{err}") from e
    raw = np.frombuffer(proc.stdout, dtype=np.float32)
    if raw.size == 0 or raw.size % channels:
        raise AudioIOError(f"ffmpeg returned no usable audio for '{path}'.")
    return raw.reshape(-1, channels).copy(), sr


def load(path) -> Tuple[np.ndarray, int]:
    """Read a file as float32, shape (samples, channels), and its sample rate.

    WAV, FLAC, OGG and AIFF are read directly; MP3, M4A and AAC through
    ffmpeg. Any other extension is tried directly first, then via ffmpeg.
    """
    path = os.fspath(path)
    ext = os.path.splitext(path)[1].lower()
    if ext not in FFMPEG_EXTS:
        try:
            x, sr = sf.read(path, always_2d=True, dtype="float32")
            return x, int(sr)
        except Exception as e:                             # noqa: BLE001
            if ext in SOUNDFILE_EXTS:
                raise AudioIOError(f"Could not read '{path}': {e}") from e
    return _ffmpeg_decode(path)


# ── Writing ─────────────────────────────────────────────────────────────

def save(path, y: np.ndarray, sr: int, subtype: str = "PCM_24",
         bitrate: Optional[str] = None) -> None:
    """Write audio, choosing the writer by extension.

    subtype  for WAV, FLAC and AIFF ("PCM_24", "PCM_16", "FLOAT"). OGG is
             always Vorbis. Dither is the caller's job: this writes the
             samples it is given.
    bitrate  for MP3 and M4A, e.g. "320k". None uses the codec's default.
    """
    path = os.fspath(path)
    ext = os.path.splitext(path)[1].lower()
    a = _as_2d(np.asarray(y, dtype=np.float32))
    if ext == ".ogg":
        sf.write(path, a, int(sr), format="OGG", subtype="VORBIS")
        return
    if ext in SOUNDFILE_EXTS:
        sf.write(path, a, int(sr), subtype=subtype)
        return
    if ext not in _FFMPEG_CODEC:
        raise AudioIOError(f"Cannot write '{ext}' files.")
    codec, container = _FFMPEG_CODEC[ext]
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        # 32-bit float in, so the encoder sees every bit the engine made.
        sf.write(tmp, a, int(sr), subtype="FLOAT")
        cmd = [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-i", tmp, "-c:a", codec]
        if bitrate:
            cmd += ["-b:a", bitrate]
        cmd += ["-f", container, path]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=600)
        except FileNotFoundError as e:
            raise AudioIOError("ffmpeg is needed to write MP3 and M4A. Install ffmpeg "
                               "and add it to PATH.") from e
        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode("utf-8", errors="replace")
            raise AudioIOError(f"Could not write '{path}'.\n{err}") from e
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def wav_bytes(y: np.ndarray, sr: int, subtype: str = "PCM_16") -> bytes:
    """An in-memory WAV, for previews that never touch the disk."""
    buf = _bytesio.BytesIO()
    sf.write(buf, _as_2d(np.asarray(y, dtype=np.float32)), int(sr), format="WAV",
             subtype=subtype)
    return buf.getvalue()


# ── Sample rate ─────────────────────────────────────────────────────────

def resample(x: np.ndarray, sr: int, target_sr: Optional[int]) -> Tuple[np.ndarray, int]:
    """Change the sample rate with a polyphase filter. A no-op when there is
    no target or the rate already matches. Returns float64."""
    a = np.asarray(x, dtype=np.float64)
    if not target_sr or int(target_sr) == int(sr):
        return a, int(sr)
    frac = Fraction(int(target_sr), int(sr)).limit_denominator(1000)
    y = resample_poly(_as_2d(a), frac.numerator, frac.denominator, axis=0, padtype="line")
    return (y if a.ndim == 2 else y[:, 0]), int(target_sr)
