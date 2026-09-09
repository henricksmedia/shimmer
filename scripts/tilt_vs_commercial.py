"""tilt_vs_commercial.py — does the chain now land where real records sit?

Every tilt figure quoted so far measured Shimmer's output against the
automated service's master of the same song. That was the only reference
available, and §7 of BRIGHTNESS-ASSESSMENT.md then measured the service
itself about 7 dB bright through presence and air. So "6 dB duller than the
service" never meant "6 dB duller than commercial music", and the number
could not answer the question the tool exists to answer.

This measures against captured commercial masters instead — other people's
finished records, played through this machine and measured by the reference
library. It runs the real chain over each source twice, once with the
retracted target and once with the derived one, holding everything else
identical, so the only variable is the target.

Usage:  ./.venv/Scripts/python.exe scripts/tilt_vs_commercial.py
"""
from __future__ import annotations

import glob
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from shimmer import mastering as M                      # noqa: E402
from shimmer import references as R                     # noqa: E402
from shimmer.audio_io import load_audio                 # noqa: E402
from shimmer.params import MasterParams                 # noqa: E402
from shimmer.pipeline import clean_and_master           # noqa: E402
from shimmer.presets import PRESETS                     # noqa: E402

LOW_HZ, HIGH_HZ = 800.0, 6300.0     # the tilt every earlier figure was quoted across

# The curve retracted on 2026-09-08: the median of 135 masters one automated
# service produced from AI renders. Kept here only so the two can be run
# against each other; it is not a target and must not be used as one.
RETRACTED = np.array([
    -3.7, 4.3, 8.3, 8.8, 7.9, 7.4, 7.4, 6.3, 4.5, 2.1, 0.3, -0.7, 0.0, 0.5,
    -1.5, -1.5, -1.4, -0.7, 0.0, 0.6, 0.7, 1.1, -0.1, -1.0, -0.4,
    -1.5, -5.8, -13.1, -25.4,
], dtype=np.float64)


def band(hz: float) -> int:
    return int(np.argmin(np.abs(M._REF_FREQS - hz)))


def tilt(rel_db: np.ndarray) -> float:
    """High minus low, on the normalised band curve. Higher = brighter."""
    return float(rel_db[band(HIGH_HZ)] - rel_db[band(LOW_HZ)])


def use(shape: np.ndarray) -> None:
    """Swap the module-level target. compute_tone_curve reads the derived
    _REF_DB, so both have to move together."""
    M._REF_SHAPE_DB = np.asarray(shape, dtype=np.float64)
    M._REF_DB = M._REF_SHAPE_DB - np.median(M._REF_SHAPE_DB[M._MID_BANDS])


def commercial_tilt() -> tuple:
    rows = [t for t in R.load().get("tracks", [])
            if not (t.get("rejected") or R.rejection(t)) and not R.is_control(t)]
    if not rows:
        raise SystemExit("No validated commercial captures.")
    v = np.array([tilt(np.asarray(t["rel_db"], dtype=np.float64)) for t in rows])
    return float(np.median(v)), float(v.std(ddof=1) / np.sqrt(len(v))), len(v)


def run(path: str, shape: np.ndarray) -> float:
    use(shape)
    x, sr = load_audio(path)
    y, _, _ = clean_and_master(x, sr, PRESETS["generic"](),
                               master_params=MasterParams(
                                   enabled=True, intensity="med", tilt="neutral"))
    return tilt(np.asarray(M.analyze_spectrum(y, sr)["rel_db"], dtype=np.float64))


def main() -> None:
    target, se, n = commercial_tilt()
    derived = M._REF_SHAPE_DB.copy()
    files = sorted(glob.glob(os.path.join(ROOT, "sources", "suno-*.wav")))
    if not files:
        raise SystemExit("No Suno sources to run.")

    print(f"Commercial masters, {LOW_HZ:.0f} Hz -> {HIGH_HZ/1000:.1f} kHz tilt: "
          f"{target:+.2f} dB (n={n}, se {se:.2f})")
    print(f"Target tilts: retracted {tilt(RETRACTED):+.2f} dB, "
          f"derived {tilt(derived):+.2f} dB")
    print()
    print(f"{'source':<30} {'retracted':>10} {'derived':>9} "
          f"{'gap before':>11} {'gap after':>10}")
    before, after = [], []
    for p in files:
        name = os.path.basename(p).replace("suno-", "").replace(".wav", "")
        t_old = run(p, RETRACTED)
        t_new = run(p, derived)
        before.append(t_old - target)
        after.append(t_new - target)
        print(f"{name:<30} {t_old:10.2f} {t_new:9.2f} "
              f"{before[-1]:+11.2f} {after[-1]:+10.2f}")

    use(derived)
    b, a = np.array(before), np.array(after)
    print()
    print(f"gap to commercial, before : mean {b.mean():+.2f} dB, "
          f"median {np.median(b):+.2f}, |mean| {np.abs(b).mean():.2f}")
    print(f"gap to commercial, after  : mean {a.mean():+.2f} dB, "
          f"median {np.median(a):+.2f}, |mean| {np.abs(a).mean():.2f}")
    print(f"closed {np.abs(b).mean() - np.abs(a).mean():+.2f} dB of "
          f"{np.abs(b).mean():.2f} dB "
          f"({100*(np.abs(b).mean()-np.abs(a).mean())/max(np.abs(b).mean(),1e-9):.0f}%)")
    print()
    print("Positive gap = Shimmer brighter than commercial; negative = duller.")


if __name__ == "__main__":
    main()
