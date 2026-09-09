"""Shimmer was accused of removing presence. Did that move the material
toward real music or away from it?

Per band: what the Suno source was, what Shimmer did to it, where it landed,
and where the three independent references say it should have landed.
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
BASS, MID = (-0.000907, 0.256, -32.942), (-0.000183, 0.0213, -16.735)


def elow_band():
    x = 1.0 + 60.0 * np.log2(f / 30.0)
    a = np.where(x < 100.0, BASS[0], MID[0])
    b = np.where(x < 100.0, BASS[1], MID[1])
    c = np.where(x < 100.0, BASS[2], MID[2])
    y = a * x ** 2 + b * x + c + 10.0 * np.log10(0.2316 * f)
    y = y - np.median(y[(f >= 200) & (f <= 2000)])
    y[(f < 31.5) | (f > 15700)] = np.nan
    return y


def disk(tag):
    return np.median(np.array([
        relative_band_levels(np.array(analyze_spectrum(
            *load_audio(p))["band_power_db"]))
        for p in sorted(glob.glob(
            rf"D:\MusicVault\Tools\Shimmer\sources\{tag}-*.wav"))]), axis=0)


i10 = int(np.argmin(abs(f - 10000)))
i16 = int(np.argmin(abs(f - 16000)))


def sl(c, lo, hi):
    m = (f >= lo) & (f <= hi)
    return float(np.polyfit(np.log2(f[m]), np.asarray(c, float)[m], 1)[0])


lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
cap = np.median(np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
                          if np.array(t["rel_db"], float)[i10] >= -29.1
                          and np.array(t["rel_db"], float)[i16] >= -40.1
                          and sl(np.array(t["rel_db"], float), 4000, 16000) >= -14.0]),
                axis=0)
suno, shim, serv = disk("suno"), disk("shimmer"), disk("distrokid")
paper = elow_band()

print("dB relative to the 200 Hz - 2 kHz median.")
print("'needed' = what the source would have to move to reach that reference.")
print("'did'    = what Shimmer actually moved it.")
print()
print(f"{'Hz':>7} {'Suno':>6} {'did':>6} {'landed':>7} | "
      f"{'cap':>6} {'needed':>7} {'err':>6} | {'paper':>6} {'needed':>7} {'err':>6}"
      f" | {'service':>7} {'needed':>7}")
for i, hz in enumerate(f):
    if hz < 500 or hz > 16000:
        continue
    did = shim[i] - suno[i]
    nc, np_ = cap[i] - suno[i], paper[i] - suno[i]
    print(f"{hz:7.0f} {suno[i]:6.1f} {did:+6.1f} {shim[i]:7.1f} | "
          f"{cap[i]:6.1f} {nc:+7.1f} {shim[i]-cap[i]:+6.1f} | "
          f"{paper[i]:6.1f} {np_:+7.1f} {shim[i]-paper[i]:+6.1f}"
          f" | {serv[i]:7.1f} {serv[i]-suno[i]:+7.1f}")

print()
for lo, hi, tag in ((2500, 12500, "2.5-12.5 kHz"), (4000, 10000, "4-10 kHz"),
                    (6300, 10000, "6.3-10 kHz")):
    m = (f >= lo) & (f <= hi)
    print(f"{tag:>14}  Suno {suno[m].mean():+6.2f}  Shimmer {shim[m].mean():+6.2f}"
          f"  captured {cap[m].mean():+6.2f}  paper {np.nanmean(paper[m]):+6.2f}"
          f"  service {serv[m].mean():+6.2f}  TARGET {_REF_SHAPE_DB[m].mean():+6.2f}")

print()
print("Distance from each reference, |mean error| over 2.5-12.5 kHz:")
m = (f >= 2500) & (f <= 12500)
for name, c in (("Suno raw", suno), ("Shimmer output", shim),
                ("Service master", serv), ("SHIPPED TARGET", _REF_SHAPE_DB)):
    c = np.asarray(c, float)
    print(f"  {name:<16} vs captured {c[m].mean()-cap[m].mean():+6.2f}"
          f"   vs paper {c[m].mean()-np.nanmean(paper[m]):+6.2f}")
