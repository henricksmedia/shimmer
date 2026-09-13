"""
make_fix_round.py — Build the blind listening sets for one card's fix
(docs/STEP6-FIXES.md, decision rule 4).

For each song: the passage where the fix acts most, rendered three ways by
the new engine's render(), exactly as the Master tab exports it (no
mastering, no EQ, so only the fix differs):

  original      nothing on
  amount-50     the card at Amount 50 % (the card's default)
  amount-100    the card at Amount 100 % (the slider's top)

The bench level-matches every arm and shuffles the letters
(shimmer/abtest.py); the residual is what Amount 100 % took out, so the
author can hear exactly what the fix removes. Judge at
http://localhost:<port>/static/ab/ with the rebuild running.

Usage:
    python scripts/make_fix_round.py sibilance "path/to/song.wav" [more.wav ...]
        [--seconds 20]
"""
from __future__ import annotations

import os
import re
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimmer import abtest                       # noqa: E402
from shimmer import core                         # noqa: E402

QUESTIONS = {
    "sibilance": "Which has the least harsh \"s\", \"t\" and \"ch\", without the song "
                 "sounding duller?",
    "harshness": "Which has the least piercing upper mids, without the song sounding "
                 "thinner?",
    "mud": "Which sounds clearest in the low mids, without the song sounding thinner?",
    "clicks": "Which has the fewest clicks and crackles, without softer drums?",
}


def _slug(path: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", os.path.splitext(os.path.basename(path))[0]).strip("-")
    return s[:40].lower() or "song"


def _busiest(source: core.Source, card: str, seconds: float) -> float:
    """Start of the `seconds` where the fix at full Amount changes the most."""
    s = core.Settings(fixes={card: 1.0}, auto=False, mastering=False, preserve_volume=False)
    r = core.render(source, s, with_removed=True)
    e = np.sum(np.asarray(r.removed, dtype=np.float64) ** 2, axis=1)
    w = int(seconds * r.sr)
    if e.size <= w:
        return 0.0
    c = np.concatenate([[0.0], np.cumsum(e)])
    starts = np.arange(0, e.size - w, int(0.5 * r.sr))
    best = starts[int(np.argmax(c[starts + w] - c[starts]))]
    return float(best) / r.sr


def build_set(card: str, path: str, seconds: float = 20.0) -> dict:
    source = core.Source.load(path)
    t0 = _busiest(source, card, seconds)
    window = (t0, min(source.duration_s, t0 + seconds))
    arms = []
    for label, amount in (("original", 0.0), ("amount-50", 0.5), ("amount-100", 1.0)):
        fixes = {card: amount} if amount > 0 else {}
        s = core.Settings(fixes=fixes, auto=False, mastering=False, preserve_volume=False)
        r = core.render(source, s, window=window)
        arms.append((label, r.audio, r.sr))
    set_id = f"fix-{card}-{_slug(path)}"
    return abtest.build(
        set_id, f"{core.catalog.card(card).label}: {os.path.basename(path)}", arms, arms[0][2],
        note=(f"{window[0]:.1f}-{window[1]:.1f} s, where the fix acts most. "
              "Nothing else on. The residual is what Amount 100 % took out."),
        residual_of=("original", "amount-100"), residual_kind="removed", seed=7,
        question=QUESTIONS.get(card, ""), tie_label="No difference")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    seconds = 20.0
    if "--seconds" in argv:
        i = argv.index("--seconds")
        seconds = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    card, paths = argv[0], argv[1:]
    for p in paths:
        m = build_set(card, p, seconds)
        print(f"built {m.get('id', '?')}: {m.get('title', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
