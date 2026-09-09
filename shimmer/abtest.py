"""
abtest.py — the listening bench: instant, level-matched, blind A/B.

Every listening round so far has been a folder of files. That instrument is
bad in three specific ways, and each one has already cost this project a
wrong conclusion:

  * you cannot switch instantly, so you compare B against your memory of A;
  * nothing enforces level matching, and the whole tone investigation began
    with an A/B where the preferred file was 2.7 LU louder;
  * per-file normalisation crept in unnoticed, and in round 1 one residual
    was given 26 dB more gain than another it was being compared with.

So the bench fixes those at the source rather than in the instructions.

**Level.** Arms are matched by integrated LUFS to the quietest of them
before they are written, and the applied gain is recorded in the manifest and
shown on the page. A comparison that has not been level-matched cannot be
built here.

**Instant switching** is the page's job: every arm plays at once and the
toggle moves gain between them, so the position never changes.

**The residual** — what a stage removed — is computed here rather than in the
browser, because it needs sample alignment to be meaningful. If the two arms
are offset by even a few samples the subtraction produces comb filtering, and
what you hear is the misalignment rather than the removal. It is aligned by
cross-correlation first, then lifted by a FIXED amount rather than normalised,
so a removal twice the size sounds twice as loud — normalising each one to the
same peak throws away the only thing worth knowing.

**Residuals mislead in a known way** and the page says so: removed air sounds
like *shhh* in isolation and never like music, so a listener correctly
reports "no music in there" while several dB of openness has gone. The
residual answers "was this noise or a cymbal", not "was it too much".

**Blind.** Arms are shuffled when a set is built and the key is stored
separately, so the page cannot leak it. Reveal is a deliberate second call.
"""
from __future__ import annotations

import json
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .audio_io import save_audio
from .mastering import measure_loudness

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "listening-test", "ab")

# A residual is quiet, so it needs lifting to be heard at all. This is a
# FIXED lift, not a normalisation, and the difference matters: normalising
# each residual to the same peak throws away how much was removed, which is
# the one thing worth knowing. A setting that takes twice as much should
# sound twice as loud here. In round 1 the residuals were normalised
# individually and one was given 26 dB more gain than the one it was being
# compared against, which made a heavy removal and a light one sound alike.
#
# The raw peak is recorded either way, so an inaudible residual can be read
# as "almost nothing was taken" rather than mistaken for a broken file.
RESIDUAL_LIFT_DB = 6.0


def _peak(x: np.ndarray) -> float:
    return float(np.max(np.abs(x))) if x.size else 0.0


def align(a: np.ndarray, b: np.ndarray, sr: int, max_ms: float = 20.0) -> int:
    """Samples b must be shifted by to line up with a. Usually 0.

    A zero-phase EQ and a compensated limiter should not move anything, but
    "should not" is why this is measured rather than assumed — an unnoticed
    offset turns a residual into comb filtering.
    """
    n = min(len(a), len(b), sr * 10)
    m = int(max_ms * sr / 1000.0)
    x = a[:n].mean(axis=1) if a.ndim > 1 else a[:n]
    y = b[:n].mean(axis=1) if b.ndim > 1 else b[:n]
    x = x - x.mean()
    y = y - y.mean()
    if not np.any(x) or not np.any(y):
        return 0
    best, lag = -np.inf, 0
    for k in range(-m, m + 1):
        xs = x[max(0, k):n + min(0, k)]
        ys = y[max(0, -k):n + min(0, -k)]
        if len(xs) < sr:
            continue
        c = float(np.dot(xs, ys) / (np.linalg.norm(xs) * np.linalg.norm(ys) + 1e-20))
        if c > best:
            best, lag = c, k
    return lag


def build(set_id: str, title: str, arms: List[Tuple[str, np.ndarray]], sr: int,
          note: str = "", residual_of: Optional[Tuple[str, str]] = None,
          seed: Optional[int] = None) -> Dict[str, Any]:
    """Write a comparison set. `arms` is [(true_label, audio), ...].

    Everything is level-matched to the quietest arm before writing, so the
    files on disk are already comparable and nothing downstream has to
    remember to do it.
    """
    if len(arms) < 2:
        raise ValueError("a comparison needs at least two arms")
    out = os.path.join(BENCH, set_id)
    os.makedirs(out, exist_ok=True)

    # Trim every arm to the shortest, so the page can loop one region across
    # all of them without running off the end of one.
    n = min(len(a) for _, a in arms)
    arms = [(lab, np.asarray(a[:n], dtype=np.float64)) for lab, a in arms]

    lufs = [float(measure_loudness(a, sr)["lufs_i"]) for _, a in arms]
    quietest = min(lufs)
    gains = [quietest - l for l in lufs]              # all <= 0, so no clipping
    matched = [(lab, a * (10.0 ** (g / 20.0)))
               for (lab, a), g in zip(arms, gains)]

    rows: List[Dict[str, Any]] = []
    for i, ((lab, a), g, l) in enumerate(zip(matched, gains, lufs)):
        rows.append({"arm": f"arm{i}", "true_label": lab,
                     "lufs_before": round(l, 2), "gain_db": round(g, 2),
                     "lufs_after": round(quietest, 2),
                     "peak_dbfs": round(20.0 * np.log10(max(_peak(a), 1e-9)), 2),
                     "file": f"arm{i}.wav"})
        save_audio(os.path.join(out, f"arm{i}.wav"), a, sr)

    # The residual: what one arm has and the other does not.
    residual = None
    if residual_of:
        la, lb = residual_of
        ia = next(i for i, r in enumerate(rows) if r["true_label"] == la)
        ib = next(i for i, r in enumerate(rows) if r["true_label"] == lb)
        a, b = matched[ia][1], matched[ib][1]
        lag = align(a, b, sr)
        if lag > 0:
            b = np.concatenate([np.zeros((lag,) + b.shape[1:]), b])[:len(a)]
        elif lag < 0:
            b = b[-lag:]
            b = np.concatenate([b, np.zeros((len(a) - len(b),) + b.shape[1:])])
        d = a[:len(b)] - b
        pk = _peak(d)
        rg = RESIDUAL_LIFT_DB
        lifted = d * (10.0 ** (rg / 20.0))
        # Only pull back if the fixed lift would clip, and say by how much,
        # so the "louder means more was removed" reading still holds.
        clip_trim = 0.0
        if _peak(lifted) > 0.99:
            clip_trim = 20.0 * np.log10(0.99 / _peak(lifted))
            lifted = lifted * (10.0 ** (clip_trim / 20.0))
        save_audio(os.path.join(out, "residual.wav"), lifted, sr)
        residual = {"file": "residual.wav", "of": [la, lb],
                    "align_samples": int(lag),
                    "gain_db": round(float(rg + clip_trim), 2),
                    "fixed_lift_db": RESIDUAL_LIFT_DB,
                    "clip_trim_db": round(float(clip_trim), 2),
                    "peak_dbfs_raw": round(20.0 * np.log10(max(pk, 1e-9)), 2),
                    "rms_dbfs_raw": round(10.0 * np.log10(
                        max(float(np.mean(d ** 2)), 1e-20)), 2)}

    order = list(range(len(rows)))
    random.Random(seed if seed is not None else set_id).shuffle(order)
    shown = [chr(ord("A") + i) for i in range(len(rows))]

    manifest = {
        "id": set_id, "title": title, "note": note,
        "sr": sr, "seconds": round(n / sr, 2),
        "matched_lufs": round(quietest, 2),
        "residual": residual,
        # what the page may see: letters, files, and the level proof
        "arms": [{"letter": shown[j], "file": rows[order[j]]["file"],
                  "gain_db": rows[order[j]]["gain_db"],
                  "lufs_before": rows[order[j]]["lufs_before"]}
                 for j in range(len(rows))],
    }
    key = {"id": set_id,
           "answer": {shown[j]: rows[order[j]]["true_label"]
                      for j in range(len(rows))},
           "arms": rows}
    _write(os.path.join(out, "manifest.json"), manifest)
    _write(os.path.join(out, "ANSWER-KEY.json"), key)
    return manifest


def _write(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1)
        fh.write("\n")


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def sets() -> List[Dict[str, Any]]:
    """Every comparison on the bench, newest first."""
    out = []
    if not os.path.isdir(BENCH):
        return out
    for name in os.listdir(BENCH):
        m = _read(os.path.join(BENCH, name, "manifest.json"))
        if not m:
            continue
        scores = _read(os.path.join(BENCH, name, "SCORES.json")) or {"rounds": []}
        m = dict(m)
        m["judged"] = len(scores.get("rounds", []))
        out.append({k: m[k] for k in ("id", "title", "note", "seconds",
                                      "matched_lufs", "judged")
                    if k in m})
    return sorted(out, key=lambda r: r["id"])


def manifest(set_id: str) -> Optional[Dict[str, Any]]:
    return _read(os.path.join(BENCH, _safe(set_id), "manifest.json"))


def reveal(set_id: str) -> Optional[Dict[str, Any]]:
    return _read(os.path.join(BENCH, _safe(set_id), "ANSWER-KEY.json"))


def audio_path(set_id: str, filename: str) -> Optional[str]:
    if not filename.endswith(".wav") or "/" in filename or "\\" in filename:
        return None
    p = os.path.join(BENCH, _safe(set_id), filename)
    return p if os.path.isfile(p) else None


def score(set_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Record one judgement. Appended, never overwritten — a second opinion
    on the same set is data, not a correction."""
    d = os.path.join(BENCH, _safe(set_id))
    if not os.path.isdir(d):
        return {"ok": False, "error": "no such set"}
    path = os.path.join(d, "SCORES.json")
    doc = _read(path) or {"id": set_id, "rounds": []}
    key = reveal(set_id) or {}
    picked = str(payload.get("preferred") or "")
    doc["rounds"].append({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "preferred_letter": picked,
        "preferred_label": key.get("answer", {}).get(picked, ""),
        "confidence": str(payload.get("confidence") or ""),
        "revealed_first": bool(payload.get("revealed_first")),
        "switches": int(payload.get("switches") or 0),
        "seconds_listened": round(float(payload.get("seconds") or 0.0), 1),
        "note": str(payload.get("note") or "")[:2000],
    })
    _write(path, doc)
    return {"ok": True, "rounds": len(doc["rounds"])}


def scores(set_id: str) -> Dict[str, Any]:
    return _read(os.path.join(BENCH, _safe(set_id), "SCORES.json")) or {"rounds": []}


def _safe(set_id: str) -> str:
    keep = "-_." + "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(c for c in str(set_id) if c in keep)[:80]
