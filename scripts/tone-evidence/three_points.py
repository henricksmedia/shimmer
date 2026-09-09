"""Where does each thing actually sit?

The investigation began because Shimmer sounded dull next to the service's
masters, and the fix pointed Shimmer at the service's curve. The captured
commercial music now says that curve is bright. Those can all be true at
once, so put the three on one axis and look.
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
band = (f >= 2500) & (f <= 12500)
i10 = int(np.argmin(np.abs(f - 10000)))
i16 = int(np.argmin(np.abs(f - 16000)))


def curve(p):
    x, sr = load_audio(p)
    return relative_band_levels(np.array(analyze_spectrum(x, sr)["band_power_db"]))


def slope(c, lo, hi):
    m = (f >= lo) & (f <= hi)
    return float(np.polyfit(np.log2(f[m]), np.asarray(c, float)[m], 1)[0])


groups = {}
for tag in ("suno", "shimmer", "distrokid"):
    cs = [curve(p) for p in
          sorted(glob.glob(rf"D:\MusicVault\Tools\Shimmer\sources\{tag}-*.wav"))]
    groups[tag] = np.array(cs)

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
good = np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
                 if np.array(t["rel_db"], float)[i10] >= -29.1
                 and np.array(t["rel_db"], float)[i16] >= -40.1
                 and slope(np.array(t["rel_db"], float), 4000, 16000) >= -14.0])

rows = [
    ("Suno render (raw)", groups["suno"]),
    ("Shimmer output", groups["shimmer"]),
    ("Service master", groups["distrokid"]),
    ("Commercial (captured)", good),
]
print(f"{'':<24} {'n':>3} {'2.5-12.5k':>10} {'spread':>8} {'4-16k slope':>12}")
for name, arr in rows:
    v = arr[:, band].mean(axis=1)
    sl = [slope(c, 4000, 16000) for c in arr]
    print(f"{name:<24} {len(arr):3d} {np.median(v):10.2f} "
          f"{np.percentile(v,84)-np.percentile(v,16):8.2f} {np.median(sl):12.2f}")
print(f"{'SHIPPED TARGET':<24} {'-':>3} {_REF_SHAPE_DB[band].mean():10.2f} "
      f"{'-':>8} {slope(_REF_SHAPE_DB,4000,16000):12.2f}")

print()
print("Full curves, dB relative to the 200 Hz - 2 kHz median")
print(f"{'Hz':>7} {'Suno':>8} {'Shimmer':>8} {'Service':>8} {'TARGET':>8} "
      f"{'Commercl':>9}")
for i, hz in enumerate(f):
    if hz < 200 or hz > 20000:
        continue
    print(f"{hz:7.0f} {np.median(groups['suno'][:,i]):8.1f} "
          f"{np.median(groups['shimmer'][:,i]):8.1f} "
          f"{np.median(groups['distrokid'][:,i]):8.1f} "
          f"{_REF_SHAPE_DB[i]:8.1f} {np.median(good[:,i]):9.1f}")

v = good[:, band].mean(axis=1)
se = np.std(v, ddof=1) / np.sqrt(len(v))
gap = np.median(v) - _REF_SHAPE_DB[band].mean()
print()
print(f"commercial vs shipped target: {gap:+.2f} dB, "
      f"standard error {se:.2f} dB over n={len(v)}")
print(f"after the measured -1.35 dB excerpt bias: {gap+1.35:+.2f} dB")
