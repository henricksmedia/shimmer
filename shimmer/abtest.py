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
import re
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


def _song_correlation(a: np.ndarray, d: np.ndarray) -> float:
    """How much of the difference signal is just the song again.

    Subtracting two versions of one song gives very different things
    depending on what was done to them, and the two are easy to confuse:

      * a stage REMOVED something — the difference is the removed material
        and barely correlates with the music;
      * a stage RESHAPED everything — an EQ change, say — and the difference
        is the whole song through the difference filter. Nothing was removed.
        It sounds like the song at low volume, because it is.

    Correlation tells them apart, so a set cannot claim to show a removal
    when it is showing an EQ move.
    """
    x = a.mean(axis=1) if a.ndim > 1 else a
    y = d.mean(axis=1) if d.ndim > 1 else d
    n = min(len(x), len(y))
    x, y = x[:n] - np.mean(x[:n]), y[:n] - np.mean(y[:n])
    den = float(np.linalg.norm(x) * np.linalg.norm(y))
    return float(abs(np.dot(x, y)) / den) if den > 1e-20 else 0.0


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


# A set id becomes a folder name, so it has to be one. Sanitising by dropping
# bad characters is not enough: "." and ".." survive that, and joining ".."
# onto the bench walks out of it — manifest("..") read listening-test/
# manifest.json and score("..") WROTE listening-test/SCORES.json. Requiring a
# leading letter or digit makes both impossible.
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_WAV_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\.wav$")


def _safe(set_id: str) -> str:
    """The folder name this id may use, or "" if it may not have one."""
    s = str(set_id)
    return s if _ID_RE.match(s) else ""


def _set_dir(set_id: str) -> Optional[str]:
    """The folder for a set, or None. The realpath check is the backstop: it
    also catches a set folder that is a symlink pointing out of the bench."""
    name = _safe(set_id)
    if not name:
        return None
    root = os.path.realpath(BENCH)
    d = os.path.realpath(os.path.join(root, name))
    return d if d.startswith(root + os.sep) else None


def manifest(set_id: str) -> Optional[Dict[str, Any]]:
    d = _set_dir(set_id)
    return _read(os.path.join(d, "manifest.json")) if d else None


def reveal(set_id: str) -> Optional[Dict[str, Any]]:
    d = _set_dir(set_id)
    return _read(os.path.join(d, "ANSWER-KEY.json")) if d else None


def scores(set_id: str) -> Dict[str, Any]:
    d = _set_dir(set_id)
    doc = _read(os.path.join(d, "SCORES.json")) if d else None
    return doc or {"rounds": []}


def audio_path(set_id: str, filename: str) -> Optional[str]:
    d = _set_dir(set_id)
    if d is None or not _WAV_RE.match(str(filename)):
        return None
    root = os.path.realpath(BENCH)
    p = os.path.realpath(os.path.join(d, filename))
    return p if p.startswith(root + os.sep) and os.path.isfile(p) else None


def _num(v: Any, default: float = 0.0) -> float:
    """A number from whatever the page sent. A bad field must not 500 and
    lose the whole verdict — the words in the note are the valuable part."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if np.isfinite(f) else default


def score(set_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Record one judgement. Appended, never overwritten — a second opinion
    on the same set is data, not a correction."""
    d = _set_dir(set_id)
    if d is None or not os.path.isdir(d):
        return {"ok": False, "error": "no such set"}
    path = os.path.join(d, "SCORES.json")
    doc = _read(path) or {"id": _safe(set_id), "rounds": []}
    if not isinstance(doc.get("rounds"), list):
        doc = {"id": _safe(set_id), "rounds": []}
    key = reveal(set_id) or {}
    picked = str(payload.get("preferred") or "")
    row = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "preferred_letter": picked,
        "preferred_label": key.get("answer", {}).get(picked, ""),
        "confidence": str(payload.get("confidence") or ""),
        "revealed_first": bool(payload.get("revealed_first")),
        "switches": int(_num(payload.get("switches"))),
        "seconds_listened": round(_num(payload.get("seconds")), 1),
        "note": str(payload.get("note") or "")[:2000],
    }
    # Fields other parts of the bench add (the ABX result, for one) ride
    # along untouched, so this function does not need editing for each one.
    for k in ("abx", "trials", "correct", "p_value", "round"):
        if k in payload:
            row[k] = payload[k]
    doc["rounds"].append(row)
    try:
        _write(path, doc)
    except OSError as e:
        return {"ok": False, "error": f"could not write the verdict: {e}"}
    return {"ok": True, "rounds": len(doc["rounds"])}


def _prepare(arms: List[Any], sr: int) -> List[Tuple[str, np.ndarray]]:
    """Check the arms can honestly be compared, and return them as 2-D float.

    An arm may be given as (label, audio) or (label, audio, sample_rate).
    The third form is the one that matters: build() writes every arm with the
    set's `sr`, so an arm that arrived at a different rate would be written
    with the wrong header and play at the wrong speed — a 48 kHz master
    written as 44.1 kHz plays 8.8 percent slow and drops a semitone. The two
    arms would then differ in pitch and tempo, which is the loudest
    difference in the set and has nothing to do with mastering. There is no
    way to notice that later: the files on disk all agree with each other.
    So callers that load arms from separate files should pass each rate and
    find out here, at build time, when it can still be fixed.
    """
    out: List[Tuple[str, np.ndarray]] = []
    for i, item in enumerate(arms):
        if len(item) == 3:
            lab, a, a_sr = item
        else:
            (lab, a), a_sr = item, sr
        if int(a_sr) != int(sr):
            raise ValueError(
                f"arm {i} ({lab!r}) is {int(a_sr)} Hz but this set is being "
                f"written at {int(sr)} Hz. Written as it is, that arm would "
                f"play at the wrong speed and the comparison would be "
                f"nonsense. Resample it to {int(sr)} Hz first.")
        a = np.asarray(a, dtype=np.float64)
        if a.ndim == 1:
            a = a[:, None]
        if a.ndim != 2 or a.shape[0] == 0:
            raise ValueError(f"arm {i} ({lab!r}) is not audio")
        if not np.all(np.isfinite(a)):
            raise ValueError(f"arm {i} ({lab!r}) has NaN or infinite samples")
        out.append((str(lab), a))

    widths = {a.shape[1] for _, a in out}
    if len(widths) > 1:
        raise ValueError(
            "the arms do not have the same channel count, so they cannot be "
            "compared: "
            + ", ".join(f"{lab} = {a.shape[1]}" for lab, a in out))
    labels = [lab for lab, _ in out]
    if len(set(labels)) != len(labels):
        raise ValueError("two arms share a label, so the answer key and the "
                         "residual cannot tell them apart: "
                         + ", ".join(labels))
    return out


def build(set_id: str, title: str, arms: List[Any], sr: int,
          note: str = "", residual_of: Optional[Tuple[str, str]] = None,
          residual_kind: str = "removed",
          seed: Optional[int] = None) -> Dict[str, Any]:
    """Write a comparison set. `arms` is [(true_label, audio), ...], or
    [(true_label, audio, sample_rate), ...] when the arms came from separate
    files and their rates should be checked against the set's.

    Everything is level-matched to the quietest arm before writing, so the
    files on disk are already comparable and nothing downstream has to
    remember to do it.
    """
    if len(arms) < 2:
        raise ValueError("a comparison needs at least two arms")
    if not _safe(set_id):
        raise ValueError(
            f"{set_id!r} cannot be a set id. Start with a letter or digit and "
            f"use only letters, digits, dot, dash and underscore.")
    out = os.path.join(BENCH, _safe(set_id))
    os.makedirs(out, exist_ok=True)

    prepared = _prepare(arms, sr)

    # Trim every arm to the shortest, so the page can loop one region across
    # all of them without running off the end of one.
    n = min(len(a) for _, a in prepared)
    prepared = [(lab, np.ascontiguousarray(a[:n])) for lab, a in prepared]
    if n < sr:
        raise ValueError(f"the shortest arm is {n / sr:.2f} s, which is too "
                         f"short to judge and too short to measure loudness")

    lufs = [float(measure_loudness(a, sr)["lufs_i"]) for _, a in prepared]

    # A silent arm reads as -inf LUFS, and -inf then becomes the target every
    # other arm is matched to: each gain is -inf dB, every arm is multiplied
    # by zero, and the set is written as silence. It does not fail — it fails
    # later, and quietly, because -inf is not valid JSON and the route that
    # serves the manifest returns 500 while the page keeps the previous set's
    # audio on screen. Say it here instead.
    dead = [lab for lab, l in zip([p[0] for p in prepared], lufs)
            if not np.isfinite(l)]
    if dead:
        raise ValueError(
            "these arms are silent, or too quiet to measure: "
            + ", ".join(dead)
            + ". Matching to them would multiply every arm by zero and write "
              "a set of silence.")

    quietest = min(lufs)
    gains = [quietest - l for l in lufs]              # all <= 0, so no clipping
    matched = [(lab, a * (10.0 ** (g / 20.0)))
               for (lab, a), g in zip(prepared, gains)]

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
        try:
            ia = next(i for i, r in enumerate(rows) if r["true_label"] == la)
            ib = next(i for i, r in enumerate(rows) if r["true_label"] == lb)
        except StopIteration:
            raise ValueError(
                f"the residual asks for {la!r} minus {lb!r}, but the arms are "
                + ", ".join(repr(r["true_label"]) for r in rows)) from None
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
        corr = _song_correlation(a, d)
        # If the caller says "removed" but the signal is largely the song
        # again, the caller is wrong. Say so in the manifest rather than
        # letting the page put a misleading word on a button.
        measured = "eq" if corr >= 0.25 else "removed"
        kind = residual_kind if residual_kind in ("removed", "eq") else "removed"
        residual = {"file": "residual.wav", "of": [la, lb],
                    "align_samples": int(lag),
                    "gain_db": round(float(rg + clip_trim), 2),
                    "fixed_lift_db": RESIDUAL_LIFT_DB,
                    "clip_trim_db": round(float(clip_trim), 2),
                    "peak_dbfs_raw": round(20.0 * np.log10(max(pk, 1e-9)), 2),
                    "rms_dbfs_raw": round(10.0 * np.log10(
                        max(float(np.mean(d ** 2)), 1e-20)), 2),
                    "kind": kind,
                    "song_correlation": round(corr, 3),
                    "kind_disagrees": bool(kind != measured),
                    "label": ("The tone change" if kind == "eq"
                              else "What was removed"),
                    "explain": (
                        "Nothing was removed here. Both versions are the same "
                        "audio with a different EQ, so this is the whole song "
                        "through the difference between the two curves. It is "
                        "meant to sound like the song, quietly, weighted "
                        "toward the frequencies the two targets disagree "
                        "about."
                        if kind == "eq" else
                        "What one version has and the other does not. It tells "
                        "you whether the thing taken out was noise or music. "
                        "It cannot tell you whether too much was taken: "
                        "removed air sounds like shhh on its own and never "
                        "like music.")}

    order = list(range(len(rows)))
    random.Random(seed if seed is not None else set_id).shuffle(order)
    shown = [chr(ord("A") + i) for i in range(len(rows))]

    manifest_doc = {
        "id": _safe(set_id), "title": title, "note": note,
        "sr": sr, "channels": int(prepared[0][1].shape[1]),
        "seconds": round(n / sr, 2),
        "matched_lufs": round(quietest, 2),
        # How far apart the arms were before matching. A big number is not an
        # error, but it is worth seeing: it is how much the match had to do.
        "level_spread_db": round(max(lufs) - min(lufs), 2),
        "residual": residual,
        # what the page may see: letters, files, and the level proof
        "arms": [{"letter": shown[j], "file": rows[order[j]]["file"],
                  "gain_db": rows[order[j]]["gain_db"],
                  "lufs_before": rows[order[j]]["lufs_before"]}
                 for j in range(len(rows))],
    }
    key = {"id": _safe(set_id),
           "answer": {shown[j]: rows[order[j]]["true_label"]
                      for j in range(len(rows))},
           "arms": rows}
    _write(os.path.join(out, "manifest.json"), manifest_doc)
    _write(os.path.join(out, "ANSWER-KEY.json"), key)
    return manifest_doc
