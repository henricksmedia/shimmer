"""
build_tone_reference.py — Derive a tone target from real masters.

`_REF_SHAPE_DB` in mastering.py is the neutral curve every automatic tone
decision is measured against. It is faithful to the study it cites, but that
study averages recordings from **1950 to 2010** and itself reports the
spectrum flattening since the 2000s. Using a sixty-year average as a
present-day target is why a contemporary master reads as "too bright" and why
every automatic decision comes out a cut (docs/BRIGHTNESS-ASSESSMENT.md §2.1).

The catalogue contains ~500 masters produced by one automated service, and
the service stamps its settings into the filename. That gives something the
literature cannot: a large set of masters **labelled by the tone setting used**,
spanning intensity Low/Medium/High against Warmer/Warm/Neutral/Bright/Brighter.

Three things come out of that:

  1. **A present-day neutral target** — the median curve of the Neutral
     masters, with its spread. A target with a tolerance band, measured, not
     inherited from a historical average.
  2. **The size and shape of a real tilt control** — how far Warmer differs
     from Brighter at fixed intensity. Shimmer's own tilt is +/-2 dB and
     cannot exceed +0.5 dB in 5-12 kHz; this says what a shipping tool
     actually moves.
  3. **What intensity does to tone**, separately from what the EQ setting does.

Scope, stated plainly: these are masters of AI renders from one catalogue,
processed by one service. That makes this the right target for *this* tool and
not a general commercial reference. It replaces a wrong universal curve with a
measured specific one, which is an improvement, not a proof.

Usage:
    python scripts/build_tone_reference.py [--limit N] [--out FILE]
"""
from __future__ import annotations

import collections
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from corpus_check import split_settings                       # noqa: E402
from shimmer.audio_io import load_audio                       # noqa: E402
from shimmer.mastering import (analyze_spectrum, measure_loudness,  # noqa: E402
                               measure_true_peak_db,
                               relative_band_levels, _REF_DB, _REF_FREQS)

ROOTS = [
    r"D:\MusicVault\The Treq\albums",
    r"D:\MusicVault\Avey Kay\albums",
    r"D:\MusicVault\Jackson Ryle\albums",
    r"D:\MusicVault\Singles",
    r"D:\DownloadVault",
]
INTENSITIES = ("Low", "Medium", "High")
EQ_SETTINGS = ("Warmer", "Warm", "Neutral", "Bright", "Brighter")
MIN_PER_CELL = 8          # below this a median is not worth reporting
EXCERPT_S = 90.0          # enough for a stable long-term average


def find_masters():
    """Every Mixea master, deduplicated by (song, setting).

    The same master is often filed in several places — an album folder, a
    distribute folder, a download folder. Counting the copies would weight
    those songs more heavily in the median, so the reference curve would drift
    toward whichever tracks happen to be filed twice. Keyed on (song, setting)
    because the same song mastered Bright and Warm is two genuine data points.
    """
    seen = {}
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for fn in files:
                if not fn.lower().endswith(".wav"):
                    continue
                song, meta = split_settings(fn)
                if meta.get("service", "").lower() != "mixea":
                    continue
                key = (song.strip().lower(), meta.get("settings", ""))
                seen.setdefault(key, (os.path.join(dirpath, fn), song,
                                      meta.get("settings", "")))
    return list(seen.values())


def split_setting(s: str):
    for i in INTENSITIES:
        if s.startswith(i):
            rest = s[len(i):]
            return i, (rest if rest in EQ_SETTINGS else None)
    return None, None


def measure(path: str):
    x, sr = load_audio(path)
    n = int(EXCERPT_S * sr)
    if x.shape[0] > n:                     # middle, past intro and outro
        start = (x.shape[0] - n) // 2
        x = x[start:start + n]
    rel = relative_band_levels(
        np.array(analyze_spectrum(x, sr)["band_power_db"]))
    L = measure_loudness(x, sr)
    return rel, L.get("lufs_i"), L.get("lra"), measure_true_peak_db(x, sr)


def main(argv) -> int:
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 0
    out_path = (argv[argv.index("--out") + 1] if "--out" in argv
                else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "..", "docs", "tone-reference.json"))

    masters = find_masters()
    if limit:
        masters = masters[:limit]
    print(f"{len(masters)} masters to measure\n")

    cells = collections.defaultdict(list)
    levels = collections.defaultdict(list)
    rows_out = []
    failed = 0
    for i, (path, _song, setting) in enumerate(masters, 1):
        intensity, eq = split_setting(setting)
        if eq is None:
            continue
        try:
            rel, lufs, lra, tp = measure(path)
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        cells[(intensity, eq)].append(rel)
        levels[(intensity, eq)].append((lufs, lra, tp))
        rows_out.append({
            "song": _song,
            "intensity": intensity,
            "eq": eq,
            "rel_db": [round(float(v), 2) for v in rel],
            "lufs": round(float(lufs), 2) if lufs is not None else None,
            "lra": round(float(lra), 2) if lra is not None else None,
            "true_peak": round(float(tp), 2),
        })
        if i % 25 == 0:
            print(f"  {i}/{len(masters)}")

    print(f"\nmeasured {sum(len(v) for v in cells.values())}, "
          f"{failed} unreadable\n")

    # 1. The neutral target: every Neutral master, any intensity.
    neutral = [r for (i, e), rows in cells.items() if e == "Neutral"
               for r in rows]
    # The per-track rows are the durable artifact, not the aggregates.
    #
    # The audio lives outside this repo, in a private catalogue, and one day it
    # will move or go. A file holding only medians would make the reference
    # unrebuildable the moment that happened: no way to recompute a different
    # statistic, exclude a subset, or re-derive after fixing a measurement bug
    # — the curve would become a number nobody could check or reproduce.
    #
    # 309 tracks x 29 bands is a few hundred kB of JSON. Keeping every row
    # means the aggregates below are always recomputable from this file alone,
    # and the corpus can be extended or corrected without the originals.
    result = {
        "version": 1,
        "method": {
            "excerpt_s": EXCERPT_S,
            "bands": "1/3-octave band power, dB relative to the median of "
                     "200 Hz-2 kHz (same normalisation as mastering._REF_DB)",
            "analyzer": "shimmer.mastering.analyze_spectrum",
            "note": "Masters of AI renders produced by one automated "
                    "mastering service, labelled by the setting used. This is "
                    "a target for this tool's material, not a general "
                    "commercial reference.",
        },
        "bands_hz": [float(f) for f in _REF_FREQS],
        "tracks": [],
        "cells": {},
    }
    if neutral:
        arr = np.array(neutral)
        med = np.median(arr, axis=0)
        lo = np.percentile(arr, 16, axis=0)
        hi = np.percentile(arr, 84, axis=0)
        result["neutral"] = {
            "n": len(neutral),
            "median_db": [round(float(v), 2) for v in med],
            "p16_db": [round(float(v), 2) for v in lo],
            "p84_db": [round(float(v), 2) for v in hi],
        }
        print("=== Measured neutral target vs the curve in the code ===")
        print(f"{'Hz':>7} {'measured':>9} {'+/-1sd':>9} {'_REF_DB':>9} {'diff':>7}")
        for j, f in enumerate(_REF_FREQS):
            if f < 40 or f > 20000:
                continue
            print(f"{f:7.0f} {med[j]:9.2f} {0.5*(hi[j]-lo[j]):9.2f} "
                  f"{_REF_DB[j]:9.2f} {med[j]-_REF_DB[j]:+7.2f}")

    # 2. What the tone control actually moves, at fixed intensity.
    print("\n=== What the EQ setting moves (Medium intensity) ===")
    base = cells.get(("Medium", "Neutral"))
    if base:
        b = np.median(np.array(base), axis=0)
        print(f"{'Hz':>7}" + "".join(f"{e[:8]:>9}" for e in EQ_SETTINGS
                                     if e != "Neutral"))
        for j, f in enumerate(_REF_FREQS):
            if f < 100 or f > 16000:
                continue
            line = f"{f:7.0f}"
            for e in EQ_SETTINGS:
                if e == "Neutral":
                    continue
                rows = cells.get(("Medium", e))
                if not rows or len(rows) < MIN_PER_CELL:
                    line += "      n/a"
                else:
                    line += f"{np.median(np.array(rows), axis=0)[j] - b[j]:9.2f}"
            print(line)

    for (i, e), rows in sorted(cells.items()):
        arr = np.array(rows)
        lv = [l for l in levels[(i, e)] if l[0] is not None]
        result["cells"][f"{i}{e}"] = {
            "n": len(rows),
            "median_db": [round(float(v), 2) for v in np.median(arr, axis=0)],
            "lufs_median": round(float(np.median([l[0] for l in lv])), 2) if lv else None,
            "true_peak_median": round(float(np.median([l[2] for l in lv])), 2) if lv else None,
        }

    print("\n=== Level by intensity ===")
    print(f"{'cell':18s} {'n':>4} {'LUFS':>8} {'true peak':>10}")
    for k, v in sorted(result["cells"].items()):
        if v["n"] >= MIN_PER_CELL:
            print(f"{k:18s} {v['n']:4d} {v['lufs_median']:8.2f} "
                  f"{v['true_peak_median']:10.2f}")

    result["tracks"] = rows_out
    out_path = os.path.abspath(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
