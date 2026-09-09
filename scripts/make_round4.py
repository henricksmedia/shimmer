"""
make_round4.py — Listening round 4: what the old scorer applied versus what
the new one applies, per song, cleaning only, level-matched and blind.

The scorer change (checklist items 5 and 10) changes *which preset the
automatic flow applies*, not the sound of any preset. So the round compares,
for each corpus song:

  source   the untouched file (hidden anchor)
  old      the preset the purity-based scorer chose for this song, at the
           strength it chose, run through the cleaning chain (notch plan
           included) — what Shimmer would have applied before 2026-09-08
  new      what the net-benefit scorer applies: on six of the eight files
           nothing beyond the notch plan and the tone killer (Generic); on
           the two `the-little-things` files Suno Hash at 100 %

No mastering and no EQ, so the tone target (retracted the same day, item 12)
plays no part. Loudest 30 s of each file. Picks are read from the detector
result JSON the two scorers produced on the same files (scratch/baseline and
scratch/after2 of the session that built this; the numbers are in the
checklist), so the round reproduces those decisions exactly.

Usage: python scripts/make_round4.py <baseline-json-dir> <after-json-dir> [--out listening-test/round-4]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from shimmer.audio_io import load_audio, save_audio     # noqa: E402
from shimmer.params import apply_preset_strength         # noqa: E402
from shimmer.pipeline import clean_and_master            # noqa: E402
from shimmer.presets import get_preset, label_for        # noqa: E402
from shimmer.repair import plan_from_lines               # noqa: E402
from make_listening_test import loudest_excerpt          # noqa: E402
import make_ab_round                                      # noqa: E402

EXCERPT_S = 30.0
FILES = {
    "reference-hey": "assets/reference/reference-hey.wav",
    "reference-leave-the-world-behind": "assets/reference/reference-leave-the-world-behind.wav",
    "suno-algorithms-lure": "sources/suno-algorithms-lure.wav",
    "suno-alive-again": "sources/suno-alive-again.wav",
    "suno-couldve-been-stories": "sources/suno-couldve-been-stories.wav",
    "suno-falling-for-you": "sources/suno-falling-for-you.wav",
    "suno-the-little-things": "sources/suno-the-little-things.wav",
    "distrokid-the-little-things": "sources/distrokid-the-little-things.wav",
}


def pick(json_dir, name):
    p = os.path.join(json_dir, name + ".json")
    if not os.path.exists(p):
        return None
    r = json.load(open(p, encoding="utf-8"))
    return {"preset": r["preset"], "strength": float(r.get("strength", 1.0)),
            "tones": r["evidence"]["tones"]}


def render(x, sr, preset, strength, tones):
    p = get_preset(preset)
    if abs(strength - 1.0) > 1e-6:
        apply_preset_strength(p, strength)
    plan = plan_from_lines(tones, sr)
    y, _, _ = clean_and_master(x, sr, p, master_params=None, eq_params=None,
                               repair=plan if plan.notches else None)
    return np.asarray(y, dtype=np.float32)[:x.shape[0]]


def main(argv):
    base_dir, after_dir = argv[0], argv[1]
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "listening-test", "round-4")
    renders = os.path.join(out, "renders")
    os.makedirs(renders, exist_ok=True)
    picks = {}
    for name, rel in FILES.items():
        old, new = pick(base_dir, name), pick(after_dir, name)
        if old is None and new is None:
            print(f"{name}: no detector result, skipped")
            continue
        x, sr = load_audio(os.path.join(ROOT, rel))
        clip = np.ascontiguousarray(loudest_excerpt(x, sr, EXCERPT_S).astype(np.float32))
        tones = (new or old)["tones"]
        save_audio(os.path.join(renders, f"{name}-source.wav"), clip, sr, subtype="PCM_24")
        row = {}
        if old is not None:
            save_audio(os.path.join(renders, f"{name}-old.wav"),
                       render(clip, sr, old["preset"], old["strength"], tones), sr, subtype="PCM_24")
            row["old"] = f"{label_for(old['preset'])} at {old['strength']:.0%}"
        if new is not None:
            save_audio(os.path.join(renders, f"{name}-new.wav"),
                       render(clip, sr, new["preset"], new["strength"], tones), sr, subtype="PCM_24")
            row["new"] = f"{label_for(new['preset'])} at {new['strength']:.0%}"
        row["notches"] = len(plan_from_lines(tones, sr).notches)
        picks[name] = row
        print(f"{name:36s} old={row.get('old', '-'):32s} new={row.get('new', '-')}", flush=True)

    make_ab_round.MEANING = {
        "source": "the untouched file (hidden anchor)",
        "old": "what the purity-based scorer applied to this song (cleaning only)",
        "new": "what the net-benefit scorer applies to this song (cleaning only)",
    }
    make_ab_round.main([renders, "--out", os.path.join(out, "blind")])
    key_path = os.path.join(out, "blind", "ANSWER-KEY.json")
    key = json.load(open(key_path, encoding="utf-8"))
    key["picks"] = picks
    key["note"] = ("No mastering, no EQ: the tone target plays no part. Loudest 30 s. "
                   "The question is whether the old pick took something audible from "
                   "the music that the new pick leaves in, and whether anything the old "
                   "pick removed was worth removing.")
    with open(key_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(key, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
