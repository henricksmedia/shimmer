"""
efficacy_harness.py — Does each preset remove the artifact, and what does
it cost? Measured against ground truth, not against the detector.

The earlier harness (preset_harness.py) judged efficacy by the detector's
own prior before and after cleaning. That is circular: the prior is the
component shown to be miscalibrated, and it is a relative measure that
other bands' removal inflates. This one does not use the detector to judge.

Method
------
  host H      a finished master with no measurable hash (flicker excess
              below budget.EXCESS_FLOOR_DB on its hot window), loudest
              CLIP_S seconds.
  artifact A  one of shimmer.artifacts, scaled so that the hearing model
              says it adds L sones of audible content to H:
              added(H, H + A) = L, for each L in LEVELS. The level is
              measured, not chosen, so every artifact starts equally
              audible, and the levels bracket what the detector's own test
              signals inject (see the LEVELS comment).
  render R    H + A.
  cleaned C   preset(R); control K = preset(H), the same preset on the
              clean host. Real cleaning pipeline, no mastering / EQ.

  efficacy    1 - added(K, C) / added(H, R)
              What the cleaned render still has that the cleaned clean host
              does not: the artifact's footprint after cleaning. Comparing
              C with K rather than with H cancels what the cleaner does to
              the music on its own (FlickerTamer alone registers ~0.07
              sones of "added" on a clean master, which would otherwise
              read as artifact residue). 0 = nothing removed, 1 = gone; an
              inert preset scores exactly 0 because K = H and C = R.
  cost        missing(H, C) and lin_dist(H, C): music removed and tone tilt,
              measured against the clean host, net of the same measures
              for the un-cleaned render, missing(H, R): a loud artifact
              masks host content and tilts the spectrum on its own, and
              that is not the cleaner's doing. `cost_missing` /
              `cost_lin_dist` are the net values (floored at 0); the raw
              ones are kept as `*_raw`. Also reported for the control,
              missing(H, K): the cost with nothing to fix.

For the fixed-line models the product runs the static repair first, so a
`static_repair` row is measured too (the whole-file scan's notch plan, no
preset).

The detector's evidence is recorded for host, render and cleaned output so
the prior-based "efficacy" the old harness reported can be compared with
the ground-truth one, but nothing here is judged by it.

Everything is written to docs/efficacy-harness.json, one row per
(host, artifact, level, preset, strength). tests/test_efficacy.py asserts
relations over that file, not thresholds.

Usage:
    python scripts/efficacy_harness.py [--hosts a,b] [--artifacts x,y]
        [--presets p,q] [--strengths 0.5,1,2] [--levels 0.1,0.3,1.0]
        [--out FILE]
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
from dataclasses import asdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from shimmer import artifacts as A                              # noqa: E402
from shimmer import detect as D                                 # noqa: E402
from shimmer.audio_io import load_audio                          # noqa: E402
from shimmer.budget import EXCESS_FLOOR_DB                       # noqa: E402
from shimmer.params import apply_preset_strength                 # noqa: E402
from shimmer.perceptual import measure_damage                    # noqa: E402
from shimmer.pipeline import clean_and_master                    # noqa: E402
from shimmer.presets import get_preset                           # noqa: E402
from shimmer.repair import apply_static_repair, plan_from_lines  # noqa: E402
from make_listening_test import loudest_excerpt                  # noqa: E402

CLIP_S = 8.0
# Injection levels, sones of audible content added to the host. 0.10 is the
# budget's ceiling on audible removal (as much as the tool may ever take
# out). Measured on tests/test_detect.py's synthetic bed: its hash injects
# 5.65 sones at the level the tests use (0.09) and 0.46 sones at 0.03, which
# is where the flicker measure first registers it (+1.0 dB excess). 2.0 is
# therefore "plainly there" and 0.5 "just detectable". 0.1 was measured on
# one host and every preset read within +/-0.05 of zero efficacy on it: too
# faint for either instrument, so it is not in the default set.
LEVELS = (0.5, 2.0)
LEVEL_ITERS = 12
HOST_GLOBS = ("sources/distrokid-*.wav", "assets/reference/*.wav")
EVIDENCE = ("flicker_excess_db", "flat_3_8", "flat_4_12", "flat_8_18",
            "presence_db", "ring_4_10", "comb", "sib_burst", "tail_contrast",
            "period_excess", "echo_corr", "umid_db", "top_tilt_db")


def hosts(names=None):
    files = []
    for g in HOST_GLOBS:
        files += sorted(glob.glob(os.path.join(ROOT, g)))
    out = []
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0]
        if names and name not in names:
            continue
        x, sr = load_audio(f)
        ev = D.evidence_scan(x, sr).evidence
        if ev.flicker_excess_db >= EXCESS_FLOOR_DB:
            print(f"host {name}: flicker excess {ev.flicker_excess_db:+.2f} dB, "
                  f"carries hash, skipped")
            continue
        clip = loudest_excerpt(x, sr, CLIP_S)
        out.append((name, np.ascontiguousarray(clip.astype(np.float32)), sr,
                    round(float(ev.flicker_excess_db), 2)))
    return out


def match_level(host, art, sr, target):
    """Gain on `art` such that added(host, host + gain*art) == target.
    Audibility rises with gain, so bisect in log gain."""
    lo, hi = -80.0, 20.0
    peak = float(np.max(np.abs(art))) or 1.0
    art = art / peak * float(np.max(np.abs(host)))
    for _ in range(LEVEL_ITERS):
        mid = 0.5 * (lo + hi)
        g = 10.0 ** (mid / 20.0)
        d = measure_damage(host, host + g * art, sr)
        if d.added < target:
            lo = mid
        else:
            hi = mid
    g = 10.0 ** (0.5 * (lo + hi) / 20.0)
    return (g * art).astype(np.float32), measure_damage(host, host + g * art, sr)


def run_preset(x, sr, name, strength=1.0):
    p = get_preset(name)
    if abs(strength - 1.0) > 1e-6:
        apply_preset_strength(p, float(strength))
    y, _, _ = clean_and_master(x, sr, p, master_params=None, eq_params=None,
                               repair=None)
    return np.ascontiguousarray(np.asarray(y, dtype=np.float32)[:x.shape[0]])


def run_static_repair(x, sr):
    ev = D.evidence_scan(x, sr).evidence
    plan = plan_from_lines([asdict(t) for t in ev.tones], sr)
    if not plan.notches:
        return x, 0
    y, _ = apply_static_repair(x, sr, plan)
    return np.ascontiguousarray(np.asarray(y, dtype=np.float32)[:x.shape[0]]), len(plan.notches)


def evidence(x, sr):
    ev = D.evidence_scan(x, sr).evidence
    out = {k: round(float(getattr(ev, k)), 3) for k in EVIDENCE}
    for k in ("tone_8_12", "tone_9_15", "tone_12_20"):
        t = getattr(ev, k)
        out[k] = {"hz": round(float(t.hz), 1), "excess_db": round(float(t.excess_db), 2),
                  "duty": round(float(t.duty), 3)}
    return out


def _row(base, preset, strength, K, C, H, sr, d_in, **extra):
    d_c = measure_damage(H, C, sr)
    d_res = measure_damage(K, C, sr)
    return {**base, "preset": preset, "strength": strength,
            "residue_added": round(d_res.added, 4),
            "efficacy": round(1.0 - d_res.added / max(d_in.added, 1e-9), 3),
            "cost_missing": round(max(0.0, d_c.missing - d_in.missing), 4),
            "cost_lin_dist": round(max(0.0, d_c.lin_dist - d_in.lin_dist), 3),
            "cost_missing_raw": round(d_c.missing, 4),
            "cost_lin_dist_raw": round(d_c.lin_dist, 3),
            "cost_added": round(d_c.added, 4),
            **extra}


def main(argv):
    def opt(flag, default=None):
        if flag in argv:
            return argv[argv.index(flag) + 1]
        return default
    host_names = opt("--hosts").split(",") if opt("--hosts") else None
    art_names = (opt("--artifacts") or ",".join(A.GENERATORS)).split(",")
    preset_names = (opt("--presets")
                    or ",".join(D.artifact_preset_names() + ["generic"])).split(",")
    strengths = [float(s) for s in (opt("--strengths") or "1.0").split(",")]
    levels = [float(s) for s in opt("--levels").split(",")] if opt("--levels") else list(LEVELS)
    out_path = opt("--out", os.path.join(ROOT, "docs", "efficacy-harness.json"))

    hs = hosts(host_names)
    print(f"{len(hs)} hosts x {len(art_names)} artifacts x {len(levels)} levels x "
          f"{len(preset_names)} presets x {len(strengths)} strengths\n")
    rows = []
    if "--append" in argv and os.path.exists(out_path):
        # Add presets to an existing result instead of re-running it all;
        # rows for the same (host, artifact, level, preset, strength) are
        # replaced.
        old = json.load(open(out_path, encoding="utf-8"))["rows"]
        keys = {(r["host"], r["artifact"], r["level"], r["preset"], r["strength"])
                for r in old}
        new_keys = {(h, a, L, p, s) for h, _, _, _ in hs for a in art_names
                    for L in levels for p in preset_names for s in strengths}
        rows = [r for r in old if (r["host"], r["artifact"], r["level"], r["preset"],
                                   r["strength"]) not in new_keys]
        print(f"appending to {len(rows)} existing rows")
    t0 = time.time()
    for hname, H, sr, hflick in hs:
        # Controls: every preset at every strength on the clean host.
        K = {}
        control = {}
        for pn in preset_names:
            for s in strengths:
                K[pn, s] = run_preset(H, sr, pn, s)
                d = measure_damage(H, K[pn, s], sr)
                control[pn, s] = {"missing": round(d.missing, 4),
                                  "lin_dist": round(d.lin_dist, 3),
                                  "added": round(d.added, 4)}
        ev_host = evidence(H, sr)
        for an in art_names:
            raw = A.make(an, H.shape[0], sr, host=H)
            for L in levels:
                art, d_in = match_level(H, raw, sr, L)
                R = (H + art).astype(np.float32)
                base = {"host": hname, "host_flicker_excess_db": hflick,
                        "artifact": an, "level": L,
                        "injected_added": round(d_in.added, 4),
                        "injected_missing": round(d_in.missing, 4),
                        "injected_lin_dist": round(d_in.lin_dist, 3),
                        "evidence_host": ev_host, "evidence_render": evidence(R, sr)}
                Cs, n_notch = run_static_repair(R, sr)
                rows.append(_row(base, "static_repair", 1.0, H, Cs, H, sr, d_in,
                                 notches=n_notch, control={"missing": 0.0, "lin_dist": 0.0,
                                                           "added": 0.0},
                                 targeted=an in ("line", "whistle", "comb")))
                for pn in preset_names:
                    for s in strengths:
                        C = run_preset(R, sr, pn, s)
                        rows.append(_row(
                            base, pn, s, K[pn, s], C, H, sr, d_in,
                            control=control[pn, s],
                            evidence_cleaned=evidence(C, sr) if s == 1.0 else None,
                            targeted=pn in A.TARGETS.get(an, ())))
                print(f"{hname:36s} {an:10s} L={L:<4} done  {time.time() - t0:6.0f} s",
                      flush=True)
                with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                    json.dump({"clip_s": CLIP_S, "levels": levels, "rows": rows},
                              f, indent=1)
    summarise(rows)
    print(f"\nwrote {out_path}")
    return 0


def summarise(rows):
    arts = sorted({r["artifact"] for r in rows})
    levels = sorted({r["level"] for r in rows})
    presets = []
    for r in rows:
        if r["preset"] not in presets:
            presets.append(r["preset"])
    for L in levels:
        print(f"\n=== Efficacy at {L} sones injected (share of the audible "
              f"artifact removed), strength 1.0, mean over hosts; * = aimed at it ===")
        print(f"{'preset':18s}" + "".join(f"{a:>11s}" for a in arts)
              + f"{'cost':>8s}{'ctrl':>8s}")
        for pn in presets:
            cells = []
            for an in arts:
                rs = [r for r in rows if r["preset"] == pn and r["artifact"] == an
                      and r["strength"] == 1.0 and r["level"] == L]
                if not rs:
                    cells.append(f"{'-':>11s}")
                    continue
                e = float(np.mean([r["efficacy"] for r in rs]))
                star = "*" if rs[0]["targeted"] else " "
                cells.append(f"{100 * e:9.0f}%{star}")
            rs = [r for r in rows if r["preset"] == pn and r["strength"] == 1.0
                  and r["level"] == L]
            cost = float(np.mean([r["cost_missing"] for r in rs])) if rs else float("nan")
            ctrl = float(np.mean([r["control"]["missing"] for r in rs])) if rs else float("nan")
            print(f"{pn:18s}" + "".join(cells) + f"{cost:8.3f}{ctrl:8.3f}")
    print("\ncost = missing (sones) against the clean host, mean over hosts and "
          "artifacts; ctrl = the same preset on the clean host alone")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
