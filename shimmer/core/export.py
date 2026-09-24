"""export(rendered, path): the one way a file is written.

Every tab writes through here, so every export gets the same treatment:

- **The source is never overwritten.** This covers the file the render came
  from, a `source_path` the caller names, and the same file spelled
  differently.
- **16-bit files get TPDF dither,** at the textbook level: triangular noise,
  one step (1 LSB) either way. 1.1.1 used twice that.
- **Samples never wrap.** Anything past full scale is clipped, not wrapped
  around, and the report says how many samples were.
- **The file appears whole or not at all.** It is written under a temporary
  name, tagged, then renamed into place.
- **The report reads the written file.** Loudness and true peak are measured
  on what is on disk, decoded, not on what was meant to be written.
- **Lossy files are checked after encoding.** Codecs push peaks up when they
  encode (measured: up to +2.9 dB for M4A). Each lossy file is decoded and
  measured. If it is over -1.0 dBTP, it is turned down by the excess and
  encoded again, and the report says by how much (`lossy_trim_db`).
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, Optional

import numpy as np

from . import catalog
from . import tags as tagging
from .audio import io, meters
from .render import Rendered, Source, render
from .settings import Settings

_DITHER_SEED = 0          # the same dither every time, so an export repeats exactly

# A lossy file, decoded, stays at or under -1.0 dBTP (ARCHITECTURE §19.1
# item 12). The meter reads at 8x, which can miss up to 0.17 dB, so it aims
# that much lower.
_LOSSY_LIMIT_DBTP = catalog.LOSSY_FILE_LIMIT_DBTP
_LOSSY_AIM_DBTP = _LOSSY_LIMIT_DBTP + 20.0 * math.log10(math.cos(math.pi / 16))
_LOSSY_TRIES = 3


def tpdf_dither(y: np.ndarray, bits: int = 16, seed: int = _DITHER_SEED) -> np.ndarray:
    """Add triangular (TPDF) dither of +/- 1 LSB at `bits`."""
    lsb = 1.0 / (2 ** (bits - 1))
    rng = np.random.default_rng(seed)
    a = np.asarray(y, dtype=np.float64)
    return a + (rng.random(a.shape) - rng.random(a.shape)) * lsb


# ── How big a file will be (the size limit) ─────────────────────────────
# WAV is worked out from the length. FLAC depends on the music, so a few
# slices are encoded (dithered, as export() writes them) and the whole song
# scaled from them. Lossy formats follow their bitrate; OGG Vorbis at
# quality 0.8 ran about 270 kbps on a dense mix (SOUND-CHANGES.md).
_EST_SLICE_S = 10.0
_EST_SLICES = 3
# FLAC slices vs the whole song, either way. Measured 2026-09-13 on two
# songs, three loudness choices, 16- and 24-bit: every estimate from
# rendered windows landed within 2 % of the written file.
_EST_FLAC_SPREAD = 0.05
_OGG_BYTES_PER_S = (28_000, 38_000)


def _wav_header_bytes(channels: int, bits: int) -> int:
    """44 bytes; libsndfile writes the longer WAVE_FORMAT_EXTENSIBLE header
    (80 bytes with its fact chunk) for more than 16 bits or 2 channels."""
    return 44 if bits <= 16 and channels <= 2 else 80


def _flac_ratio(x: np.ndarray, sr: int, fmt: catalog.Format, sample: bool = False) -> float:
    """Encoded FLAC bytes per PCM byte, from up to three slices of `x`, or
    from all of `x` when it is already a sample of the song."""
    import io as _bytes_io

    import soundfile as sf

    n = x.shape[0]
    width = int(_EST_SLICE_S * sr)
    if sample or n <= width * _EST_SLICES:
        starts = [0]
        width = n
    else:
        starts = [int(n * f) - width // 2 for f in (0.2, 0.5, 0.8)]
    enc = pcm = 0
    for a in starts:
        seg = x[max(0, a):max(0, a) + width]
        out_sr = fmt.rate_for(sr)
        if out_sr != sr:
            seg = io.resample(seg, sr, out_sr)[0]
        y = np.asarray(seg, dtype=np.float64)
        if fmt.bits == 16:
            y = tpdf_dither(y, 16)
        buf = _bytes_io.BytesIO()
        sf.write(buf, np.clip(y, -1.0, 1.0), out_sr, format="FLAC", subtype=fmt.subtype)
        enc += len(buf.getvalue())
        pcm += y.shape[0] * y.shape[1] * (fmt.bits // 8)
    return enc / max(pcm, 1)


def estimate_size(audio: np.ndarray, sr: int, key: str,
                  seconds: Optional[float] = None) -> Dict[str, Any]:
    """How big `audio` will be written as format `key`: {format, bytes, low,
    high, exact}. WAV is exact (tags add a little); FLAC and lossy are a
    range. `audio` is what will be written, the master: the raw upload
    reads 24-bit FLAC at half its real size, because a 16-bit song keeps its
    low bits empty until mastering fills them (measured on two songs).
    `seconds`: the whole file's length, when `audio` is only a sample of it."""
    fmt = catalog.output_format(key)
    x = np.asarray(audio, dtype=np.float32)
    x = x[:, None] if x.ndim == 1 else x
    sample = seconds is not None
    seconds = float(seconds) if sample else x.shape[0] / float(sr)
    frames = int(round(seconds * fmt.rate_for(sr))) if sample else \
        int(round(x.shape[0] * fmt.rate_for(sr) / float(sr)))
    ch = x.shape[1]
    if not fmt.lossy and fmt.ext == ".wav":
        b = _wav_header_bytes(ch, fmt.bits) + frames * ch * (fmt.bits // 8)
        low = high = b
    elif not fmt.lossy:
        mid = _flac_ratio(x, sr, fmt, sample) * frames * ch * (fmt.bits // 8)
        low, high = mid * (1.0 - _EST_FLAC_SPREAD), mid * (1.0 + _EST_FLAC_SPREAD)
    elif fmt.bitrate:
        low = high = seconds * int(fmt.bitrate.rstrip("k")) * 1000 / 8
    else:
        low, high = seconds * _OGG_BYTES_PER_S[0], seconds * _OGG_BYTES_PER_S[1]
    return {"format": fmt.key, "bytes": int(round((low + high) / 2)),
            "low": int(round(low)), "high": int(round(high)),
            "exact": low == high and not fmt.lossy}


def estimate_sizes(audio: np.ndarray, sr: int) -> Dict[str, Dict[str, Any]]:
    """estimate_size() for every format, keyed by format."""
    return {f.key: estimate_size(audio, sr, f.key) for f in catalog.FORMATS}


def estimate_sizes_for(source: Source, settings: Settings,
                       reference: Optional[Source] = None) -> Dict[str, Dict[str, Any]]:
    """Every format's size for this song with these settings, before the
    run: three 10-second windows are rendered exactly as the export will be
    (render() on a window, with the reference track if one is used), and
    the whole song is scaled from them."""
    dur = source.duration_s
    half = _EST_SLICE_S / 2.0
    if dur <= _EST_SLICE_S * _EST_SLICES:
        windows = [(0.0, dur)]
    else:
        windows = [(dur * f - half, dur * f + half) for f in (0.2, 0.5, 0.8)]
    parts = [render(source, settings, w, reference=reference) for w in windows]
    sample = np.concatenate([p.audio for p in parts])
    return {f.key: estimate_size(sample, parts[0].sr, f.key, seconds=dur)
            for f in catalog.FORMATS}


def _same_file(a: str, b: str) -> bool:
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def export(rendered: Rendered, path, source_path=None,
           tags: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Write `rendered` to `path` in its settings' format. Returns a report
    measured on the written file: lufs, true_peak_dbtp, sr, clipped_samples,
    dither, tags."""
    path = os.path.abspath(os.fspath(path))
    fmt = catalog.output_format(rendered.settings.format)
    root, ext = os.path.splitext(path)
    if ext.lower() != fmt.ext:
        raise ValueError(f"a {fmt.label} file must end in {fmt.ext}")
    for src in (rendered.source_path, source_path):
        if src and _same_file(path, os.fspath(src)):
            raise ValueError("refusing to write over the source file")
    if rendered.sr != fmt.rate_for(rendered.sr):
        raise ValueError(f"{fmt.label} is {fmt.rate_for(rendered.sr)} Hz; render with this "
                         "format first")

    y = np.asarray(rendered.audio, dtype=np.float64)
    if fmt.bits == 16:
        y = tpdf_dither(y, 16)
    over = int(np.count_nonzero(np.abs(y) > 1.0))
    if over:
        y = np.clip(y, -1.0, 1.0)

    tmp = f"{root}.partial{ext}"
    trim_db = 0.0
    try:
        for _ in range(_LOSSY_TRIES if fmt.lossy else 1):
            out = y * 10.0 ** (trim_db / 20.0) if trim_db else y
            io.save(tmp, out, rendered.sr, subtype=fmt.subtype or "PCM_24",
                    bitrate=fmt.bitrate, quality=fmt.quality)
            if not fmt.lossy:
                break
            # What the listener hears is the decoded file. If the codec pushed
            # its peaks over the limit, turn the file down by exactly that much
            # and encode again.
            z, zsr = io.load(tmp)
            excess = meters.true_peak_db(z, zsr) - _LOSSY_AIM_DBTP
            if excess <= 0.0:
                break
            trim_db -= excess + 0.05
        tag_report = tagging.write_tags(tmp, tags) if tags else {"written": False, "fields": []}
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    z, zsr = io.load(path)
    return {
        "size_bytes": os.path.getsize(path),
        "path": path,
        "format": fmt.key,
        "sr": zsr,
        "bits": fmt.bits,
        "dither": fmt.bits == 16,
        "lufs": meters.loudness(z, zsr),
        "true_peak_dbtp": meters.true_peak_db(z, zsr),
        "lossy_trim_db": trim_db,
        "clipped_samples": over,
        "tags": tag_report,
    }
