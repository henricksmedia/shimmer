"""listening_report.py — turn the bench's raw verdicts into a findings record.

The bench itself is a working instrument: regenerated audio plus the answer
keys that blind it, all of it gitignored. This script reads that instrument
and writes the part that has to outlive it — what was preferred, under what
conditions, with what limits — to docs/listening/.

Two rules shape the output, and both matter.

  * It records the *true label* that won, never the letter that carried it.
    The letter is the blinding. Publishing letters would make the sets on
    disk unusable; publishing what won does not, because letters are
    randomised afresh every time a set is built.

  * It never silently drops a round. The bench holds one synthetic probe
    verdict written while the interface was being reviewed. It is marked
    excluded, with its reason, rather than filtered out — a record that
    quietly discards rows cannot be checked.

    python scripts/listening_report.py            # write the record
    python scripts/listening_report.py --print    # summary to the terminal
"""
from __future__ import annotations

import glob
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCH = os.path.join(ROOT, "listening-test", "ab")
OUT_DIR = os.path.join(ROOT, "docs", "listening")

# What each group of sets asks. Written here rather than inferred, because the
# question asked shapes the answer and has to travel with the numbers.
QUESTIONS = {
    "service": "Which sounds most open and finished? (our chain vs an automated service's master)",
    "r8": "Which sounds most open and finished? (four arms: our chain now, the service, our chain before, untouched)",
    "chain": "Which sounds most open and finished? (the full chain vs the untouched render)",
    "clean": "Which sounds better? (untouched vs cleaned, judged on the loudest 30 s)",
    "quiet": "Which still has the shimmer? (untouched vs cleaned, judged on the most exposed passage)",
    "learned": "Which still has the shimmer? (untouched vs the learned hash remover, most exposed passage)",
    "tone": "Which sounds most open and finished? (two tone targets, everything else identical)",
    "era": "Which of these is right? (three tone targets, everything else identical)",
    "level": "Which is loudest? (the same master at the three Loudness targets, each at its real level, not level-matched)",
    "loud": "Which sounds cleanest? (the same master at the three Loudness targets, level-matched)",
}

EXCLUDE_MARK = "ignore this verdict"


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def collect():
    rows = []
    for d in sorted(glob.glob(os.path.join(BENCH, "*"))):
        sid = os.path.basename(d)
        scores = _read(os.path.join(d, "SCORES.json"))
        key = _read(os.path.join(d, "ANSWER-KEY.json"))
        man = _read(os.path.join(d, "manifest.json"))
        if not scores or not key:
            continue
        group = sid.split("-", 1)[0]
        song = sid.split("-", 1)[1] if "-" in sid else ""
        answer = key.get("answer", {})
        for r in scores.get("rounds", []):
            note = (r.get("note") or "").strip()
            letter = r.get("preferred_letter")
            # Decode against this set's own key rather than trusting the
            # label stored alongside the letter, so a mismatch is visible.
            decoded = answer.get(letter) if letter else None
            stored = r.get("preferred_label") or None
            tie = letter == "tie" or (letter and decoded is None and not stored)
            abx = r.get("abx") or {}
            rows.append({
                "set": sid,
                "group": group,
                "song": song,
                "at": r.get("at"),
                "excluded": EXCLUDE_MARK in note.lower(),
                "exclusion_reason": note if EXCLUDE_MARK in note.lower() else None,
                "preferred": None if tie else (decoded or stored),
                "tie": bool(tie),
                "decode_agrees": None if tie else (decoded == stored),
                "blind": r.get("revealed_first") is False,
                "seconds_listened": r.get("seconds_listened"),
                "switches": r.get("switches"),
                "abx_trials": abx.get("trials"),
                "abx_correct": abx.get("correct"),
                "abx_p": abx.get("p_value"),
                "listener_note": note if EXCLUDE_MARK not in note.lower() and note else None,
                "arms": len(key.get("arms", [])) or None,
                "seconds_of_audio": (man or {}).get("seconds"),
                "matched_lufs": (man or {}).get("matched_lufs"),
                # Loudness checks are built unmatched on purpose; older sets
                # predate the flag and were all matched.
                "level_matched": (man or {}).get("level_matched", True),
            })
    rows.sort(key=lambda r: (r["group"], r["song"], r["at"] or ""))
    return rows


def summarise(rows):
    out = {}
    for g in sorted({r["group"] for r in rows}):
        rs = [r for r in rows if r["group"] == g and not r["excluded"]]
        tally = Counter(r["preferred"] or "tie / no preference" for r in rs)
        secs = [r["seconds_listened"] for r in rs if r["seconds_listened"] is not None]
        out[g] = {
            "question_asked": QUESTIONS.get(g),
            "rounds": len(rs),
            "excluded_rounds": len([r for r in rows if r["group"] == g and r["excluded"]]),
            "songs": len({r["song"] for r in rs}),
            "arms_per_set": sorted({r["arms"] for r in rs if r["arms"]}),
            "preferred": dict(tally.most_common()),
            "median_seconds_listened": round(sorted(secs)[len(secs) // 2], 1) if secs else None,
            "rounds_with_audibility_test": len([r for r in rs if r["abx_trials"]]),
        }
    return out


def _opt(flag, default):
    """A `--flag value` from the command line, or the default."""
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv[:-1] else default


def main():
    rows = collect()
    if not rows:
        print("no verdicts found in listening-test/ab — nothing to record")
        return 1
    # Each session gets its own record. The defaults reproduce the 2026-09-09
    # record exactly; a later session passes its own name, file and playback,
    # so running this never overwrites an earlier session's findings.
    session = _opt("--session", "2026-09-09 bench round")
    out_name = os.path.basename(_opt("--out", "2026-09-09-bench-round.json"))
    playback = _opt("--playback", (
        "The computer speakers the listener uses for everyday music "
        "listening. Model and level not recorded."))
    excerpts = _opt("--excerpts", (
        "20-30 s. Most groups use the loudest passage; the quiet and "
        "learned groups use the passage where the removed material is "
        "least masked, chosen by the repair's own residual."))
    matched = [r for r in rows if r["level_matched"] is not False]
    unmatched = [r for r in rows if r["level_matched"] is False]
    if not unmatched:
        level_text = "All arms matched to the quietest arm's LUFS by shimmer/abtest.py."
    elif not matched:
        level_text = ("No arms matched: each plays at its own level, on purpose, "
                      "because the question asked is which is loudest.")
    else:
        level_text = (f"{len(matched)} rounds level-matched by shimmer/abtest.py; "
                      f"{len(unmatched)} rounds not matched, on purpose, because "
                      f"their question is which is loudest.")
    record = {
        "session": session,
        "written_by": "scripts/listening_report.py",
        "listener": {
            "n": 1,
            "who": "the author of the tool",
            "conflict_of_interest": (
                "The listener built the thing being judged and knows what each "
                "outcome would imply for the project. Blind to which arm was "
                "which; not blind to the hypothesis."),
            "playback": playback,
            "playback_is_a_consumer_system": True if "--playback" not in sys.argv else None,
        },
        "method": {
            "blinding": "Arm labels hidden; letters randomised per set.",
            "level_matching": level_text,
            "excerpts": excerpts,
            "response_recorded": "One preferred arm per round. No ranking.",
            "audibility_gate": "None. No group required an ABX pass before a preference counted.",
        },
        "counts": {
            "rounds_total": len(rows),
            "rounds_used": len([r for r in rows if not r["excluded"]]),
            "rounds_excluded": len([r for r in rows if r["excluded"]]),
            "sets": len({r["set"] for r in rows}),
            "blind_rounds": len([r for r in rows if r["blind"]]),
            "decode_mismatches": len([r for r in rows
                                      if r["decode_agrees"] is False]),
        },
        "summary": summarise(rows),
        "rounds": rows,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, out_name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(record, fh, indent=1)
        fh.write("\n")
    print(f"wrote {os.path.relpath(path, ROOT)}")
    if "--print" in sys.argv:
        c = record["counts"]
        print(f"\n{c['rounds_used']} rounds used, {c['rounds_excluded']} excluded, "
              f"{c['sets']} sets, {c['blind_rounds']} blind, "
              f"{c['decode_mismatches']} decode mismatches\n")
        for g, s in record["summary"].items():
            print(f"{g:9} {s['rounds']:2} rounds / {s['songs']} songs   "
                  f"median {s['median_seconds_listened']}s listened   "
                  f"audibility tests: {s['rounds_with_audibility_test']}")
            for label, n in s["preferred"].items():
                print(f"          {n:2}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
