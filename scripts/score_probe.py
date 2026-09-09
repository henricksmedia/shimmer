"""
score_probe.py — What does every preset do to every corpus file, and what
does the detector make of it?

This is the measurement behind checklist item 5 (the verified score). For
each file it takes the detector's own hot window, applies the static repair
the detector would apply, runs every artifact preset at 100 % through the
real cleaning pipeline, and records per (file, preset):

  prior              evidence that the preset's artifact is present
  artifact_db, collateral_db, net_db
                     where the removed energy sat (informational)
  missing, lin_dist, added
                     the BS.1387 hearing model's verdict, in sones
  score              detect.verified_score for that row

Three synthetic signals from tests/test_detect.py are appended (clean bed,
bed + hash, bed + tone) so the tests' material is measured on the same
footing as the corpus.

The corpus check runs first, non-strict: files it flags with an error are
skipped and named, so a bad pair cannot enter the statistics unnoticed.

Usage:
    python scripts/score_probe.py [--out docs/score-probe.json] [FILES...]

With no files it measures sources/*.wav and assets/reference/*.wav. The
summary at the end lists, per file, the best preset and its score, and
counts how many finished masters would get a recommendation — the number
that has to stay at zero for the references.
"""
from __future__ import annotations

import glob
import json
import os
import sys
from dataclasses import asdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from shimmer import detect as D                                   # noqa: E402
from shimmer.audio_io import load_audio                            # noqa: E402
from shimmer.repair import apply_static_repair, plan_from_lines    # noqa: E402

WINDOW_S = 5.0
FINISHED_PREFIXES = ("distrokid-", "reference-")


def flagged_files() -> set:
    """Names the corpus check reports as errors."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from corpus_check import require_valid_corpus
    rep = require_valid_corpus(strict=False)
    return {issue.where for issue in rep.errors}


def measure(name: str, x: np.ndarray, sr: int) -> list:
    scan = D.evidence_scan(x, sr)
    ev = scan.evidence
    pr = D.priors_from_evidence(ev)
    plan = plan_from_lines([asdict(t) for t in ev.tones], sr)
    w0 = int(scan.window_start_s * sr)
    clip = np.ascontiguousarray(x[w0:w0 + int(WINDOW_S * sr)])
    if plan.notches:
        clip, _ = apply_static_repair(clip, sr, plan)
        clip = np.ascontiguousarray(clip)
    masks = D.build_masks(clip, sr, D.eligible_tones(ev.tones))
    tone_w = D.tone_weight_for(ev.tones) if masks.tone_bins.size else 0.0
    rows = []
    for n in D.artifact_preset_names():
        y, removed = D._run_preset(clip, sr, n, 1.0)
        m = D.measure_removed(removed, sr, masks, y)
        rows.append({"file": name, "preset": n, "prior": round(pr[n], 3),
                     "tone_w": round(tone_w, 3),
                     "flicker_excess_db": round(ev.flicker_excess_db, 2),
                     **m.as_dict(),
                     "score": round(D.verified_score(m, pr[n], tone_w), 3)})
    return rows


def synthetic() -> list:
    import test_detect as T
    bed = T._music(6.0)
    return [("synth-clean", bed, T.SR),
            ("synth-hash", bed + T._hash(6.0, 0.09), T.SR),
            ("synth-tone", bed + T._tone(6.0, 11200.0, 0.02), T.SR)]


def summarise(rows: list) -> None:
    files = sorted({r["file"] for r in rows})
    fired = 0
    finished = 0
    print(f"\n{'file':40s} {'best preset':18s} {'score':>6s}")
    for f in files:
        best = max((r for r in rows if r["file"] == f), key=lambda r: r["score"])
        is_finished = f.startswith(FINISHED_PREFIXES)
        acts = best["score"] >= D.MIN_ACTIONABLE_SCORE
        finished += is_finished
        fired += is_finished and acts
        print(f"{f:40s} {best['preset']:18s} {best['score']:6.3f}"
              f"{'  <-- recommends on a finished master' if (is_finished and acts) else ''}")
    print(f"\nfinished masters that would get a recommendation: {fired}/{finished}")


def main(argv: list) -> int:
    out = os.path.join(ROOT, "docs", "score-probe.json")
    if "--out" in argv:
        i = argv.index("--out")
        out = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    files = argv or (sorted(glob.glob(os.path.join(ROOT, "sources", "*.wav")))
                     + sorted(glob.glob(os.path.join(ROOT, "assets", "reference", "*.wav"))))
    bad = flagged_files()
    rows = []
    for f in files:
        base = os.path.basename(f)
        if base in bad:
            print(f"skipping {base}: flagged by the corpus check")
            continue
        x, sr = load_audio(f)
        rows += measure(os.path.splitext(base)[0], x, sr)
        print(base, "done", flush=True)
        json.dump(rows, open(out, "w", newline="\n"), indent=1)
    for name, x, sr in synthetic():
        rows += measure(name, x, sr)
        print(name, "done", flush=True)
    json.dump(rows, open(out, "w", newline="\n"), indent=1)
    summarise(rows)
    print(f"\nwrote {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
