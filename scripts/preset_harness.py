"""
preset_harness.py — Does each preset fix what it targets, and what does it cost?

TWO questions, and the first one matters more.

  EFFICACY   Did the artifact go away? A repair tool that leaves the shimmer
             in has failed, however gently it did so. Measured from the
             detector's own evidence before and after: if a track reads
             +2.5 dB of excess flicker going in and +0.3 coming out, the hash
             was removed. This is the tool's actual purpose.

  COST       What did it take with it? The BS.1387 damage model
             (shimmer/perceptual.py), in sones of audible difference.

Everything built before this measured COST alone. That is backwards for a
repair tool, and it made the artifact budget dangerous on its own: a budget
that limits cleaning without checking what survives can hold a preset back
until the artifact remains, and nothing would notice.

A preset is only good if BOTH hold: the artifact drops, and the cost is small.
A preset that scores zero cost by doing nothing is not surgical, it is inert —
and the cost-only view could not tell those apart.

Usage:
    python scripts/preset_harness.py [--presets a,b] [--limit N] [--out FILE]
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer import perceptual as P                         # noqa: E402
from shimmer.audio_io import load_audio                     # noqa: E402
from shimmer.detect import (artifact_preset_names, evidence_scan,  # noqa: E402
                            priors_from_evidence)
from shimmer.pipeline import clean_and_master               # noqa: E402
from shimmer.presets import PRESETS, label_for              # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCERPT_S = 20.0

# Efficacy is judged by each preset's OWN prior, not by a field picked by hand.
#
# `detect.priors_from_evidence` already answers "is this artifact present?" for
# every preset — that is what the detector uses to decide whether to recommend
# one. Running it before and after asks the preset the tool's own question: the
# thing you said was wrong, is it less wrong now?
#
# The first version of this script hand-mapped each preset to one evidence
# field. That covered 11 of 19, and the eight that fell through were scored
# against flicker excess — which is not what Laser Whistle or Cymbal Sheen
# target, so they were reported INERT when the truth was "measured against the
# wrong thing". Using the prior removes both the coverage gap and the chance
# of choosing a flattering metric.
EVIDENCE = ("flicker_excess_db", "flat_3_8", "flat_4_12", "flat_8_18",
            "presence_db", "ring_4_10", "comb", "sib_burst", "tail_contrast",
            "period_excess", "echo_corr", "umid_db", "top_tilt_db")

# Below this the artifact is not really present, so "fixed 0%" says nothing
# about the preset — it says the material had nothing for it to work on.
PRIOR_PRESENT = 0.25


def excerpt(x, sr):
    n = int(EXCERPT_S * sr)
    if x.shape[0] <= n:
        return x
    s = x.shape[0] // 3
    return np.ascontiguousarray(x[s:s + n])


def evidence_of(x, sr):
    """Both the raw evidence and every preset's prior, from one scan."""
    ev = evidence_scan(x, sr).evidence
    return ({k: float(getattr(ev, k)) for k in EVIDENCE},
            priors_from_evidence(ev))


def main(argv) -> int:
    names = (argv[argv.index("--presets") + 1].split(",")
             if "--presets" in argv else artifact_preset_names())
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else 3
    out_path = (argv[argv.index("--out") + 1] if "--out" in argv
                else os.path.join(ROOT, "docs", "preset-harness.json"))

    srcs = sorted(glob.glob(os.path.join(ROOT, "sources", "suno-*.wav")))[:limit]
    print(f"{len(names)} presets x {len(srcs)} sources\n")

    rows = []
    for path in srcs:
        x, sr = load_audio(path)
        clip = excerpt(x, sr)
        before, prior_before = evidence_of(clip, sr)
        song = os.path.basename(path)[5:-4]
        strong = [k for k, v in sorted(prior_before.items(),
                                       key=lambda kv: -kv[1])[:3]]
        print(f"--- {song}   strongest signals: "
              + ", ".join(f"{k} {prior_before[k]:.2f}" for k in strong))
        print(f"{'preset':24s} {'prior before':>15} {'after':>8} "
              f"{'fixed':>7} {'cost':>7}")
        for name in names:
            try:
                y, _rm, _rep = clean_and_master(
                    clip, sr, PRESETS[name](), master_params=None,
                    eq_params=None, repair=None)
                y = np.asarray(y)[:clip.shape[0]]
                after, prior_after = evidence_of(y, sr)
                dmg = P.measure_damage(clip, y, sr)
            except Exception as e:  # noqa: BLE001
                print(f"{name:24s} ERROR {e}")
                continue
            # The preset's own prior: does the tool still think this artifact
            # is here? Guarded so a source that never had it cannot make a
            # preset look inert.
            b = float(prior_before.get(name, 0.0))
            a = float(prior_after.get(name, 0.0))
            key = "own prior"
            fixed = ((b - a) / b) if b >= PRIOR_PRESENT else float("nan")
            rows.append({"song": song, "preset": name, "primary": key,
                         "before": round(b, 3), "after": round(a, 3),
                         "fixed_frac": None if np.isnan(fixed) else round(fixed, 3),
                         "cost_missing": round(dmg.missing, 4),
                         "cost_lin_dist": round(dmg.lin_dist, 3),
                         "evidence_before": {k: round(v, 3) for k, v in before.items()},
                         "evidence_after": {k: round(v, 3) for k, v in after.items()}})
            fs = "   n/a" if np.isnan(fixed) else f"{100 * fixed:6.0f}%"
            print(f"{label_for(name)[:24]:24s} {b:15.2f} {a:8.2f} {fs:>7} "
                  f"{dmg.missing:7.3f}")
        print()

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"excerpt_s": EXCERPT_S, "rows": rows}, f, indent=1)

    print("=== Efficacy vs cost, averaged over sources where the artifact "
          "was present ===")
    print(f"{'preset':26s} {'fixed':>8} {'cost':>8}  verdict")
    by = {}
    for r in rows:
        if r["fixed_frac"] is None:
            continue
        by.setdefault(r["preset"], []).append((r["fixed_frac"], r["cost_missing"]))
    for name, vals in sorted(by.items(), key=lambda kv: -np.mean([v[0] for v in kv[1]])):
        f_ = float(np.mean([v[0] for v in vals]))
        c_ = float(np.mean([v[1] for v in vals]))
        if f_ < 0.15:
            verdict = "does not reduce its own signal"
        elif c_ > 0.10:
            verdict = "COSTLY - fixes it, but takes a lot with it"
        else:
            verdict = "good"
        print(f"{label_for(name)[:26]:26s} {100 * f_:7.0f}% {c_:8.3f}  {verdict}")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
