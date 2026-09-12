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
from .render import Rendered

_DITHER_SEED = 0          # the same dither every time, so an export repeats exactly

# A lossy file, decoded, stays at or under -1.0 dBTP (ARCHITECTURE §19.1
# item 12). The meter reads at 8x, which can miss up to 0.17 dB, so it aims
# that much lower.
_LOSSY_LIMIT_DBTP = -1.0
_LOSSY_AIM_DBTP = _LOSSY_LIMIT_DBTP + 20.0 * math.log10(math.cos(math.pi / 16))
_LOSSY_TRIES = 3


def tpdf_dither(y: np.ndarray, bits: int = 16, seed: int = _DITHER_SEED) -> np.ndarray:
    """Add triangular (TPDF) dither of +/- 1 LSB at `bits`."""
    lsb = 1.0 / (2 ** (bits - 1))
    rng = np.random.default_rng(seed)
    a = np.asarray(y, dtype=np.float64)
    return a + (rng.random(a.shape) - rng.random(a.shape)) * lsb


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
    if fmt.sr and rendered.sr != fmt.sr:
        raise ValueError(f"{fmt.label} is {fmt.sr} Hz; render with this format first")

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
