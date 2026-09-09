"""
verify_tone_fix.py — Did swapping the tone target actually close the gap?

Runs the real chain twice over each source: once with the old 1950-2010 curve,
once with the measured one. Everything else is held identical — same preset,
same strength, same mastering, same limiter — so the only variable is the tone
target. Then measures each result against that song's reference master.

This answers the question the whole effort exists for, and it produces the
audio for a listening round at the same time, because a number that says the
gap closed is worth nothing until someone confirms it by ear.

Usage:  python scripts/verify_tone_fix.py [--preset NAME] [--render DIR]
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shimmer import mastering as M                             # noqa: E402
from shimmer.audio_io import load_audio, save_audio            # noqa: E402
from shimmer.params import MasterParams                        # noqa: E402
from shimmer.pipeline import clean_and_master                  # noqa: E402
from shimmer.presets import PRESETS                            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = os.path.join(ROOT, "sources")

# The curve as it shipped before this change: the AES 1950-2010 average.
OLD_SHAPE = np.array([
    -2.5, 1.0, 3.5, 4.5, 5.0, 5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0, 1.5, 1.0,
    0.5, 0.0, -0.5, -1.0, -1.5, -2.0, -2.5, -3.0, -4.3, -5.8, -7.5,
    -9.5, -12.0, -16.0, -22.0,
], dtype=np.float64)
NEW_SHAPE = M._REF_SHAPE_DB.copy()

EXCERPT_S = 30.0
LOW_HZ, HIGH_HZ = 800.0, 6300.0     # the tilt the gap is quoted across


def _set_target(shape: np.ndarray) -> None:
    """Swap the module-level target. Both _REF_SHAPE_DB and the derived
    _REF_DB have to move together — compute_tone_curve reads the derived one."""
    M._REF_SHAPE_DB = shape
    M._REF_DB = shape - np.median(shape[M._MID_BANDS])


def _rel(x, sr):
    return np.array(M.relative_band_levels(
        np.array(M.analyze_spectrum(x, sr)["band_power_db"])))


def _band(i_hz):
    return int(np.argmin(np.abs(M._REF_FREQS - i_hz)))


def _excerpt(x, sr):
    n = int(EXCERPT_S * sr)
    if x.shape[0] <= n:
        return x
    s = (x.shape[0] - n) // 2
    return np.ascontiguousarray(x[s:s + n])


def main(argv) -> int:
    preset = (argv[argv.index("--preset") + 1] if "--preset" in argv
              else "suno_hash")
    render = (argv[argv.index("--render") + 1] if "--render" in argv else "")
    if render:
        os.makedirs(render, exist_ok=True)

    songs = []
    for f in sorted(os.listdir(SOURCES)):
        if f.startswith("suno-") and f.endswith(".wav"):
            stem = f[5:-4]
            ref = os.path.join(SOURCES, f"distrokid-{stem}.wav")
            if os.path.exists(ref):
                songs.append((stem, os.path.join(SOURCES, f), ref))

    lo, hi = _band(LOW_HZ), _band(HIGH_HZ)
    mp = MasterParams(enabled=True, target_lufs=-14.0, ceiling_dbtp=-1.0,
                      intensity="med", tilt="neutral")

    print(f"preset: {preset}   tilt gap measured {LOW_HZ:.0f} Hz -> "
          f"{HIGH_HZ / 1000:.1f} kHz\n")
    print(f"{'song':30s} {'OLD gap':>9} {'NEW gap':>9} {'closed':>8}")

    olds, news = [], []
    for stem, src_path, ref_path in songs:
        src, sr = load_audio(src_path)
        ref, _ = load_audio(ref_path)
        src, ref = _excerpt(src, sr), _excerpt(ref, sr)
        b_src, b_ref = _rel(src, sr), _rel(ref, sr)

        gaps = {}
        for name, shape in (("old", OLD_SHAPE), ("new", NEW_SHAPE)):
            _set_target(shape)
            y, _rm, _rep = clean_and_master(
                src, sr, PRESETS[preset](), master_params=mp,
                eq_params=None, repair=None)
            y = np.asarray(y)[:src.shape[0]]
            b_y = _rel(y, sr)
            # What each chain did to the same source, then the gap between
            # the two chains' tilts. Band levels are already normalised, so
            # no extra loudness alignment is needed.
            shim = (b_y[hi] - b_y[lo]) - (b_src[hi] - b_src[lo])
            refr = (b_ref[hi] - b_ref[lo]) - (b_src[hi] - b_src[lo])
            gaps[name] = refr - shim
            if render:
                save_audio(os.path.join(render, f"{stem}-{name}.wav"),
                           y, sr, subtype="PCM_24")
        if render:
            save_audio(os.path.join(render, f"{stem}-source.wav"), src, sr,
                       subtype="PCM_24")
        olds.append(gaps["old"])
        news.append(gaps["new"])
        print(f"{stem[:30]:30s} {gaps['old']:9.2f} {gaps['new']:9.2f} "
              f"{gaps['old'] - gaps['new']:8.2f}")

    _set_target(NEW_SHAPE)
    o, n = np.array(olds), np.array(news)
    print()
    print(f"mean gap  before {o.mean():6.2f} dB   after {n.mean():6.2f} dB   "
          f"closed {o.mean() - n.mean():.2f} dB "
          f"({100.0 * (o.mean() - n.mean()) / abs(o.mean()):.0f}%)")
    print(f"spread    before {o.std():6.2f}      after {n.std():6.2f}")
    if render:
        print(f"\nrendered to {render}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
