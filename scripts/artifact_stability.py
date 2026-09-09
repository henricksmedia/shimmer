"""
artifact_stability.py — Is the hash measurement noise, or is it real?

The budget gates on `flicker_excess_db`: excess amplitude modulation in
4.5-12 kHz over the same measure in the mids. It decides whether a track has
an artifact worth removing at all, so if it is unreliable, everything built on
it is unreliable.

It is currently taken from ONE 5-second window, chosen by a heuristic. Change
the excerpt and the clean/don't-clean decision was seen to flip on three of
four songs. This script establishes WHY before anything is changed, because
the two possible causes need opposite fixes:

  * **Noise.** The estimator is jittery on short windows. Then the fix is a
    robust statistic over many windows, and the variance should shrink roughly
    as 1/sqrt(window length).
  * **Signal.** The hash genuinely varies across a track - denser under
    sustained pads, absent under sparse verses. Then a single track-level
    number is wrong in principle, a median would paper over real structure,
    and the budget has to become time-varying.

The discriminator is autocorrelation. Noise is independent window to window;
real structure persists, so neighbouring windows agree more than distant ones.

Reports, per track: the per-window series, its spread, lag-1 autocorrelation,
and how a whole-track median compares with the single-window value the code
uses today.

Usage:  python scripts/artifact_stability.py [--json out.json]
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.audio_io import load_audio          # noqa: E402
from shimmer.detect import _flicker              # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where to look for AI source renders. Sources live outside the repo, so this
# is a list of folders rather than one fixed path.
SOURCE_GLOBS = [
    os.path.join(ROOT, "sources", "suno-*.wav"),
    r"D:\MusicVault\The Treq\albums\The Fifth Direction\suno\*.wav",
]

WINDOW_S = 5.0          # what the detector uses today
HOP_S = 5.0             # non-overlapping, so windows are independent samples
LONG_WINDOWS = (5.0, 10.0, 20.0)   # for the 1/sqrt(N) test
MAX_TRACK_S = 300.0


def windows(mono: np.ndarray, sr: int, win_s: float, hop_s: float):
    n = int(win_s * sr)
    hop = int(hop_s * sr)
    for start in range(0, max(0, len(mono) - n), hop):
        yield mono[start:start + n]


def flicker_series(mono: np.ndarray, sr: int, win_s: float) -> np.ndarray:
    out = []
    for w in windows(mono, sr, win_s, win_s):
        _, _, ex = _flicker(np.asarray(w, dtype=np.float32), sr)
        out.append(ex)
    return np.array(out, dtype=np.float64)


def lag1(x: np.ndarray) -> float:
    """Do neighbouring windows agree? ~0 means independent draws (noise);
    clearly positive means the value is tracking something real."""
    if len(x) < 4 or np.std(x) < 1e-9:
        return float("nan")
    a, b = x[:-1], x[1:]
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def main(argv) -> int:
    paths = []
    for g in SOURCE_GLOBS:
        paths.extend(sorted(glob.glob(g)))
    if not paths:
        print("No source renders found. Check SOURCE_GLOBS.")
        return 1

    print(f"{len(paths)} source renders\n")
    print(f"{'track':38s} {'n':>4} {'median':>7} {'p10':>6} {'p90':>6} "
          f"{'sd':>6} {'lag1':>6} {'hot1':>7}")

    rows = []
    for p in paths:
        try:
            x, sr = load_audio(p)
        except Exception as e:  # noqa: BLE001
            print(f"{os.path.basename(p)[:38]:38s} unreadable: {e}")
            continue
        mono = x.mean(axis=1) if x.ndim > 1 else x
        mono = mono[:int(MAX_TRACK_S * sr)]
        s = flicker_series(mono, sr, WINDOW_S)
        if s.size < 4:
            continue
        # What a single-window pick would have said: the loudest window, which
        # is what the detector's heuristic approximates.
        energies = [float(np.mean(w.astype(np.float64) ** 2))
                    for w in windows(mono, sr, WINDOW_S, WINDOW_S)]
        hot = float(s[int(np.argmax(energies))]) if energies else float("nan")

        row = {
            "track": os.path.basename(p),
            "n": int(s.size),
            "median": float(np.median(s)),
            "p10": float(np.percentile(s, 10)),
            "p90": float(np.percentile(s, 90)),
            "sd": float(np.std(s)),
            "lag1": lag1(s),
            "hot_window": hot,
            "series": [round(float(v), 3) for v in s],
        }
        rows.append(row)
        print(f"{row['track'][:38]:38s} {row['n']:4d} {row['median']:7.2f} "
              f"{row['p10']:6.2f} {row['p90']:6.2f} {row['sd']:6.2f} "
              f"{row['lag1']:6.2f} {row['hot_window']:7.2f}")

    print()
    lags = np.array([r["lag1"] for r in rows if np.isfinite(r["lag1"])])
    sds = np.array([r["sd"] for r in rows])
    print("=== Is it noise or signal? ===")
    print(f"lag-1 autocorrelation across {lags.size} tracks: "
          f"median {np.median(lags):.3f}, "
          f"{100.0 * np.mean(lags > 0.3):.0f}% above 0.3")
    print(f"within-track spread (sd): median {np.median(sds):.2f} dB, "
          f"max {sds.max():.2f} dB")
    verdict = ("SIGNAL - the value tracks real structure; a single number "
               "per track discards it"
               if np.median(lags) > 0.3 else
               "NOISE - windows are near-independent; a robust statistic "
               "over the track is the right fix")
    print(f"verdict: {verdict}")

    print()
    print("=== Does averaging longer windows shrink the spread? ===")
    print("(noise shrinks ~1/sqrt(N); real structure does not)")
    sample = rows[:6]
    print(f"{'track':30s}" + "".join(f"{w:>8.0f}s" for w in LONG_WINDOWS))
    for r in sample:
        p = next(q for q in paths if os.path.basename(q) == r["track"])
        x, sr = load_audio(p)
        mono = x.mean(axis=1) if x.ndim > 1 else x
        mono = mono[:int(MAX_TRACK_S * sr)]
        line = f"{r['track'][:30]:30s}"
        for w in LONG_WINDOWS:
            ss = flicker_series(mono, sr, w)
            line += f"{np.std(ss):9.2f}" if ss.size >= 3 else "      n/a"
        print(line)

    print()
    print("=== How often would the single-window pick disagree with the "
          "track median? ===")
    from shimmer.budget import EXCESS_FLOOR_DB
    flips = [r for r in rows
             if (r["hot_window"] > EXCESS_FLOOR_DB) != (r["median"] > EXCESS_FLOOR_DB)]
    print(f"{len(flips)} of {len(rows)} tracks change their clean/don't-clean "
          f"answer ({100.0 * len(flips) / max(len(rows), 1):.0f}%)")
    for r in flips:
        print(f"   {r['track'][:44]:44s} hot {r['hot_window']:+.2f} vs "
              f"median {r['median']:+.2f}")

    if "--json" in argv:
        out = argv[argv.index("--json") + 1]
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"window_s": WINDOW_S, "tracks": rows}, f, indent=1)
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
