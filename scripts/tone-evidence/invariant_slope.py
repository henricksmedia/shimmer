"""The percussion-invariant test.

Elowsson & Friberg Section 4.2: across 11 groups spanning Lperc -23.1 to
-9.8 dB -- from sparse folk to dense electronic -- the PSD slope from 89 Hz
to 4.5 kHz stays at 4.53 dB/octave, with a standard deviation between groups
of 0.055 dB/octave. Section 6.3 repeats it as a headline finding.

That makes it the one figure the "their corpus is folky, ours is electronic"
objection cannot touch. Any master, any genre, any amount of percussion:
this slope should come out near -4.53. So measure it on everything.
"""
import glob
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

f = np.asarray(_REF_FREQS, float)
PAPER = -4.53
F1, F2 = 89.0, 4500.0


def psd(band_db):
    return np.asarray(band_db, float) - 10.0 * np.log10(0.2316 * f)


def invariant_slope(band_db):
    p = psd(band_db)
    m = np.isfinite(p)
    a, b = np.interp(np.log2([F1, F2]), np.log2(f[m]), p[m])
    return (b - a) / np.log2(F2 / F1)


BASS, MID = (-0.000907, 0.256, -32.942), (-0.000183, 0.0213, -16.735)


def elow_psd(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    a, b, c = np.where(x < 100.0, BASS[0], MID[0]), \
        np.where(x < 100.0, BASS[1], MID[1]), np.where(x < 100.0, BASS[2], MID[2])
    return a * x ** 2 + b * x + c


print(f"self-check, their own curve at 89 Hz -> 4.5 kHz: "
      f"{(elow_psd(F2)-elow_psd(F1))/np.log2(F2/F1):+.2f} dB/oct "
      f"(paper says {PAPER:+.2f})")

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
i10, i16 = int(np.argmin(abs(f - 10000))), int(np.argmin(abs(f - 16000)))


def ok(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


def disk(tag):
    return [relative_band_levels(np.array(analyze_spectrum(
        *load_audio(p))["band_power_db"]))
        for p in sorted(glob.glob(rf"D:\MusicVault\Tools\Shimmer\sources\{tag}-*.wav"))]


tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
sets = {
    "captured commercial": [np.array(t["rel_db"], float)
                            for t in lib["tracks"]
                            if ok(np.array(t["rel_db"], float))],
    "service masters": [np.array(t["rel_db"], float) for t in tone["tracks"]],
    "service (on disk)": disk("distrokid"),
    "Shimmer output": disk("shimmer"),
    "Suno render, raw": disk("suno"),
}

print()
print(f"{'':<22} {'n':>4} {'median':>8} {'p16':>7} {'p84':>7}  vs paper")
for name, cs in sets.items():
    v = np.array([invariant_slope(c) for c in cs])
    print(f"{name:<22} {len(v):4d} {np.median(v):8.2f} "
          f"{np.percentile(v,16):7.2f} {np.percentile(v,84):7.2f}  "
          f"{np.median(v)-PAPER:+.2f}")

t = invariant_slope(_REF_SHAPE_DB)
print(f"{'SHIPPED TARGET':<22} {'-':>4} {t:8.2f} {'-':>7} {'-':>7}  {t-PAPER:+.2f}")
