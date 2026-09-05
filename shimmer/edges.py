"""
edges.py — Detect head/tail artifacts that silence trimming cannot catch.

Generators frequently leave a short burst at the very top of a render: a
click, a truncated reverb tail from the previous section, a DC step at
sample 0.  These sit ABOVE a normal silence gate (-60 dBFS) but BELOW the
music, and they are separated from the program by a gap of near-silence.
A threshold trim therefore treats the burst as "the start of the song" and
cuts nothing.

This module looks for that shape specifically: a short run of energy, a
quiet gap, then sustained program.  It reports what it found and where a
clean cut would be — it never edits audio.  Cutting is the caller's job
(see `dsp.trim_silence` for the plain silence case, and Params.trim_in_s /
trim_out_s for the applied edit).

Detection runs on a peak envelope rather than RMS: these artifacts are
often one or two milliseconds long, and a 20 ms RMS window averages them
straight into the noise floor.
"""

from __future__ import annotations

from . import _winfix  # noqa: F401  # must precede scipy import on Windows

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .dsp import as_2d


# Envelope resolution. 1 ms hops keep single-sample clicks visible while
# staying cheap enough to scan both edges of a 5-minute file instantly.
HOP_MS = 1.0

# Everything below this is treated as silence for grouping purposes. Well
# under the -60 dBFS export gate so we can still see the gap *around* an
# artifact that a -60 gate would call audible.
FLOOR_DB = -75.0

# How far into each edge we look. Artifacts live in the first moments; a
# burst 8 seconds in is a musical event, not a render glitch.
SCAN_S = 5.0

# A run longer than this is program material, not an artifact. Real render
# glitches measured across the library run 15-35 ms; a 390 ms event turned
# out to be an intro note on "Ah", which this cap correctly ignores.
MAX_ARTIFACT_MS = 150.0

# The artifact has to be genuinely detached from the music. Shorter gaps
# than this are just a quiet beat inside the intro.
MIN_GAP_MS = 25.0

# Below this the burst is inaudible in practice — reporting it would be
# noise, not a finding.
MIN_ARTIFACT_PEAK_DB = -80.0

# The burst must stand clear of the gap floor, otherwise we are looking at
# noise-floor wobble rather than a discrete event.
MIN_PROMINENCE_DB = 10.0

# Breathing room left between the end of the artifact and the suggested
# cut, so the edit lands inside the gap rather than on the decay.
CUT_MARGIN_MS = 10.0


def _envelope_db(mono: np.ndarray, sr: int) -> Tuple[np.ndarray, int]:
    """Peak envelope in dBFS, one value per HOP_MS. Returns (env, hop)."""
    hop = max(1, int(round(sr * HOP_MS / 1000.0)))
    n_frames = int(np.ceil(mono.shape[0] / hop))
    pad = n_frames * hop - mono.shape[0]
    if pad:
        mono = np.concatenate([mono, np.zeros(pad, dtype=mono.dtype)])
    peaks = mono.reshape(n_frames, hop).max(axis=1)
    return 20.0 * np.log10(peaks + 1e-9), hop


def _runs_above(env_db: np.ndarray, floor_db: float) -> List[Tuple[int, int]]:
    """Contiguous [start, end) frame ranges where the envelope is audible."""
    loud = env_db > floor_db
    if not loud.any():
        return []
    edges = np.flatnonzero(np.diff(loud.astype(np.int8)))
    starts = list(edges[loud[edges + 1]] + 1)
    ends = list(edges[~loud[edges + 1]] + 1)
    if loud[0]:
        starts.insert(0, 0)
    if loud[-1]:
        ends.append(loud.size)
    return list(zip(starts, ends))


def _zero_crossing_near(x: np.ndarray, target: int, sr: int,
                        window_ms: float = 3.0) -> int:
    """Nearest sample to `target` where every channel is closest to zero.

    Cutting on a zero crossing means the edit itself cannot click, which
    matters more than hitting the requested millisecond exactly.
    """
    half = max(1, int(sr * window_ms / 1000.0))
    lo = max(0, target - half)
    hi = min(x.shape[0], target + half)
    if hi - lo < 2:
        return int(np.clip(target, 0, max(0, x.shape[0] - 1)))
    energy = np.abs(x[lo:hi]).sum(axis=1)
    return int(lo + np.argmin(energy))


def _detect_one_edge(x: np.ndarray, sr: int) -> Optional[Dict[str, Any]]:
    """Look for an artifact at the START of `x`. Tail detection reverses
    the audio and calls this, then mirrors the timings back."""
    scan = x[:int(min(x.shape[0], SCAN_S * sr))]
    if scan.shape[0] < int(0.05 * sr):
        return None

    mono = np.max(np.abs(scan), axis=1)
    env_db, hop = _envelope_db(mono, sr)
    f2s = hop / sr  # frames → seconds

    runs = _runs_above(env_db, FLOOR_DB)
    if len(runs) < 2:
        # Either silence throughout, or audio that starts and never stops —
        # both mean there is no detached burst to report.
        return None

    a_start, a_end = runs[0]
    p_start = runs[1][0]

    length_ms = (a_end - a_start) * f2s * 1000.0
    gap_ms = (p_start - a_end) * f2s * 1000.0
    if length_ms > MAX_ARTIFACT_MS or gap_ms < MIN_GAP_MS:
        return None
    # A glitch is brief relative to the silence that follows it. A note
    # that rings longer than the gap after it is part of the arrangement.
    if gap_ms < length_ms:
        return None

    peak_db = float(env_db[a_start:a_end].max())
    gap_db = float(env_db[a_end:p_start].max())
    if peak_db < MIN_ARTIFACT_PEAK_DB:
        return None
    if peak_db - gap_db < MIN_PROMINENCE_DB:
        return None

    # Cut as little as possible: just past the burst, still inside the gap.
    cut_s = min(
        a_end * f2s + CUT_MARGIN_MS / 1000.0,
        p_start * f2s - CUT_MARGIN_MS / 1000.0,
    )
    cut_s = max(cut_s, a_end * f2s)
    cut_sample = _zero_crossing_near(x, int(round(cut_s * sr)), sr)

    return {
        "artifact_start_s": float(a_start * f2s),
        "artifact_end_s": float(a_end * f2s),
        "artifact_ms": float(length_ms),
        "artifact_peak_db": round(peak_db, 1),
        "gap_ms": float(gap_ms),
        "gap_floor_db": round(gap_db, 1),
        # Where the music itself begins (head) or ends (tail).
        "program_s": float(p_start * f2s),
        "suggested_s": float(cut_sample / sr),
    }


def _mirror(edge: Dict[str, Any], duration_s: float) -> Dict[str, Any]:
    """Convert a result measured on reversed audio into real timings.

    Reversed-slice time t maps to duration_s - t, which also swaps the
    meaning of the artifact's start and end.
    """
    out = dict(edge)
    for key in ("artifact_start_s", "artifact_end_s",
                "program_s", "suggested_s"):
        out[key] = float(duration_s - edge[key])
    out["artifact_start_s"], out["artifact_end_s"] = (
        out["artifact_end_s"], out["artifact_start_s"])
    return out


def detect_edge_artifacts(x: np.ndarray, sr: int) -> Dict[str, Any]:
    """Scan both edges of (samples, channels) audio for render artifacts.

    Returns a dict with "head" and "tail" keys, each either None or a
    description of what was found. Never modifies the audio.
    """
    x = as_2d(np.asarray(x, dtype=np.float32))
    duration_s = x.shape[0] / sr

    head = _detect_one_edge(x, sr)

    # Reverse only the trailing scan window, not the whole file — the
    # mapping back to real time is duration - t either way.
    tail_slice = np.ascontiguousarray(x[-int(min(x.shape[0], SCAN_S * sr)):][::-1])
    tail_raw = _detect_one_edge(tail_slice, sr)
    tail = _mirror(tail_raw, duration_s) if tail_raw else None

    return {
        "head": head,
        "tail": tail,
        "found": bool(head or tail),
        "duration_s": float(duration_s),
    }


# Fade applied at an explicit cut. Long enough to guarantee no click even
# when the cut misses a zero crossing, short enough to be inaudible.
TRIM_FADE_MS = 5.0


def apply_trim(x: np.ndarray, sr: int,
               in_s: float = 0.0, out_s: Optional[float] = None,
               fade_ms: float = TRIM_FADE_MS) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Cut audio to [in_s, out_s] with short edge fades.

    Unlike `dsp.trim_silence` this makes no judgement about content — it
    cuts exactly where asked. Returns (audio, report). Out-of-range or
    inverted points are clamped rather than raising: a bad marker should
    degrade to "no edit", never to a failed export.
    """
    x = as_2d(np.asarray(x, dtype=np.float32))
    n = x.shape[0]
    duration_s = n / sr

    start = int(np.clip(round(float(in_s or 0.0) * sr), 0, n))
    end = n if out_s is None else int(np.clip(round(float(out_s) * sr), 0, n))
    if end <= start:
        start, end = 0, n

    if start == 0 and end == n:
        return x, {"applied": False, "in_s": 0.0, "out_s": duration_s,
                   "cut_head_s": 0.0, "cut_tail_s": 0.0}

    y = x[start:end].copy()
    fade = min(int(sr * max(0.0, fade_ms) / 1000.0), y.shape[0] // 2)
    if fade > 1:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
        if start > 0:
            y[:fade] *= ramp
        if end < n:
            y[-fade:] *= ramp[::-1]

    return y, {
        "applied": True,
        "in_s": round(start / sr, 4),
        "out_s": round(end / sr, 4),
        "cut_head_s": round(start / sr, 4),
        "cut_tail_s": round((n - end) / sr, 4),
        "fade_ms": float(fade_ms),
    }


def describe_edge(edge: Optional[Dict[str, Any]], where: str = "head") -> str:
    """One-line human summary, for logs, the CLI, and the UI notice."""
    if not edge:
        return f"no {where} artifact"
    return (f"{edge['artifact_ms']:.0f} ms burst at "
            f"{edge['artifact_peak_db']:.0f} dBFS, "
            f"{edge['gap_ms']:.0f} ms before program")
