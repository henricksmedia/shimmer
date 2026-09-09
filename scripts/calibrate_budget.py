"""
calibrate_budget.py — Derive budget.SONES_PER_DB from real material.

The budget converts measured artifact (dB of excess flicker in 4.5-12 kHz)
into an allowance (sones of audible removal). That conversion needs a number,
and inventing one would be guesswork, so it is fit here against two anchors
that come from measurement and from listening rather than from taste:

  * **Suno Hash on the four reference sources.** A listener judged this preset
    correctly targeted, with only very slight over-reach, on all four. So the
    allowance should land at or just under what it actually costs.
  * **A finished master with no hash.** the clean control measures -0.2 dB
    of excess flicker, so its budget must come out at zero. This is the anchor
    that stops a clean track being cleaned.

Run after changing the damage model or the presets; it prints the fitted
constant and whether the current one still holds.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shimmer import budget as B                            # noqa: E402
from shimmer import perceptual as P                        # noqa: E402
from shimmer.audio_io import load_audio                    # noqa: E402
from shimmer.detect import evidence_scan                   # noqa: E402
from shimmer.pipeline import clean_and_master              # noqa: E402
from shimmer.presets import PRESETS                        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "sources")
SONGS = ["algorithms-lure", "alive-again", "leave-the-world-behind",
         "we-were-meant-for-the-stars"]
CLEAN_CONTROL = os.path.join(ROOT, "assets", "reference", "reference-hey.wav")
CLIP_S = 25.0


def excerpt(path):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from make_listening_test import loudest_excerpt
    x, sr = load_audio(path)
    return loudest_excerpt(x, sr, CLIP_S), sr


def main() -> None:
    print("Anchor 1 — what the well-aimed preset costs on hashed sources\n")
    print(f"{'song':30s} {'excess dB':>10} {'suno_hash cost':>15} "
          f"{'implied k':>10}")
    ks = []
    for s in SONGS:
        clip, sr = excerpt(os.path.join(SRC, f"suno-{s}.wav"))
        ev = evidence_scan(clip, sr).evidence
        y, _, _ = clean_and_master(clip, sr, PRESETS["suno_hash"](),
                                   master_params=None, eq_params=None,
                                   repair=None)
        d = P.measure_damage(clip, np.asarray(y)[:clip.shape[0]], sr)
        head = ev.flicker_excess_db - B.EXCESS_FLOOR_DB
        k = d.missing / head if head > 0 else float("nan")
        if head > 0:
            ks.append(k)
        print(f"{s[:30]:30s} {ev.flicker_excess_db:10.2f} "
              f"{d.missing:15.4f} {k:10.4f}")

    fitted = float(np.median(ks)) if ks else float("nan")
    print(f"\nfitted SONES_PER_DB (median) = {fitted:.4f}")
    print(f"currently in budget.py       = {B.SONES_PER_DB:.4f}")

    print("\nAnchor 2 — a finished master with no hash must earn nothing\n")
    clip, sr = excerpt(CLEAN_CONTROL)
    ev = evidence_scan(clip, sr).evidence
    bud = B.estimate_budget(clip, sr, ev.flicker_excess_db)
    print(f"  clean control  excess {ev.flicker_excess_db:+.2f} dB  "
          f"-> budget {bud.sones:.4f} sones")
    print(f"  {'PASS' if bud.sones == 0.0 else 'FAIL'}: "
          f"a clean master must earn a zero budget")

    print("\nEffect on the preset that ignores the signal\n")
    y, _, _ = clean_and_master(clip, sr, PRESETS["deep_scrub"](),
                              master_params=None, eq_params=None, repair=None)
    y = np.asarray(y)[:clip.shape[0]]
    d_before = P.measure_damage(clip, y, sr)
    held, rep = B.apply_within_budget(clip, y, sr, bud)
    d_after = P.measure_damage(clip, held, sr)
    print(f"  Deep Scrub unbudgeted: missing {d_before.missing:.4f} sones, "
          f"lin_dist {d_before.lin_dist:.2f}")
    print(f"  Deep Scrub budgeted:   missing {d_after.missing:.4f} sones, "
          f"lin_dist {d_after.lin_dist:.2f}  (mix {rep.mix:.2f})")
    print(f"  {rep.reason}")


if __name__ == "__main__":
    main()
