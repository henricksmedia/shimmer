"""
efficacy_report.py — Read docs/efficacy-harness.json and answer the
questions checklist items 3 and 6 ask.

  1. Per preset: does it remove the artifact it is aimed at (ground-truth
     efficacy), and what does it cost — both axes, so inert and surgical
     can be told apart.
  2. Does the detector's evidence track the truth? For every targeted row
     the old harness would have scored "fixed" as the drop in the preset's
     own prior; here that number is computed alongside the ground-truth
     efficacy, and the two are correlated. If the prior does not track the
     truth, the old harness's verdicts were noise.
  3. Which presets respond to the artifact at all: cost on the render vs
     cost on the clean host (the control).

Usage: python scripts/efficacy_report.py [docs/efficacy-harness.json]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimmer import artifacts as A                      # noqa: E402
from shimmer.detect import Evidence, priors_from_evidence  # noqa: E402


def prior_of(preset: str, ev: dict) -> float:
    """The detector's prior for `preset` from a recorded evidence dict.
    Fields the harness did not record are filled with neutral values."""
    from shimmer.detect import Tone

    def tone(k):
        v = ev.get(k)
        return Tone(v["hz"], v["excess_db"], v["duty"]) if v else Tone(0.0, 0.0, 0.0)
    t = Tone(0.0, 0.0, 0.0)
    full = Evidence(tones=[], tone_4_8=t, tone_8_12=tone("tone_8_12"),
                    tone_9_15=tone("tone_9_15"), tone_12_20=tone("tone_12_20"),
                    top_tilt_db=ev.get("top_tilt_db", 0.0),
                    presence_db=ev.get("presence_db", 0.0),
                    upper_db=0.0, umid_db=ev.get("umid_db", 0.0),
                    mud_db=0.0, dull_db=0.0,
                    flicker_hi_db=0.0, flicker_body_db=0.0,
                    flicker_excess_db=ev.get("flicker_excess_db", 0.0),
                    comb=ev.get("comb", 0.0), sib_burst=ev.get("sib_burst", 0.0),
                    period_hi=0.0, period_body=0.0,
                    period_excess=ev.get("period_excess", 0.0),
                    tail_contrast=ev.get("tail_contrast", 0.0),
                    ring_4_10=ev.get("ring_4_10", 0.0),
                    echo_corr=ev.get("echo_corr", 0.0),
                    flat_3_8=ev.get("flat_3_8", 0.0), flat_4_12=ev.get("flat_4_12", 0.0),
                    flat_8_18=ev.get("flat_8_18", 0.0))
    return float(priors_from_evidence(full).get(preset, 0.0))


def main(argv):
    path = argv[0] if argv else os.path.join(ROOT, "docs", "efficacy-harness.json")
    d = json.load(open(path, encoding="utf-8"))
    rows = [r for r in d["rows"] if r["strength"] == 1.0]
    levels = sorted({r["level"] for r in rows})
    arts = sorted({r["artifact"] for r in rows})
    presets = []
    for r in rows:
        if r["preset"] not in presets:
            presets.append(r["preset"])
    top = max(levels)

    print(f"# 1. Efficacy on the artifact each preset is aimed at, at {top} sones "
          f"injected (mean over hosts), with cost on the render and on the clean host")
    print(f"{'preset':18s} {'aimed at':28s} {'efficacy':>9s} {'cost':>7s} {'ctrl':>7s} {'tilt':>7s}  verdict")
    for pn in presets:
        aimed = [an for an in arts if pn in A.TARGETS.get(an, ()) or
                 (pn == "static_repair" and an in ("line", "whistle", "comb"))]
        if not aimed:
            note = "not covered" if pn in A.NOT_COVERED else "no model aimed at it"
            print(f"{pn:18s} {'-':28s} {'-':>9s} {'-':>7s} {'-':>7s} {'-':>7s}  {note}")
            continue
        rs = [r for r in rows if r["preset"] == pn and r["artifact"] in aimed and r["level"] == top]
        eff = float(np.mean([r["efficacy"] for r in rs]))
        cost = float(np.mean([r["cost_missing"] for r in rs]))
        ctrl = float(np.mean([r["control"]["missing"] for r in rs]))
        tilt = float(np.mean([r["cost_lin_dist"] for r in rs]))
        if eff < 0.15:
            verdict = "INERT on its target"
        elif cost > 0.10:
            verdict = "works, COSTLY"
        else:
            verdict = "works"
        print(f"{pn:18s} {','.join(aimed):28s} {100 * eff:8.0f}% {cost:7.3f} {ctrl:7.3f} {tilt:7.2f}  {verdict}")

    print(f"\n# 2. Does efficacy hold as the artifact gets fainter? Aimed presets, "
          f"mean efficacy per injected level")
    print(f"{'preset':18s}" + "".join(f"{L:>9}" for L in levels))
    for pn in presets:
        cells = []
        for L in levels:
            rs = [r for r in rows if r["preset"] == pn and r["targeted"] and r["level"] == L]
            cells.append(f"{100 * float(np.mean([r['efficacy'] for r in rs])):8.0f}%" if rs else f"{'-':>9s}")
        print(f"{pn:18s}" + "".join(cells))

    print("\n# 3. Does the detector's prior track the truth? For every aimed row: "
          "the old harness's 'fixed' (drop in the preset's own prior, render -> "
          "cleaned) against ground-truth efficacy")
    xs, ys = [], []
    for r in rows:
        if not r["targeted"] or r["preset"] == "static_repair" or not r.get("evidence_cleaned"):
            continue
        pb = prior_of(r["preset"], r["evidence_render"])
        pa = prior_of(r["preset"], r["evidence_cleaned"])
        if pb < 0.25:
            continue
        xs.append((pb - pa) / pb)
        ys.append(r["efficacy"])
    if len(xs) >= 3:
        c = float(np.corrcoef(xs, ys)[0, 1])
        print(f"  {len(xs)} rows where the prior saw the artifact (>= 0.25): "
              f"correlation(prior-drop, true efficacy) = {c:+.3f}")
    else:
        print(f"  only {len(xs)} rows where the prior saw the artifact; no correlation to report")
    seen = []
    for r in rows:
        if r["targeted"] and r["level"] == top and r["preset"] != "static_repair":
            pr = prior_of(r["preset"], r["evidence_render"])
            ph = prior_of(r["preset"], r["evidence_host"])
            seen.append((r["artifact"], r["preset"], ph, pr))
    print("  Does the prior rise when its artifact is injected at the top level? "
          "(host prior -> render prior, mean over hosts)")
    for an in arts:
        for pn in presets:
            v = [(ph, pr) for a, p, ph, pr in seen if a == an and p == pn]
            if v:
                print(f"    {an:10s} {pn:18s} {np.mean([h for h, _ in v]):.2f} -> {np.mean([p for _, p in v]):.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
