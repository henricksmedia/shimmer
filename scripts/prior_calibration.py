"""
prior_calibration.py — Where do the detector's evidence features sit on
clean music, on real renders, and on music with a known artifact injected?

Checklist item 10. `detect.priors_from_evidence` ramps each feature between
two edges set from 26 Suno renders (about their 20th and 85th percentiles)
with no clean control, so a prior of 1.0 means "unusually strong for Suno
material" and nothing says "no artifact". Measured on finished masters,
presence-band priors read 0.7-1.0.

This script does not change anything. It reads two cached measurements:

  docs/efficacy-harness.json   evidence on 5 clean hosts, and on the same
                               hosts with each modelled artifact injected at
                               0.5 and 2.0 sones (evidence_host /
                               evidence_render)
  docs/score-probe.json        evidence on the real corpus: finished
                               masters, Shimmer masters, Suno renders

and prints, per feature the priors use: the clean-host range, the real
render range, the injected range for the artifact the feature is meant to
see, and the current ramp edges — so the next decision is made from the
table, not from memory.

Usage: python scripts/prior_calibration.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# feature -> (which modelled artifact should raise it, the ramp edges BEFORE the
#             2026-09-08 recalibration (kept so the table shows old vs new), presets that use it)
FEATURES = {
    "flicker_excess_db": ("hash", (0.5, 3.0), "suno_hash, vocal_glaze_plus"),
    "comb": ("comb", (0.15, 0.45), "checkerboard_grid, cymbal_chatter"),
    "flat_8_18": ("fizz", (0.15, 0.45), "broadband_fizz"),
    "sib_burst": ("sibilance", (0.05, 0.25), "sibilance_rattle"),
    "echo_corr": ("shadow", (0.30, 0.60), "echo_sheen"),
    "flat_3_8": ("shadow", (0.25, 0.55), "vocal_glaze, echo_sheen, presence_haze"),
    "flat_4_12": ("shadow", (0.25, 0.55), "harsh_veil"),
    "presence_db": ("shadow", (-14.0, -2.0), "vocal_glaze, presence_haze, phantom_cymbal"),
    "umid_db": ("shadow", (-16.0, -4.0), "harsh_veil"),
    "ring_4_10": (None, (0.10, 0.40), "phantom_cymbal"),
    "period_excess": (None, (0.05, 0.30), "cymbal_chatter"),
    "tail_contrast": (None, (0.0, 0.03), "reverb_flutter"),
    "top_tilt_db": (None, (-12.0, -3.0), "air_brittle"),
}
TONES = {"tone_8_12": ("line", (3.0, 12.0), "cymbal_sheen"),
         "tone_9_15": ("whistle", (3.0, 12.0), "laser_whistle"),
         "tone_12_20": ("line", (4.0, 12.0), "air_brittle, laser_whistle")}


def pct(v, p):
    return float(np.percentile(v, p)) if len(v) else float("nan")


def rng(v):
    return f"{pct(v, 16):7.2f} {pct(v, 50):7.2f} {pct(v, 84):7.2f}" if len(v) else f"{'-':>23s}"


def main(argv):
    h = json.load(open(os.path.join(ROOT, "docs", "efficacy-harness.json"), encoding="utf-8"))["rows"]
    s = json.load(open(os.path.join(ROOT, "docs", "score-probe.json"), encoding="utf-8"))
    # One evidence record per (host) and per (host, artifact, level).
    hosts, injected = {}, {}
    for r in h:
        hosts[r["host"]] = r["evidence_host"]
        injected[(r["host"], r["artifact"], r["level"])] = r["evidence_render"]
    # score-probe rows carry only flicker; the rest of the real-corpus
    # evidence is in the harness's host records (finished masters) and the
    # per-file scans below.
    real = {}
    for r in s:
        real.setdefault(r["file"], r)
    finished = [f for f in real if f.startswith(("distrokid-", "reference-"))]
    renders = [f for f in real if f.startswith("suno-")]

    print("Feature ranges: 16th / 50th / 84th percentile.  'clean' = 5 clean hosts "
          "(finished masters without hash); 'inject' = the same hosts with the "
          "named model at 0.5 and 2.0 sones.\n")
    print(f"{'feature':18s} {'model':10s} {'clean (n=5)':>23s} {'inject 0.5':>23s} "
          f"{'inject 2.0':>23s}   ramp lo..hi   used by")
    for feat, (model, ramp, used) in FEATURES.items():
        clean = [e[feat] for e in hosts.values() if feat in e]
        if model:
            i05 = [e[feat] for (hh, a, L), e in injected.items() if a == model and L == 0.5]
            i20 = [e[feat] for (hh, a, L), e in injected.items() if a == model and L == 2.0]
        else:
            i05 = i20 = []
        print(f"{feat:18s} {model or '-':10s} {rng(clean):>23s} {rng(i05):>23s} {rng(i20):>23s}"
              f"   {ramp[0]:5.2f}..{ramp[1]:<5.2f}  {used}")
    print()
    for feat, (model, ramp, used) in TONES.items():
        clean = [e[feat]["excess_db"] for e in hosts.values() if feat in e]
        i05 = [e[feat]["excess_db"] for (hh, a, L), e in injected.items() if a == model and L == 0.5 and feat in e]
        i20 = [e[feat]["excess_db"] for (hh, a, L), e in injected.items() if a == model and L == 2.0 and feat in e]
        print(f"{feat + ' excess':18s} {model:10s} {rng(clean):>23s} {rng(i05):>23s} {rng(i20):>23s}"
              f"   {ramp[0]:5.2f}..{ramp[1]:<5.2f}  {used}")

    print("\nReal corpus, flicker_excess_db (the hash feature) by file class:")
    for name, files in (("finished masters", finished), ("Suno renders", renders)):
        v = [real[f]["flicker_excess_db"] for f in files]
        print(f"  {name:18s} n={len(v):2d}  {rng(v)}")

    print("\nHow the current priors read on the clean hosts (from evidence_host):")
    from recorded_evidence import priors_from_recorded  # noqa: E402
    for hname, e in hosts.items():
        pr = priors_from_recorded(e)
        top = sorted(pr.items(), key=lambda kv: -kv[1])[:4]
        print(f"  {hname:38s} " + ", ".join(f"{k} {v:.2f}" for k, v in top))

    # ---- Proposed edges -------------------------------------------------
    # Clean side: every finished master in the corpus (the 4 that carry hash
    # are still finished masters for every feature but flicker), scanned
    # here so the clean sample is 9 files, not 5.
    import glob
    from shimmer.audio_io import load_audio
    from shimmer.detect import evidence_scan
    clean_files = (sorted(glob.glob(os.path.join(ROOT, "sources", "distrokid-*.wav")))
                   + sorted(glob.glob(os.path.join(ROOT, "assets", "reference", "*.wav"))))
    clean_files = [f for f in clean_files if "kindling" not in f]
    clean_ev = []
    for f in clean_files:
        x, sr = load_audio(f)
        ev = evidence_scan(x, sr).evidence
        d = {k: float(getattr(ev, k)) for k in FEATURES}
        for k in TONES:
            d[k] = float(getattr(ev, k).excess_db)
        d["upper_db"] = float(ev.upper_db)
        d["click_rate"] = float(ev.click_rate)
        clean_ev.append(d)
    print(f"\nProposed ramp edges. Rule: lo = 84th percentile of the {len(clean_ev)} "
          "finished masters (clean reads ~0 above the run of the mill); hi = the "
          "median reading with the model injected at 2.0 sones where a model exists, "
          "otherwise lo plus the old ramp's width. Flicker excludes the 4 masters "
          "that carry hash.")
    print(f"{'feature':18s} {'clean p50':>9s} {'clean p84':>9s} {'inj2.0 p50':>10s}  "
          f"{'old lo..hi':>14s}  {'new lo..hi':>14s}")
    for feat, (model, ramp, used) in list(FEATURES.items()) + list(TONES.items()):
        if feat == "flicker_excess_db":
            cv = [d[feat] for d in clean_ev if d[feat] < 0.5]
        else:
            cv = [d[feat] for d in clean_ev]
        lo = pct(cv, 84)
        if model:
            src = [e[feat] if feat in FEATURES else e[feat]["excess_db"]
                   for (hh, a, L), e in injected.items() if a == model and L == 2.0]
            hi = pct(src, 50)
        else:
            src = []
            hi = lo + (ramp[1] - ramp[0])
        if hi <= lo:
            hi = lo + (ramp[1] - ramp[0])
        print(f"{feat:18s} {pct(cv, 50):9.2f} {lo:9.2f} {(pct(src, 50) if src else float('nan')):10.2f}  "
              f"{ramp[0]:6.2f}..{ramp[1]:<6.2f}  {lo:6.2f}..{hi:<6.2f}")
    for extra in ("upper_db", "click_rate"):
        cv = [d[extra] for d in clean_ev]
        print(f"{extra:18s} {pct(cv, 50):9.2f} {pct(cv, 84):9.2f} {'-':>10s}  (no model; used by "
              f"{'broadband_fizz' if extra == 'upper_db' else 'sibilance_rattle'})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
