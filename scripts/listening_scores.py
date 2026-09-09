"""
listening_scores.py — Record a blind listening round, then read it.

Two modes:

    python scripts/listening_scores.py --template <round-dir>
        Writes SCORES.json next to the audio, pre-filled with the song names
        and letters and nothing else. It does not reveal which letter is
        which, so filling it in cannot spoil the blind.

    python scripts/listening_scores.py --score <round-dir>
        Reads SCORES.json against ANSWER-KEY.json and reports what the
        listener actually preferred, per variant and overall.

Why ranking rather than free text: a ranking can be counted. "Sounds better"
cannot, and the whole reason for this round is a measurement that says the
gap closed 26% and no way to tell whether 26% is audible.

Why `heard_a_difference` is a separate field: a ranking always produces an
order, even from guessing. Without it, a coin-flip round is indistinguishable
from a real preference — which would be the worst possible input to a decision
about shipping.
"""
from __future__ import annotations

import collections
import json
import os
import sys


def template(round_dir: str) -> int:
    key_path = os.path.join(round_dir, "ANSWER-KEY.json")
    with open(key_path, encoding="utf-8") as f:
        key = json.load(f)

    out = {
        "_how_to_fill_this_in": [
            "For each song: play its letters, then put them in best_to_worst",
            "order — best first. Use every letter once.",
            "",
            "heard_a_difference: true if they actually sounded different.",
            "  false if you were guessing. Saying false is useful, not a",
            "  failure — it is the answer to 'is this change audible'.",
            "",
            "scores: OPTIONAL 0-100 per letter (100 = best you heard).",
            "  Only fill these in if the gaps felt worth recording. Ranking",
            "  is what gets counted; scores just add magnitude.",
            "",
            "notes: OPTIONAL, anything you noticed. Free text.",
            "",
            "Skip a song by leaving best_to_worst empty.",
        ],
        "songs": {},
    }
    for song, rows in sorted(key["songs"].items()):
        letters = [r["letter"] for r in rows]
        out["songs"][song] = {
            "best_to_worst": [],
            "heard_a_difference": None,
            "scores": {ltr: None for ltr in letters},
            "notes": "",
        }

    dst = os.path.join(round_dir, "SCORES.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"wrote {dst}")
    print(f"{len(out['songs'])} songs, letters "
          f"{'/'.join(sorted(letters))} each")
    return 0


def score(round_dir: str) -> int:
    with open(os.path.join(round_dir, "ANSWER-KEY.json"), encoding="utf-8") as f:
        key = json.load(f)
    path = os.path.join(round_dir, "SCORES.json")
    if not os.path.exists(path):
        print("No SCORES.json yet — run --template first, then fill it in.")
        return 1
    with open(path, encoding="utf-8") as f:
        got = json.load(f)

    letter_to_variant = {
        song: {r["letter"]: r["variant"] for r in rows}
        for song, rows in key["songs"].items()
    }

    ranks = collections.defaultdict(list)     # variant -> [rank position]
    wins = collections.Counter()
    judged = heard = 0
    print(f"{'song':30s} {'1st':>12} {'2nd':>12} {'3rd':>12} {'4th':>12}  diff?")
    for song, row in sorted(got.get("songs", {}).items()):
        order = row.get("best_to_worst") or []
        if not order:
            continue
        m = letter_to_variant.get(song, {})
        variants = [m.get(l, "?") for l in order]
        judged += 1
        if row.get("heard_a_difference"):
            heard += 1
        for i, v in enumerate(variants):
            ranks[v].append(i + 1)
        wins[variants[0]] += 1
        cells = "".join(f"{v[:12]:>13}" for v in variants)
        print(f"{song[:30]:30s}{cells}  "
              f"{'yes' if row.get('heard_a_difference') else 'NO'}")

    if not judged:
        print("\nNothing scored yet.")
        return 1

    print(f"\n=== {judged} songs judged, difference heard on {heard} ===")
    print(f"{'variant':38s} {'mean rank':>10} {'firsts':>8}")
    for v, rs in sorted(ranks.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        print(f"{v[:38]:38s} {sum(rs) / len(rs):10.2f} {wins[v]:8d}")

    new_r = ranks.get("new", [])
    old_r = ranks.get("old", [])
    if new_r and old_r:
        better = sum(1 for a, b in zip(new_r, old_r) if a < b)
        print(f"\nnew tone target beat the old one on {better} of "
              f"{len(new_r)} songs")
        if heard < judged / 2:
            print("CAUTION: a difference was heard on fewer than half the "
                  "songs, so this ordering may be mostly noise.")
    return 0


def main(argv) -> int:
    if "--template" in argv:
        return template(argv[argv.index("--template") + 1])
    if "--score" in argv:
        return score(argv[argv.index("--score") + 1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
