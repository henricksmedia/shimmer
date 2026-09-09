"""make_bench_set.py — build comparisons for the listening bench.

Usage:
    ./.venv/Scripts/python.exe scripts/make_bench_set.py tone
    ./.venv/Scripts/python.exe scripts/make_bench_set.py clean
    ./.venv/Scripts/python.exe scripts/make_bench_set.py both

`tone` is round 4.5: the tone target landed on 2026-09-09 against the one it
replaced, everything else held identical. That change moved the target about
8 dB through presence and air on the strength of measurement alone, and
nobody has heard it. It is the largest unheard change in the project.

`clean` puts an untouched render against the cleaned one, so the residual is
literally what the repair took out.

Excerpts are the loudest 30 seconds of each song, which is where a chorus
usually sits and where differences are easiest to hear. Level matching,
alignment and blinding are `abtest.build`'s job, not this script's.
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimmer import abtest                                   # noqa: E402
from shimmer import mastering as M                           # noqa: E402
from shimmer.audio_io import load_audio                      # noqa: E402
from shimmer.params import MasterParams                      # noqa: E402
from shimmer.pipeline import clean_and_master                # noqa: E402
from shimmer.presets import PRESETS                          # noqa: E402

SECONDS = 30.0

DERIVED = M._REF_SHAPE_DB.copy()
# The curve retracted on 2026-09-08 — one service's median on AI renders.
RETRACTED = np.array([
    -3.7, 4.3, 8.3, 8.8, 7.9, 7.4, 7.4, 6.3, 4.5, 2.1, 0.3, -0.7, 0.0, 0.5,
    -1.5, -1.5, -1.4, -0.7, 0.0, 0.6, 0.7, 1.1, -0.1, -1.0, -0.4,
    -1.5, -5.8, -13.1, -25.4,
], dtype=np.float64)


def use(shape):
    M._REF_SHAPE_DB = np.asarray(shape, dtype=np.float64)
    M._REF_DB = M._REF_SHAPE_DB - np.median(M._REF_SHAPE_DB[M._MID_BANDS])


def loudest(x, sr, seconds=SECONDS):
    """The densest stretch, by RMS. Usually a chorus."""
    n = int(seconds * sr)
    if x.shape[0] <= n:
        return np.ascontiguousarray(x)
    m = x.mean(axis=1) if x.ndim > 1 else x
    hop = int(sr)
    best, at = -1.0, 0
    for s in range(0, len(m) - n, hop):
        r = float(np.sqrt(np.mean(m[s:s + n] ** 2)))
        if r > best:
            best, at = r, s
    return np.ascontiguousarray(x[at:at + n])


def master(ref, sr, shape):
    use(shape)
    y, _, _ = clean_and_master(ref, sr, PRESETS["generic"](),
                               master_params=MasterParams(
                                   enabled=True, intensity="med",
                                   tilt="neutral"))
    return y


def tone_sets():
    made = []
    for p in sorted(glob.glob(os.path.join(ROOT, "sources", "suno-*.wav"))):
        song = os.path.basename(p).replace("suno-", "").replace(".wav", "")
        x, sr = load_audio(p)
        ref = loudest(x, sr)
        old = master(ref, sr, RETRACTED)
        new = master(ref, sr, DERIVED)
        m = abtest.build(
            f"tone-{song}", f"Tone target · {song.replace('-', ' ')}",
            [("old target (service curve)", old),
             ("new target (research + captures)", new)],
            sr,
            note=("Same song, same preset, same mastering. The only "
                  "difference is the tone target. The new one sits about "
                  "8 dB darker through presence and air."),
            residual_of=("old target (service curve)",
                         "new target (research + captures)"))
        made.append(m["id"])
        print(f"  {m['id']:<44} matched to {m['matched_lufs']:.1f} LUFS")
    use(DERIVED)
    return made


def clean_sets():
    made = []
    for p in sorted(glob.glob(os.path.join(ROOT, "sources", "suno-*.wav")))[:4]:
        song = os.path.basename(p).replace("suno-", "").replace(".wav", "")
        x, sr = load_audio(p)
        ref = loudest(x, sr)
        use(DERIVED)
        cleaned, _, _ = clean_and_master(ref, sr, PRESETS["generic"](),
                                         master_params=None, eq_params=None)
        n = min(len(ref), len(cleaned))
        m = abtest.build(
            f"clean-{song}", f"Cleaning · {song.replace('-', ' ')}",
            [("untouched render", ref[:n]), ("cleaned", cleaned[:n])],
            sr,
            note=("No mastering — cleaning only, so the tone target plays no "
                  "part. The removed part is literally what the repair took."),
            residual_of=("untouched render", "cleaned"))
        made.append(m["id"])
        print(f"  {m['id']:<44} matched to {m['matched_lufs']:.1f} LUFS")
    return made


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "tone"
    os.makedirs(abtest.BENCH, exist_ok=True)
    if what in ("tone", "both"):
        print("Tone target, old vs new:")
        tone_sets()
    if what in ("clean", "both"):
        print("Cleaning, untouched vs cleaned:")
        clean_sets()
    print(f"\nOpen http://localhost:7860/static/ab/")
