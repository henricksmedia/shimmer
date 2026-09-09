"""Elowsson & Friberg's mean LTAS, on Shimmer's 1/3-octave grid.

AES 142nd Convention paper 9762 (2017), 12345 tracks. Section 3.2 fits the
smoothed mean LTAS with two quadratics over a log-frequency axis of 60 bins
per octave spanning 30 Hz - 15.7 kHz (543 bins), joined at bin 100 (94 Hz).

Their curve is power spectral DENSITY in dB. Shimmer's curves are 1/3-octave
band POWER. A third-octave band is 23.16% of its centre frequency wide, so
band power runs above density by 10*log10(0.2316*fc) and the gap grows with
frequency -- which is exactly the axis under dispute. Convert before
comparing or the answer is wrong by ~9 dB per decade.

Both are then normalised the way relative_band_levels does it, to the median
of the 200 Hz - 2 kHz bands, which removes level and leaves shape.
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

# --- their axis --------------------------------------------------------
BASS = (-0.000907, 0.256, -32.942)      # Eq. 5, bins 1-100
MID = (-0.000183, 0.0213, -16.735)      # Eq. 6, bins 100-543


def bin_of(hz):
    return 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)


def ltas_psd_db(hz):
    x = bin_of(hz)
    c = np.where(x < 100.0, 0, 1)
    out = np.empty_like(x, dtype=float)
    for k, (a, b, cc) in enumerate((BASS, MID)):
        m = c == k
        out[m] = a * x[m] ** 2 + b * x[m] + cc
    return out


def slope_db_oct(hz):
    """d(LTAS)/d(octave) from Eq. 7."""
    x = bin_of(hz)
    return 60.0 * (2.0 * MID[0] * x + MID[1])


print("Check against their Table 1:")
for hz, want in ((200, -2.350), (400, -3.668), (800, -4.985),
                 (1600, -6.303), (3200, -7.621), (6400, -8.938)):
    got = float(slope_db_oct(np.array([hz]))[0])
    print(f"  {hz:6.0f} Hz  paper {want:7.3f}   reproduced {got:7.3f}   "
          f"{'ok' if abs(got-want) < 0.005 else 'MISMATCH'}")

# --- onto Shimmer's grid ----------------------------------------------
VALID = (f >= 31.5) & (f <= 15700)      # their stated analysis range
elow_band = ltas_psd_db(f) + 10.0 * np.log10(0.2316 * f)   # density -> band power
mid = (f >= 200) & (f <= 2000)
elow_rel = elow_band - np.median(elow_band[mid])
elow_rel[~VALID] = np.nan

# --- everything else ---------------------------------------------------
i10 = int(np.argmin(np.abs(f - 10000)))
i16 = int(np.argmin(np.abs(f - 16000)))


def fit(c, lo, hi):
    m = (f >= lo) & (f <= hi) & np.isfinite(c)
    return float(np.polyfit(np.log2(f[m]),
                            np.asarray(c, float)[m]
                            - 10.0 * np.log10(0.2316 * f[m]), 1)[0])


lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))


def keep(t):
    c = np.array(t["rel_db"], float)
    m = (f >= 4000) & (f <= 16000)
    s = float(np.polyfit(np.log2(f[m]), c[m], 1)[0])
    return c[i10] >= -29.1 and c[i16] >= -40.1 and s >= -14.0


good = np.array([np.array(t["rel_db"], float) for t in lib["tracks"] if keep(t)])
tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
service = np.median(np.array([t["rel_db"] for t in tone["tracks"]], float), axis=0)
shim = np.median(np.array([relative_band_levels(np.array(
    analyze_spectrum(*load_audio(p))["band_power_db"]))
    for p in sorted(glob.glob(
        r"D:\MusicVault\Tools\Shimmer\sources\shimmer-*.wav"))]), axis=0)

cur = {"Elowsson 12345": elow_rel, "SHIPPED TARGET": np.asarray(_REF_SHAPE_DB, float),
       "service 309": service, "captured 13": np.median(good, axis=0),
       "Shimmer out": shim}

print()
print("PSD slope, dB/octave")
print(f"{'':<17} {'200-800':>9} {'800-3.2k':>9} {'1k-10k':>9} {'2.5k-12.5k':>11}")
for n, c in cur.items():
    print(f"{n:<17} {fit(c,200,800):9.2f} {fit(c,800,3200):9.2f} "
          f"{fit(c,1000,10000):9.2f} {fit(c,2500,12500):11.2f}")

print()
print("Shape, dB relative to the 200 Hz - 2 kHz median")
print(f"{'Hz':>7} " + " ".join(f"{n[:9]:>10}" for n in cur))
for i, hz in enumerate(f):
    if hz < 100 or hz > 16000:
        continue
    print(f"{hz:7.0f} " + " ".join(
        f"{c[i]:10.1f}" if np.isfinite(c[i]) else f"{'-':>10}" for c in cur.values()))

band = (f >= 2500) & (f <= 12500)
print()
print("2.5-12.5 kHz mean, and distance from the published corpus:")
e = np.nanmean(elow_rel[band])
for n, c in cur.items():
    print(f"  {n:<17} {np.nanmean(c[band]):7.2f}   {np.nanmean(c[band])-e:+7.2f} dB")
