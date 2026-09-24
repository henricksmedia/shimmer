"""Reading and writing audio files. Nothing else in the engine touches files.

Ported from shimmer/audio_io.py (load/save only), with four fixes:

- **OGG export no longer crashes.** libsndfile's Vorbis encoder overflows
  the stack when given a long song in one write call, which killed the
  whole process. Files are now written a block at a time.

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

import hashlib
import io as _bytesio
import json
import os
import shutil
import subprocess
import tempfile
from fractions import Fraction
from functools import lru_cache
from typing import List, Optional, Tuple

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SOUNDFILE_EXTS = {".wav", ".flac", ".ogg", ".aiff", ".aif"}
FFMPEG_EXTS = {".mp3", ".m4a", ".aac", ".mp4"}
_FFMPEG_CODEC = {".mp3": ("libmp3lame", "mp3"), ".m4a": ("aac", "mp4"),
                 ".aac": ("aac", "adts"), ".mp4": ("aac", "mp4")}
_WRITE_BLOCK = 1 << 14    # frames per libsndfile write call


class AudioIOError(RuntimeError):
    """A file could not be read or written."""


def _tool(name: str) -> str:
    return shutil.which(name) or name


# ffmpeg's built-in AAC encoder can drop a glitch into a loud master: one
# spot decoded 3.6 dB over the master, an audible pop, and turning the file
# down did not remove it (28 of 30 test songs were turned down, by up to
# 6.2 dB, and 3 still went over). The system's own AAC encoders had no such
# glitch on the same songs: macOS AudioToolbox and Windows Media Foundation.
# They take 44.1 and 48 kHz; other rates, or a build without them, use the
# built-in one.
_SYSTEM_AAC = ("aac_at", "aac_mf")
_SYSTEM_AAC_RATES = (44100, 48000)


@lru_cache(maxsize=1)
def _encoders() -> Tuple[str, ...]:
    try:
        out = subprocess.run([_tool("ffmpeg"), "-hide_banner", "-encoders"],
                             capture_output=True, timeout=30).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return ()
    return tuple(line.split()[1] for line in out.splitlines()
                 if len(line.split()) > 1 and line.split()[0].startswith("A"))


def _aac_encoders(sr: int) -> List[str]:
    """The AAC encoders to try, best first."""
    have = _encoders()
    first = [e for e in _SYSTEM_AAC if e in have] if int(sr) in _SYSTEM_AAC_RATES else []
    return first + ["aac"]


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


_BITS = {"PCM_S8": 8, "PCM_U8": 8, "PCM_16": 16, "PCM_24": 24, "PCM_32": 32,
         "FLOAT": 32, "DOUBLE": 64}


def bit_depth(path) -> Tuple[Optional[int], bool]:
    """(bits, is_float) of a PCM file, or (None, False) for a lossy file or
    one libsndfile cannot read. Reads the header only."""
    try:
        subtype = sf.info(os.fspath(path)).subtype or ""
    except Exception:                                      # noqa: BLE001
        return None, False
    return _BITS.get(subtype), subtype in ("FLOAT", "DOUBLE")


# ── Writing ─────────────────────────────────────────────────────────────

def _write_blocks(path: str, a: np.ndarray, sr: int, **fmt) -> None:
    """Write through libsndfile a block at a time. Its Vorbis encoder
    overflows the stack when handed a large buffer in one call: a 20 s
    stereo OGG crashed Python outright, with no error to catch."""
    with sf.SoundFile(path, "w", samplerate=int(sr), channels=a.shape[1], **fmt) as f:
        for s in range(0, a.shape[0], _WRITE_BLOCK):
            f.write(a[s:s + _WRITE_BLOCK])


def save(path, y: np.ndarray, sr: int, subtype: str = "PCM_24",
         bitrate: Optional[str] = None, quality: Optional[float] = None) -> None:
    """Write audio, choosing the writer by extension.

    subtype  for WAV, FLAC and AIFF ("PCM_24", "PCM_16", "FLOAT"). OGG is
             always Vorbis. Dither is the caller's job: this writes the
             samples it is given.
    bitrate  for MP3 and M4A, e.g. "320k". None uses the codec's default.
    quality  for OGG Vorbis, 0 (smallest) to 1 (best). None uses
             libsndfile's default.
    """
    path = os.fspath(path)
    ext = os.path.splitext(path)[1].lower()
    a = _as_2d(np.asarray(y, dtype=np.float32))
    if ext == ".ogg":
        fmt = {"format": "OGG", "subtype": "VORBIS"}
        if quality is not None:
            fmt["compression_level"] = 1.0 - min(1.0, max(0.0, float(quality)))
        _write_blocks(path, a, sr, **fmt)
        return
    if ext in SOUNDFILE_EXTS:
        if subtype == "PCM_16":
            # libsndfile 1.2.2 rounds float down when it writes 16-bit WAV
            # (FLAC it rounds to nearest), which adds 3 dB of noise and half
            # a step of DC (docs/CHAIN-AUDIT.md section 4). Round here, the
            # same way for every format, and hand it whole numbers.
            a = np.clip(np.round(a.astype(np.float64) * 32768.0), -32768, 32767).astype(np.int16)
        _write_blocks(path, a, sr, subtype=subtype)
        return
    if ext not in _FFMPEG_CODEC:
        raise AudioIOError(f"Cannot write '{ext}' files.")
    codec, container = _FFMPEG_CODEC[ext]
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        # 32-bit float in, so the encoder sees every bit the engine made.
        sf.write(tmp, a, int(sr), subtype="FLOAT")
        codecs = _aac_encoders(int(sr)) if codec == "aac" else [codec]
        for i, name in enumerate(codecs):
            cmd = [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                   "-i", tmp, "-c:a", name]
            if bitrate:
                cmd += ["-b:a", bitrate]
            cmd += ["-f", container, path]
            try:
                subprocess.run(cmd, capture_output=True, check=True, timeout=600)
                break
            except FileNotFoundError as e:
                raise AudioIOError("ffmpeg is needed to write MP3 and M4A. Install ffmpeg "
                                   "and add it to PATH.") from e
            except subprocess.CalledProcessError as e:
                if i + 1 < len(codecs):
                    continue                 # a system encoder failed: the next one
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


# ── Identity ────────────────────────────────────────────────────────────

def file_digest(path) -> str:
    """SHA-1 of the file's bytes. Remix projects, the stem cache and the
    Recents list are all keyed on it, so it must never change
    (docs/API.md §2). Ported unchanged from shimmer/stems.py."""
    h = hashlib.sha1()
    with open(os.fspath(path), "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


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
