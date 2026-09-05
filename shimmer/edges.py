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

# The burst's run ends where the envelope first drops under the detection
# threshold, which can be well before it has died away, and smaller ticks
# later in the gap sit under the threshold too. Either one leaves a faint
# blip after the cut. So the cut is pushed to where the gap has settled:
# the first stretch of SETTLE_MS whose envelope stays within SETTLE_DB of
# the gap's own quiet level: the middle of its noise band (the median
# of the peak envelope), so the box reaches the floor, not its top edge.
SETTLE_DB = 3.0
SETTLE_MS = 10.0
SETTLE_PCT = 50.0

# Smaller ticks after (or before) the main click count as part of the
# artifact when they are this short and land within ZONE_MAX_MS of its
# start. Render ticks run 1-40 ms; a musical hit rings longer than that.
TICK_MAX_MS = 60.0
ZONE_MAX_MS = 500.0


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


def _merge_close_runs(runs: List[Tuple[int, int]],
                      min_gap_frames: int) -> List[Tuple[int, int]]:
    """Join runs separated by less than the minimum gap. A burst that
    decays into the noise floor crosses the threshold several times on
    its way down; those crossings are the same event, not a burst
    followed by music."""
    if not runs:
        return []
    merged = [tuple(runs[0])]
    for s, e in runs[1:]:
        ps, pe = merged[-1]
        if s - pe < min_gap_frames:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    return merged


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


# Relative pass: the music proper starts where the envelope first comes
# within this much of the loudest point of the scan window.
PROGRAM_BELOW_PEAK_DB = 20.0
# Quiet level of the head, estimated from the pre-music region: this
# percentile of the peak envelope. AI renders rarely start from digital
# silence; a -60..-70 dBFS floor is normal.
HEAD_FLOOR_PCT = 20.0


def _detect_one_edge(x: np.ndarray, sr: int) -> Optional[Dict[str, Any]]:
    """Look for an artifact at the START of `x`. Tail detection reverses
    the audio and calls this, then mirrors the timings back.

    Two passes. The absolute pass wants a gap below FLOOR_DB between the
    burst and the music, which is what a render with real digital
    silence gives. Most AI renders never get that quiet: the head sits at
    -60..-70 dBFS, so the burst and the song read as one run and the
    absolute pass sees nothing. The relative pass then finds where the
    music proper starts (within PROGRAM_BELOW_PEAK_DB of the scan's
    loudest point), estimates the head's own quiet level before it, and
    looks for a short burst standing MIN_PROMINENCE_DB above that level
    with a gap of head noise after it."""
    scan = x[:int(min(x.shape[0], SCAN_S * sr))]
    if scan.shape[0] < int(0.05 * sr):
        return None

    mono = np.max(np.abs(scan), axis=1)
    env_db, hop = _envelope_db(mono, sr)

    found = _detect_in_envelope(env_db, hop, x, sr, FLOOR_DB, limit=None)
    if found is not None:
        return found

    loud = np.flatnonzero(env_db >= float(env_db.max()) - PROGRAM_BELOW_PEAK_DB)
    if loud.size == 0:
        return None
    p0 = int(loud[0])
    if p0 < int(0.05 * sr / hop):
        return None  # music starts at once: nothing detached to cut
    head_floor = float(np.percentile(env_db[:p0], HEAD_FLOOR_PCT))
    thr = max(FLOOR_DB, head_floor + MIN_PROMINENCE_DB)
    return _detect_in_envelope(env_db, hop, x, sr, thr, limit=p0)


def _detect_in_envelope(env_db: np.ndarray, hop: int, x: np.ndarray, sr: int,
                        floor_db: float, limit: Optional[int]
                        ) -> Optional[Dict[str, Any]]:
    """Shared burst-gap-program test on the peak envelope above `floor_db`.
    With `limit` (a frame index where the music proper starts), the
    music itself counts as the program even when the envelope never
    drops below `floor_db` again.

    The artifact is a zone, not one run: the first run plus any short
    ticks after it (see TICK_MAX_MS), up to the program. A render often
    leaves a click and then a couple of smaller ticks, or a faint tick
    before the click; cutting after the first run alone left those
    behind as a blip. The program is the first later run that is not a
    tick, or the music proper when `limit` is given."""
    f2s = hop / sr  # frames → seconds
    env = env_db if limit is None else env_db[:limit]

    runs = _merge_close_runs(_runs_above(env, floor_db),
                             int(round(MIN_GAP_MS / 1000.0 / f2s)))
    if not runs:
        return None

    tick_max = int(round(TICK_MAX_MS / 1000.0 / f2s))
    zone_max = int(round(ZONE_MAX_MS / 1000.0 / f2s))
    min_gap = int(round(MIN_GAP_MS / 1000.0 / f2s))
    zone = [runs[0]]
    p_start: Optional[int] = None
    for idx, (s, e) in enumerate(runs[1:], start=1):
        # A short run that reaches the music proper with no gap is the
        # song's own lead-in, not a tick: it is where the program starts.
        touches_program = (limit is not None and idx == len(runs) - 1
                           and (env.shape[0] - e) < min_gap)
        if ((e - s) <= tick_max and (e - runs[0][0]) <= zone_max
                and not touches_program):
            zone.append((s, e))
            continue
        p_start = s
        break
    if p_start is None:
        if limit is None:
            # Silence throughout, ticks with no music after them, or audio
            # that starts and never stops — nothing detached to cut.
            return None
        p_start = int(limit)

    a_start = zone[0][0]
    a_end = zone[-1][1]
    # The main burst is the loudest run in the zone; the length and
    # brevity tests apply to it, not to the spread of the ticks.
    main = max(zone, key=lambda r: float(env_db[r[0]:r[1]].max()))
    main_ms = (main[1] - main[0]) * f2s * 1000.0
    length_ms = (a_end - a_start) * f2s * 1000.0
    gap_ms = (p_start - a_end) * f2s * 1000.0
    if main_ms > MAX_ARTIFACT_MS or gap_ms < MIN_GAP_MS:
        return None
    # A glitch is brief relative to the silence that follows it. A note
    # that rings longer than the gap after it is part of the arrangement.
    if gap_ms < main_ms:
        return None

    peak_db = float(env_db[main[0]:main[1]].max())
    gap_db = float(env_db[a_end:p_start].max())
    if peak_db < MIN_ARTIFACT_PEAK_DB:
        return None
    if peak_db - gap_db < MIN_PROMINENCE_DB:
        return None

    # Cut as little as possible, but past everything the burst left
    # behind: walk from the zone's end to where the gap has settled at
    # its quiet level (see SETTLE_*). If it never settles, cut right up
    # to the margin before the music; the gap is not program by
    # construction.
    # Cut just past the tick: where its slope has reached the floor, plus
    # a small margin. The floor between here and the music is left alone;
    # that is the job of "Trim leading/trailing silence on export", which
    # is a separate, explicit choice.
    settled = _settle_frame(env_db, a_end, p_start, f2s)
    margin = int(round(CUT_MARGIN_MS / 1000.0 / f2s))
    cut_frame = min(settled + margin, p_start - margin)
    cut_frame = max(cut_frame, a_end)
    cut_s = cut_frame * f2s
    cut_sample = _zero_crossing_near(x, int(round(cut_s * sr)), sr)

    # Report the artifact as it looks and sounds: it ends where its
    # slope has reached the floor, not where it crossed the threshold.
    end = max(a_end, settled)
    return {
        "artifact_start_s": float(a_start * f2s),
        "artifact_end_s": float(end * f2s),
        "artifact_ms": float((end - a_start) * f2s * 1000.0),
        "artifact_peak_db": round(peak_db, 1),
        "ticks": len(zone) - 1,
        "gap_ms": float((p_start - end) * f2s * 1000.0),
        "gap_floor_db": round(gap_db, 1),
        # Where the music itself begins (head) or ends (tail).
        "program_s": float(p_start * f2s),
        "suggested_s": float(cut_sample / sr),
    }


def _settle_frame(env_db: np.ndarray, a_end: int, p_start: int,
                  f2s: float) -> int:
    """First frame at or after `a_end` from which the envelope stays
    within SETTLE_DB of the gap's quiet level for SETTLE_MS. Falls back
    to the last frame that still leaves CUT_MARGIN_MS before `p_start`."""
    margin = int(round(CUT_MARGIN_MS / 1000.0 / f2s))
    latest = max(a_end, p_start - margin)
    gap = env_db[a_end:p_start]
    if gap.size == 0:
        return a_end
    quiet_db = float(np.percentile(gap, SETTLE_PCT))
    win = max(1, int(round(SETTLE_MS / 1000.0 / f2s)))
    for f in range(a_end, latest + 1):
        if f + win > p_start:
            break
        if np.all(env_db[f:f + win] <= quiet_db + SETTLE_DB):
            return f
    return latest


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
    ticks = int(edge.get("ticks") or 0)
    extra = "" if ticks == 0 else (
        f" plus {ticks} smaller tick{'s' if ticks != 1 else ''}")
    return (f"{edge['artifact_ms']:.0f} ms burst at "
            f"{edge['artifact_peak_db']:.0f} dBFS{extra}, "
            f"{edge['gap_ms']:.0f} ms before program")
