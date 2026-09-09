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
# What shipped before 97609c0: the 1950-2010 average. These are the masters
# the "dull and flat" complaint was actually made about, so this curve is the
# one the current chain has to beat.
PESTANA = np.array([
    -2.5, 1.0, 3.5, 4.5, 5.0, 5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0,
    0.5, 0.0, -0.5, -1.0, -1.5, -2.0, -2.5, -3.0, -4.3, -5.8, -7.5,
    -9.5, -12.0, -16.0, -22.0,
], dtype=np.float64)
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
            note='Same song, same preset, same mastering. The only thing that differs is the tone target the chain aimed at.',
            residual_of=("old target (service curve)",
                         "new target (research + captures)"),
            residual_kind="eq")
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
            residual_of=("untouched render", "cleaned"),
            residual_kind="removed")
        made.append(m["id"])
        print(f"  {m['id']:<44} matched to {m['matched_lufs']:.1f} LUFS")
    return made


def service_sets():
    """The judgement this whole investigation rests on, made fairly.

    "The service master sounded better and richer" was the finding that
    started everything, and it was made unmatched: those masters are 2.7 LU
    louder, 3.4 dB heavier in the bass and 8.8 dB brighter on average. All
    three flatter on an A/B. With the level matched and the labels hidden,
    does it still hold?
    """
    made = []
    for p in sorted(glob.glob(os.path.join(ROOT, "sources", "suno-*.wav"))):
        song = os.path.basename(p).replace("suno-", "").replace(".wav", "")
        ref_path = os.path.join(ROOT, "sources", f"distrokid-{song}.wav")
        if not os.path.exists(ref_path):
            continue
        x, sr = load_audio(p)
        ours = master(loudest(x, sr), sr, DERIVED)
        theirs, sr2 = load_audio(ref_path)
        # The service master is the whole song; take the same passage by
        # matching where the Suno excerpt sits, then trim both to length.
        theirs = loudest(theirs, sr2)
        n = min(len(ours), len(theirs))
        m = abtest.build(
            f"service-{song}", f"Ours vs the service · {song.replace('-', ' ')}",
            # The service master is a separate file, so its rate travels with
            # it. build() refuses a set whose arms disagree: written at the
            # wrong rate an arm plays at the wrong speed, and pitch would be
            # the loudest difference in a comparison that is about tone.
            [("Shimmer, current chain", ours[:n], sr),
             ("the automated service's master", theirs[:n], sr2)],
            sr,
            note="Our current chain against an automated mastering service's master of the same song, matched for loudness, so neither can win on volume alone. This is the comparison the whole investigation was founded on, and it has never been made fairly until now.")
        made.append(m["id"])
        print(f"  {m['id']:<44} matched to {m['matched_lufs']:.1f} LUFS")
    use(DERIVED)
    return made


def era_sets():
    """All three targets this tool has ever aimed at, on one song.

    The 1950-2010 average made the masters that were called dull. The
    service curve replaced it and was retracted. The derived one ships now.
    Three arms, so the question is not "is this better than the last one"
    but "which of these is right".
    """
    made = []
    for p in sorted(glob.glob(os.path.join(ROOT, "sources", "suno-*.wav")))[:4]:
        song = os.path.basename(p).replace("suno-", "").replace(".wav", "")
        x, sr = load_audio(p)
        ref = loudest(x, sr)
        m = abtest.build(
            f"era-{song}", f"Three targets · {song.replace('-', ' ')}",
            [("1950-2010 average (what sounded dull)", master(ref, sr, PESTANA)),
             ("service curve (retracted)", master(ref, sr, RETRACTED)),
             ("derived (shipping now)", master(ref, sr, DERIVED))],
            sr,
            note='Every tone target this tool has aimed at, on one song, with everything else held identical. They are in random order.')
        made.append(m["id"])
        print(f"  {m['id']:<44} matched to {m['matched_lufs']:.1f} LUFS")
    use(DERIVED)
    return made


def chain_sets():
    """Does the tool help at all? Raw render against the finished master."""
    made = []
    for p in sorted(glob.glob(os.path.join(ROOT, "sources", "suno-*.wav")))[:4]:
        song = os.path.basename(p).replace("suno-", "").replace(".wav", "")
        x, sr = load_audio(p)
        ref = loudest(x, sr)
        m = abtest.build(
            f"chain-{song}", f"Does it help · {song.replace('-', ' ')}",
            [("untouched Suno render", ref),
             ("Shimmer, full chain", master(ref, sr, DERIVED))],
            sr,
            note=("The raw render against the finished master. If the "
                  "untouched one wins, that is a real result and the most "
                  "useful thing on this bench."),
            residual_of=("untouched Suno render", "Shimmer, full chain"),
            residual_kind="removed")
        made.append(m["id"])
        print(f"  {m['id']:<44} matched to {m['matched_lufs']:.1f} LUFS")
    use(DERIVED)
    return made


GROUPS = {"service": ("Ours vs the service (the founding question):", service_sets),
          "era": ("All three tone targets:", era_sets),
          "chain": ("Untouched render vs the full chain:", chain_sets),
          "tone": ("Tone target, retracted vs derived:", tone_sets),
          "clean": ("Cleaning only, untouched vs cleaned:", clean_sets)}

if __name__ == "__main__":
    what = sys.argv[1:] or ["all"]
    os.makedirs(abtest.BENCH, exist_ok=True)
    names = list(GROUPS) if what == ["all"] or "all" in what else what
    for name in names:
        if name not in GROUPS:
            print(f"  (no such group: {name}; have {', '.join(GROUPS)})")
            continue
        head, fn = GROUPS[name]
        print(head)
        fn()
    print(f"\nOpen http://localhost:7860/static/ab/")
