"""The release check: is this file ready to upload?

Ported from shimmer/release.py (1.1.1). One change: when the mastering
report carries no true peak, it is read with the engine's meter (the louder
channel, 8x) instead of 1.1.1's mono mix at 4x, which read low whenever the
channels differed (docs/ARCHITECTURE.md §10).

One pass/fail read after a run, the way an engineer signs a file off
before it goes to the distributor. Every check states a value, a verdict
(pass, warn, fail, or info) and one line of advice. The thresholds are
the streaming services' loudness rules and the stores' delivery rules:

* Loudness on target (with mastering on): within 0.5 LU passes, within
  1 LU warns, further fails.
* True peak at or under the ceiling: the limiter's promise.
* Clipping in the uploaded file: Shimmer cannot undo flat-topped peaks.
* Sample rate and format: 44.1 or 48 kHz WAV or FLAC is what the stores
  ask for; a lossy export is for listening.
* Silence at the start and end, and the length: the stores' rules of
  thumb (a long lead-in, a long tail, a track under 30 seconds).
* DC offset and mono compatibility.
* Tags: title, artist and album; the ISRC is noted, not required.

Plus "how loud it plays": how far each service turns the file up or
down when it normalises loudness.

Measurement only: nothing here touches the audio.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..audio import meters
from ..audio.trim import find_audible_bounds


def as_2d(x: np.ndarray) -> np.ndarray:
    return x[:, None] if x.ndim == 1 else x


# Where the services normalise to (integrated LUFS) and whether they turn
# a quiet track up. Public figures; they move slowly.
PLATFORMS: Tuple[Tuple[str, float, str], ...] = (
    ("Spotify", -14.0, "up"),        # up only as far as the true peak allows
    ("Apple Music", -16.0, "up"),
    ("YouTube", -14.0, "down"),      # never turns a quiet track up
    ("Amazon Music", -14.0, "up"),
    ("Tidal", -14.0, "up"),
    ("Deezer", -15.0, "up"),
)

LOUDNESS_PASS_LU = 0.5
LOUDNESS_WARN_LU = 1.0
TP_SLACK_DB = 0.05
CLIP_LEVEL = 0.999            # |sample| at or above this counts as clipped
CLIP_WARN_SAMPLES = 100
SILENCE_DB = -60.0
HEAD_SILENCE_WARN_S = 1.0
TAIL_SILENCE_WARN_S = 5.0
MIN_DURATION_S = 30.0
DC_WARN = 0.005               # 0.5 % of full scale, about -46 dBFS
CORR_WARN = 0.0


def _check(key: str, label: str, status: str, value: str,
           detail: str = "") -> Dict[str, Any]:
    return {"key": key, "label": label, "status": status,
            "value": value, "detail": detail}


def _finite(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _mmss(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02d}"


def count_clipped(x: np.ndarray, level: float = CLIP_LEVEL) -> int:
    """Samples at or above `level` of full scale: flat-topped peaks."""
    x = as_2d(np.asarray(x, dtype=np.float32))
    if x.size == 0:
        return 0
    return int(np.count_nonzero(np.abs(x) >= level))


def silence_at_edges(y: np.ndarray, sr: int,
                     threshold_db: float = SILENCE_DB) -> Tuple[float, float, bool]:
    """Seconds of silence before and after the audible part, and whether
    the whole file is silent."""
    y = as_2d(np.asarray(y, dtype=np.float32))
    n = y.shape[0]
    if n == 0:
        return 0.0, 0.0, True
    bounds = find_audible_bounds(y, sr, threshold_db)
    if bounds is None:
        return n / sr, 0.0, True
    start, end = bounds
    return float(start) / sr, float(max(0, n - end)) / sr, False


def platform_changes(lufs: Optional[float]) -> List[Dict[str, Any]]:
    """How far each service turns the file up or down."""
    if lufs is None or not np.isfinite(lufs):
        return []
    out: List[Dict[str, Any]] = []
    for name, target, boost in PLATFORMS:
        change = float(target - lufs)
        if change < -0.05:
            note = f"turned down {abs(change):.1f} dB"
        elif change > 0.05 and boost == "up":
            note = f"turned up {change:.1f} dB" + (" at most" if name == "Spotify" else "")
        elif change > 0.05:
            note = "played as is (no boost)"
        else:
            note = "played as is"
        out.append({"name": name, "target_lufs": target,
                    "change_db": round(change, 2), "note": note})
    return out


def tags_check(tags: Optional[Dict[str, Any]], written: bool) -> Dict[str, Any]:
    t = dict(tags or {})
    if not written:
        return _check("tags", "Tags", "warn", "none",
                      "no tags were written; title, artist and album travel with the file")
    missing = [k for k in ("title", "artist", "album") if not str(t.get(k) or "").strip()]
    value = " · ".join(str(t[k]) for k in ("title", "artist") if t.get(k)) or "written"
    if missing:
        return _check("tags", "Tags", "warn", value,
                      f"missing {', '.join(missing)}; add them in Tags")
    return _check("tags", "Tags", "pass", value, f"album: {t.get('album')}")


def isrc_check(tags: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    isrc = str((tags or {}).get("isrc") or "").strip()
    if isrc:
        return _check("isrc", "ISRC", "pass", isrc, "")
    return _check("isrc", "ISRC", "info", "none",
                  "the distributor assigns one if you do not have your own")


def _with_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    checks = report.get("checks") or []
    counts = {s: sum(1 for c in checks if c.get("status") == s)
              for s in ("pass", "warn", "fail")}
    status = "fail" if counts["fail"] else "warn" if counts["warn"] else "pass"
    report.update({"status": status, "passed": counts["pass"],
                   "warned": counts["warn"], "failed": counts["fail"]})
    return report


def add_check(report: Optional[Dict[str, Any]],
              check: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Append a check made later (tags are written after the audio) and
    refresh the verdict."""
    if not report:
        return report
    report = dict(report)
    report["checks"] = [c for c in report.get("checks") or []
                        if c.get("key") != check.get("key")] + [check]
    return _with_summary(report)


def release_check(y: np.ndarray, sr: int, *,
                  mastering: Optional[Dict[str, Any]] = None,
                  export: Optional[Dict[str, Any]] = None,
                  x_in: Optional[np.ndarray] = None,
                  clipped_samples: Optional[int] = None,
                  correlation: Optional[float] = None,
                  duration_s: Optional[float] = None,
                  tags: Optional[Dict[str, Any]] = None,
                  tags_written: Optional[bool] = None,
                  lufs_out: Optional[float] = None,
                  expected_lufs: Optional[float] = None) -> Dict[str, Any]:
    """Grade the exported signal `y`. `mastering` is the mastering report
    (target, ceiling, after); `export` names the format and bit depth;
    `x_in` (or `clipped_samples`) is the uploaded file for the clipping
    check; `tags` and `tags_written` come from the tag writer, and are
    left out when None (the caller adds them with `add_check` later).
    `expected_lufs` is album mode's level for this track (the target
    less its distance below the loudest track): the loudness check then
    grades against that, since sitting under the target is the point."""
    y = as_2d(np.asarray(y, dtype=np.float32))
    n = y.shape[0]
    checks: List[Dict[str, Any]] = []
    m = mastering or {}
    after = m.get("after") or {}
    mastered = bool(m.get("enabled")) and not m.get("deferred")
    lufs = _finite(after.get("lufs_i"))
    if lufs is None:
        lufs = _finite(lufs_out)

    # 1. Loudness against the target.
    if mastered:
        target = _finite(m.get("target_lufs"))
        expected = _finite(expected_lufs)
        aim = expected if expected is not None else target
        if lufs is not None and aim is not None:
            err = lufs - aim
            side = "under" if err < 0 else "over"
            if expected is not None and target is not None:
                below = target - expected
                where = (f"album mode: kept {below:.1f} LU below the loudest track"
                         if below > 0.05 else "the album's loudest track, on the target")
            else:
                where = f"target {aim:g} LUFS"
            if abs(err) <= LOUDNESS_PASS_LU:
                st, detail = "pass", where
            elif abs(err) <= LOUDNESS_WARN_LU:
                st, detail = "warn", (f"{abs(err):.1f} LU {side} its level ({where}); "
                                      "peak control took some of the level")
            else:
                st, detail = "fail", f"{abs(err):.1f} LU {side} its level ({where})"
            checks.append(_check("loudness", "Loudness", st, f"{lufs:.1f} LUFS", detail))
        else:
            checks.append(_check("loudness", "Loudness", "warn", "n/a", "could not be measured"))
    else:
        checks.append(_check("loudness", "Loudness", "warn",
                             f"{lufs:.1f} LUFS" if lufs is not None else "n/a",
                             "mastering was off, so the level was not set for release"))

    # 2. True peak against the ceiling.
    tp = _finite(after.get("true_peak_dbtp"))
    if tp is None and n:
        tp = _finite(meters.true_peak_db(y, sr))
    ceiling = _finite(m.get("ceiling_dbtp")) if mastered else None
    if ceiling is None:
        ceiling = -1.0
    if tp is None:
        checks.append(_check("true_peak", "True peak", "warn", "n/a", "could not be measured"))
    elif tp <= ceiling + TP_SLACK_DB:
        checks.append(_check("true_peak", "True peak", "pass", f"{tp:.1f} dBTP",
                             f"ceiling {ceiling:g} dBTP"))
    else:
        checks.append(_check("true_peak", "True peak", "fail" if mastered else "warn",
                             f"{tp:.1f} dBTP",
                             f"over the {ceiling:g} dBTP ceiling; lossy encoders may clip"))

    # 3. Clipping in the uploaded file.
    if clipped_samples is None and x_in is not None:
        clipped_samples = count_clipped(x_in)
    if clipped_samples is not None:
        if clipped_samples >= CLIP_WARN_SAMPLES:
            checks.append(_check("source_clipping", "Clipping in the source", "warn",
                                 f"{clipped_samples} samples",
                                 "the uploaded file was already clipped; Shimmer cannot undo flat-topped peaks"))
        else:
            checks.append(_check("source_clipping", "Clipping in the source", "pass", "none", ""))

    # 4. Sample rate.
    if sr in (44100, 48000):
        checks.append(_check("sample_rate", "Sample rate", "pass", f"{sr / 1000:g} kHz",
                             "what the stores ask for"))
    elif sr in (88200, 96000, 176400, 192000):
        checks.append(_check("sample_rate", "Sample rate", "pass", f"{sr / 1000:g} kHz",
                             "hi-res; the stores accept it"))
    else:
        checks.append(_check("sample_rate", "Sample rate", "warn", f"{sr / 1000:g} kHz",
                             "unusual; the stores ask for 44.1 or 48 kHz"))

    # 5. Format.
    fmt = str((export or {}).get("format") or "").lower().lstrip(".")
    bits = (export or {}).get("bit_depth")
    if fmt in ("wav", "flac"):
        checks.append(_check("format", "Format", "pass",
                             f"{bits}-bit {fmt.upper()}" if bits else fmt.upper(),
                             "what the stores ask for"))
    elif fmt:
        checks.append(_check("format", "Format", "warn", fmt.upper(),
                             "fine for listening; upload WAV or FLAC to a store"))

    # 6-7. Silence at the edges.
    head_s, tail_s, silent = silence_at_edges(y, sr)
    if silent:
        checks.append(_check("head_silence", "Start", "fail", "silent",
                             "the whole file is below -60 dBFS"))
    else:
        if head_s <= HEAD_SILENCE_WARN_S:
            checks.append(_check("head_silence", "Start", "pass",
                                 f"{head_s:.2f} s of silence", ""))
        else:
            checks.append(_check("head_silence", "Start", "warn",
                                 f"{head_s:.1f} s of silence",
                                 "a long lead-in; Trim silence in Output removes it"))
        if tail_s <= TAIL_SILENCE_WARN_S:
            checks.append(_check("tail_silence", "End", "pass",
                                 f"{tail_s:.2f} s of silence", ""))
        else:
            checks.append(_check("tail_silence", "End", "warn",
                                 f"{tail_s:.1f} s of silence",
                                 "a long tail; Trim silence in Output removes it"))

    # 8. Length.
    dur = float(duration_s) if duration_s is not None else (n / sr if sr else 0.0)
    if dur >= MIN_DURATION_S:
        checks.append(_check("duration", "Length", "pass", _mmss(dur), ""))
    else:
        checks.append(_check("duration", "Length", "warn", _mmss(dur),
                             "under 30 seconds; the stores treat that differently"))

    # 9. DC offset.
    dc = float(np.max(np.abs(np.mean(y, axis=0)))) if n else 0.0
    if dc > DC_WARN:
        checks.append(_check("dc_offset", "DC offset", "warn",
                             f"{20.0 * np.log10(dc):.0f} dBFS",
                             "the waveform sits off centre; the high-pass in mastering removes it"))
    else:
        checks.append(_check("dc_offset", "DC offset", "pass", "none", ""))

    # 10. Mono compatibility.
    corr = _finite(correlation)
    if corr is None:
        checks.append(_check("mono", "Mono check", "info", "n/a",
                             "stereo correlation not measured"))
    elif corr < CORR_WARN:
        checks.append(_check("mono", "Mono check", "warn", f"correlation {corr:+.2f}",
                             "out of phase in places; the mix loses level played in mono"))
    elif corr < 0.2:
        checks.append(_check("mono", "Mono check", "pass", f"correlation {corr:+.2f}",
                             "very wide; worth a listen in mono"))
    else:
        checks.append(_check("mono", "Mono check", "pass", f"correlation {corr:+.2f}", ""))

    # 11-12. Tags, when the caller has them already.
    if tags_written is not None:
        checks.append(tags_check(tags, bool(tags_written)))
        checks.append(isrc_check(tags))

    return _with_summary({
        "checks": checks,
        "platforms": platform_changes(lufs),
        "lufs": lufs,
    })


def summary(report: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The verdict and the flagged labels, for a log line."""
    if not report:
        return None
    flags = [c["label"] for c in report.get("checks") or []
             if c.get("status") in ("warn", "fail")]
    return {"status": report.get("status"), "passed": report.get("passed"),
            "warned": report.get("warned"), "failed": report.get("failed"),
            "flags": flags[:4]}
