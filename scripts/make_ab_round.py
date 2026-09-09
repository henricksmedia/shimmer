"""
make_ab_round.py — Turn a set of rendered masters into a blind listening round.

Takes a folder of `<song>-<variant>.wav` renders and produces a level-matched,
blind-labelled round with an answer key. Separate from make_listening_test.py,
which builds residual tests; this one compares finished masters, which is the
question tone changes have to answer.

Why level matching is not optional here: the whole investigation started
because a reference master sounded better in an unlevel-matched comparison,
and it was 2.8 LU louder. Any A/B that skips this measures loudness.

Usage:  python scripts/make_ab_round.py <render-dir> [--out DIR]
"""
from __future__ import annotations

import json
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer.audio_io import load_audio, save_audio          # noqa: E402
from shimmer.mastering import apply_gain_to_lufs             # noqa: E402

TEST_LUFS = -18.0

# What each variant is, in words the listener can use without being told which
# is which. Order here is the order they are described in the key.
MEANING = {
    "source": "the untouched AI render (hidden anchor)",
    "old": "Shimmer as it shipped — 1950-2010 tone target",
    "new": "Shimmer with the measured tone target",
    "reference": "the commercial reference master",
}


def at_lufs(x, sr, target=TEST_LUFS):
    y, _ = apply_gain_to_lufs(x, sr, target)
    peak = float(np.max(np.abs(y))) or 1.0
    return y * (0.99 / peak) if peak > 0.99 else y


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 1
    src_dir = argv[0]
    out = (argv[argv.index("--out") + 1] if "--out" in argv
           else os.path.join(src_dir, "blind"))
    os.makedirs(out, exist_ok=True)
    rng = random.Random(20260908)

    songs = {}
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith(".wav") or "-" not in fn:
            continue
        stem, _, variant = fn[:-4].rpartition("-")
        if variant in MEANING:
            songs.setdefault(stem, {})[variant] = os.path.join(src_dir, fn)

    key = {
        "how_to_listen": [
            "For each song, play its letters back to back. They are matched to",
            "the same loudness, so none can win by being louder.",
            "Ask one question: which sounds most open and finished?",
            "Rank them, write it down, THEN read 'songs' below.",
            "One letter per song is the untouched render. If it wins, say so —",
            "that is a real result, not a mistake.",
        ],
        "songs": {},
    }

    for stem, variants in sorted(songs.items()):
        letters = list("ABCD")[:len(variants)]
        rng.shuffle(letters)
        rows = []
        for letter, (variant, path) in zip(letters, sorted(variants.items())):
            x, sr = load_audio(path)
            save_audio(os.path.join(out, f"{stem}-{letter}.wav"),
                       at_lufs(x, sr), sr, subtype="PCM_24")
            rows.append({"letter": letter, "what_it_is": MEANING[variant],
                         "variant": variant})
        key["songs"][stem] = sorted(rows, key=lambda r: r["letter"])
        print(f"  {stem[:34]:34s} {len(rows)} letters")   # never print which is which

    with open(os.path.join(out, "ANSWER-KEY.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(key, f, indent=1)
    # A blank scores file for the listener to fill in, beside the key. The
    # listener writes here first, then opens the key.
    scores = {
        "judged_by": "", "date": "",
        "how": ("For each song, fill in the letter you preferred and what you heard. "
                "Save, then open ANSWER-KEY.json."),
        "rankings": {stem: {"preferred": None, "note": ""} for stem in songs},
    }
    scores_path = os.path.join(out, "SCORES.json")
    if not os.path.exists(scores_path):
        with open(scores_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(scores, f, indent=1)
    print(f"\n{len(songs)} songs written to {out}")
    print("Listen first, write your answers in SCORES.json, then open ANSWER-KEY.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
