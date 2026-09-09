"""Independent cross-check of the two competing findings.

The original finding measured "tilt gap" = the 800 Hz -> 6.3 kHz DROP of one
curve minus the same drop of another. That is an endpoint-to-endpoint
difference-of-differences in dB, on relative_band_levels (1/3-oct band power,
normalised to the 200 Hz - 2 kHz median). Put every source on that exact
metric, then ask what the invariant-slope test can and cannot certify.
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


def elow_psd(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    a = np.where(x < 100.0, BASS[0], MID[0])
    b = np.where(x < 100.0, BASS[1], MID[1])
    c = np.where(x < 100.0, BASS[2], MID[2])
    return a * x ** 2 + b * x + c


def to_band(hz):
    return elow_psd(hz) + 10.0 * np.log10(0.2316 * np.asarray(hz, float))


elow = to_band(f)
mid = (f >= 200) & (f <= 2000)
elow = elow - np.median(elow[mid])
elow[(f < 31.5) | (f > 15700)] = np.nan


def curve(p):
    x, sr = load_audio(p)
    return relative_band_levels(np.array(analyze_spectrum(x, sr)["band_power_db"]))


def disk(tag):
    return np.array([curve(p) for p in sorted(glob.glob(
        rf"D:\MusicVault\Tools\Shimmer\sources\{tag}-*.wav"))])


i10 = int(np.argmin(abs(f - 10000)))
i16 = int(np.argmin(abs(f - 16000)))


def slope(c, lo, hi):
    m = (f >= lo) & (f <= hi)
    return float(np.polyfit(np.log2(f[m]), np.asarray(c, float)[m], 1)[0])


lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
good = np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
                 if np.array(t["rel_db"], float)[i10] >= -29.1
                 and np.array(t["rel_db"], float)[i16] >= -40.1
                 and slope(np.array(t["rel_db"], float), 4000, 16000) >= -14.0])
tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
serv309 = np.median(np.array([t["rel_db"] for t in tone["tracks"]], float), axis=0)

cur = {
    "Suno raw": np.median(disk("suno"), axis=0),
    "Shimmer (pre-fix)": np.median(disk("shimmer"), axis=0),
    "Service on disk": np.median(disk("distrokid"), axis=0),
    "Service 309": serv309,
    "SHIPPED TARGET": np.asarray(_REF_SHAPE_DB, float),
    "Captured 13": np.median(good, axis=0),
    "Elowsson paper": elow,
}


def at(c, hz):
    return float(np.interp(np.log2(hz), np.log2(f), np.asarray(c, float)))


print("=" * 78)
print("1. THE ORIGINAL FINDING'S OWN METRIC: 800 Hz -> 6.3 kHz drop, dB")
print("   (tilt gap between two sources = difference of these two numbers)")
print("=" * 78)
print(f"{'':<20} {'800Hz':>8} {'6.3kHz':>8} {'DROP':>8}   gap vs Shimmer(pre-fix)")
base = at(cur["Shimmer (pre-fix)"], 6300) - at(cur["Shimmer (pre-fix)"], 800)
for n, c in cur.items():
    d = at(c, 6300) - at(c, 800)
    print(f"{n:<20} {at(c,800):8.1f} {at(c,6300):8.1f} {d:8.2f}   {d-base:+8.2f}")

print()
print("=" * 78)
print("2. IS 800 Hz - 6.3 kHz INSIDE THE 89 Hz - 4.5 kHz INVARIANT RANGE?")
print("=" * 78)
print(f"   800 Hz - 4.5 kHz = {np.log2(4500/800):.3f} octaves  (inside)")
print(f"   4.5k  - 6.3 kHz  = {np.log2(6300/4500):.3f} octaves  (outside)")
print(f"   -> {100*np.log2(4500/800)/np.log2(6300/800):.1f}% of the log-width is inside")
print("   bands: 800,1k,1.25k,1.6k,2k,2.5k,3.15k,4k inside; 5k,6.3k outside "
      "(8 of 10)")

print()
print("=" * 78)
print("3. WHAT THE TWO-POINT INVARIANT SLOPE HIDES")
print("   Two-point slope over 89 Hz - 4.5 kHz says nothing about the shape")
print("   between the endpoints. Residual of each curve vs the paper, INSIDE")
print("   the invariant range, after removing the two-point slope and offset.")
print("=" * 78)


def psd(c):
    return np.asarray(c, float) - 10.0 * np.log10(0.2316 * f)


def two_pt(c, f1=89.0, f2=4500.0):
    p = psd(c)
    m = np.isfinite(p)
    a, b = np.interp(np.log2([f1, f2]), np.log2(f[m]), p[m])
    return (b - a) / np.log2(f2 / f1)


inr = (f >= 89) & (f <= 4500)
pp = psd(cur["Elowsson paper"])
print(f"{'':<20} {'2pt slope':>10} {'vs paper':>9} "
      f"{'max|resid|':>11} {'at Hz':>7} {'rms resid':>10}")
for n, c in cur.items():
    p = psd(c)
    # align to paper at 89 Hz and remove each curve's own two-point slope
    r = (p - p[inr][0]) - (pp - pp[inr][0])
    r = r[inr]
    k = int(np.argmax(np.abs(r)))
    print(f"{n:<20} {two_pt(c):10.2f} {two_pt(c)-two_pt(cur['Elowsson paper']):9.2f} "
          f"{r[k]:11.1f} {f[inr][k]:7.0f} {np.sqrt(np.mean(r**2)):10.2f}")

print()
print("=" * 78)
print("4. WHERE DOES THE TARGET'S INVARIANT SLOPE COME FROM?")
print("   Re-anchor the low end. If the target only passes because of its")
print("   bass shelf, moving x1 out of the bass will break it.")
print("=" * 78)
print(f"{'x1':>7} " + " ".join(f"{n[:9]:>10}" for n in cur))
for f1 in (89.0, 125.0, 200.0, 315.0, 500.0, 800.0):
    print(f"{f1:7.0f} " + " ".join(f"{two_pt(c, f1, 4500.0):10.2f}"
                                   for c in cur.values()))

print()
print("=" * 78)
print("5. PER-BAND ERROR OF THE SHIPPED TARGET, dB (target minus source)")
print("=" * 78)
print(f"{'Hz':>7} {'vs captured':>12} {'vs paper':>10} {'vs service309':>14}"
      f"   {'in 89-4.5k?':>12}")
for i, hz in enumerate(f):
    if hz < 200 or hz > 16000:
        continue
    t = _REF_SHAPE_DB[i]
    e = t - elow[i] if np.isfinite(elow[i]) else np.nan
    print(f"{hz:7.0f} {t-cur['Captured 13'][i]:12.1f} "
          f"{e:10.1f} {t-serv309[i]:14.1f}   "
          f"{'yes' if 89 <= hz <= 4500 else 'NO':>12}")

band = (f >= 2500) & (f <= 12500)
print()
print("=" * 78)
print("6. HEADLINE NUMBERS, RECOMPUTED")
print("=" * 78)
for n, c in cur.items():
    print(f"  {n:<20} 2.5-12.5k mean {np.nanmean(np.asarray(c,float)[band]):7.2f} dB"
          f"   89Hz-4.5k PSD slope {two_pt(c):6.2f}")
print()
print(f"  gap_2500_12500 (target - paper)    = "
      f"{np.nanmean(_REF_SHAPE_DB[band]) - np.nanmean(elow[band]):+.2f} dB")
print(f"  gap_2500_12500 (target - captured) = "
      f"{np.nanmean(_REF_SHAPE_DB[band]) - np.nanmean(cur['Captured 13'][band]):+.2f} dB")
print(f"  invariant_slope_target             = {two_pt(_REF_SHAPE_DB):.2f} dB/oct")
