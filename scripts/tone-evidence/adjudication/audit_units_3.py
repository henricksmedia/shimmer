"""Part 3: my own numbers for the comparison, plus the two statistical
questions -- dB-mean vs dB-median, and the percussion cross-check that the
paper's own Sec 4.2 invariance makes possible.
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
BAND = (f >= 2500) & (f <= 12500)
MID = (f >= 200) & (f <= 2000)
A1, A2, A3 = -0.000907, 0.256, -32.942
B1, B2, B3 = -0.000183, 0.0213, -16.735
BWDB = 10.0 * np.log10(0.231563 * f)     # density -> 1/3-oct band power


def ltas_psd_db(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    return np.where(x < 100.0, A1*x*x + A2*x + A3, B1*x*x + B2*x + B3)


paper_raw = ltas_psd_db(f) + BWDB
paper = paper_raw - np.median(paper_raw[MID])
paper[(f < 30) | (f > 15719)] = np.nan


def curves(tag):
    out = []
    for p in sorted(glob.glob(rf"D:\MusicVault\Tools\Shimmer\sources\{tag}-*.wav")):
        x, sr = load_audio(p)
        out.append(relative_band_levels(
            np.asarray(analyze_spectrum(x, sr)["band_power_db"], float)))
    return np.array(out)


tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
svc309 = np.array([t["rel_db"] for t in tone["tracks"]], float)
neutral = np.array([t["rel_db"] for t in tone["tracks"]
                    if str(t.get("intensity", "")) + str(t.get("eq", ""))
                    or True], float)   # placeholder, refined below
cap15 = np.array([t["rel_db"] for t in lib["tracks"]], float)

i10, i16 = int(np.argmin(abs(f - 10000))), int(np.argmin(abs(f - 16000)))


def gate(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


cap13 = np.array([c for c in cap15 if gate(c)])
shim = curves("shimmer")
suno = curves("suno")
dk = curves("distrokid")

print("=" * 78)
print("A. Is the shipped target really the 309-master median?")
print("=" * 78)
neu = np.asarray(tone["neutral"]["median_db"], float)
print(f"  |_REF_SHAPE_DB - tone-reference 'neutral' (n=135) median| max "
      f"{np.abs(_REF_SHAPE_DB-neu).max():.3f} dB  -> it IS the n=135 neutral median")
print(f"  median of all 309 rows, 2.5-12.5 kHz mean : "
      f"{np.median(svc309, axis=0)[BAND].mean():+.2f} dB")
print(f"  SHIPPED TARGET  (n=135 neutral)           : "
      f"{_REF_SHAPE_DB[BAND].mean():+.2f} dB")
print("  The brief's '309 masters' and the file's '135' are different rows;")
print("  the shipped array is the 135. Not a unit error, but the 309 median is")
print("  0.7 dB darker, so quoting either interchangeably shifts the gap.")

print()
print("=" * 78)
print("B. My numbers. 2.5-12.5 kHz mean, dB re the 200 Hz-2 kHz median")
print("=" * 78)
sets = [("Elowsson fitted mean (paper)", None),
        ("captured commercial, 13", cap13),
        ("captured commercial, all 15", cap15),
        ("Shimmer output, 6", shim),
        ("Suno render raw, 8", suno),
        ("service on disk, 8", dk),
        ("service rows, 309", svc309),
        ("SHIPPED TARGET (135 neu)", _REF_SHAPE_DB[None, :])]
pv = np.nanmean(paper[BAND])
print(f"{'':<30} {'median-of-dB':>13} {'mean-of-dB':>11} {'delta':>7} "
      f"{'vs paper':>9}")
print(f"{'Elowsson fitted mean':<30} {pv:13.2f} {pv:11.2f} {0.0:7.2f} {0.0:9.2f}")
for name, arr in sets[1:]:
    med = np.median(arr, axis=0)[BAND].mean()
    mn = np.mean(arr, axis=0)[BAND].mean()
    print(f"{name:<30} {med:13.2f} {mn:11.2f} {mn-med:7.2f} {med-pv:9.2f}")

print()
print("  dB-mean vs dB-median: the paper's statistic is the MEAN of 10log10.")
print("  The deltas above are how much switching to their statistic moves each")
print("  corpus. They are small compared with the gap being argued about.")

print()
print("=" * 78)
print("C. Band-by-band, my grid")
print("=" * 78)
print(f"{'Hz':>7} {'paper':>8} {'TARGET':>8} {'svc309':>8} {'cap13':>8} "
      f"{'shim':>8} {'suno':>8}   {'TGT-paper':>9}")
for i, hz in enumerate(f):
    if hz < 63 or hz > 16000:
        continue
    p = paper[i]
    print(f"{hz:7.0f} {p:8.2f} {_REF_SHAPE_DB[i]:8.2f} "
          f"{np.median(svc309,axis=0)[i]:8.2f} {np.median(cap13,axis=0)[i]:8.2f} "
          f"{np.median(shim,axis=0)[i]:8.2f} {np.median(suno,axis=0)[i]:8.2f}   "
          f"{_REF_SHAPE_DB[i]-p:9.2f}")

print()
print("=" * 78)
print("D. 89 Hz - 4.5 kHz PSD slope (two-point, the paper's own method)")
print("=" * 78)


def psd_of(c):
    return np.asarray(c, float) - BWDB


def slope89(c):
    p = psd_of(c)
    m = np.isfinite(p)
    a, b = np.interp(np.log2([89.0, 4500.0]), np.log2(f[m]), p[m])
    return (b - a) / np.log2(4500.0 / 89.0)


# paper's own answer straight off Eq 5/6, no grid, no conversion
pap_slope = (ltas_psd_db(4500.) - ltas_psd_db(89.)) / np.log2(4500./89.)
print(f"  paper, straight from Eq5/Eq6            {pap_slope:+7.2f} dB/oct "
      f"(they report -4.53 measured off the curves)")
print(f"  paper's curve, round-tripped via my grid {slope89(paper):+7.2f} dB/oct "
      f"(grid + FFT-bin quantisation cost {slope89(paper)-pap_slope:+.2f})")
for name, arr in (("captured 13", cap13), ("service 309", svc309),
                  ("Shimmer out", shim), ("Suno raw", suno),
                  ("service disk", dk)):
    v = np.array([slope89(c) for c in arr])
    print(f"  {name:<38} {np.median(v):+7.2f}   p16 {np.percentile(v,16):+6.2f} "
          f"p84 {np.percentile(v,84):+6.2f}")
print(f"  {'SHIPPED TARGET':<38} {slope89(_REF_SHAPE_DB):+7.2f}")

print()
print("=" * 78)
print("E. The paper's OWN percussion correction, applied")
print("=" * 78)
print("""  Sec 4.2: for all 11 percussion groups the 89 Hz -> 4.5 kHz slope is the
  same. Slope equality between two corpora C and P means
      y_C(4500) - y_C(89)  =  y_P(4500) - y_P(89)
  and therefore
      y_C(4500) - y_P(4500)  =  y_C(89) - y_P(89).
  Offsets cancel, so this holds under any common normalisation. A corpus
  that is X dB above the paper mean at 89 Hz is PREDICTED to be X dB above
  it at 4.5 kHz, with no defect implied. Test it.""")


def at(c, hz):
    cc = np.asarray(c, float)
    m = np.isfinite(cc)
    return float(np.interp(np.log2(hz), np.log2(f[m]), cc[m]))


print()
print(f"{'':<26} {'89 Hz':>8} {'4.5 kHz':>9} {'predicted':>10} {'residual':>9}")
for name, arr in (("captured 13", np.median(cap13, axis=0)),
                  ("service 309", np.median(svc309, axis=0)),
                  ("Shimmer out", np.median(shim, axis=0)),
                  ("Suno raw", np.median(suno, axis=0)),
                  ("SHIPPED TARGET", _REF_SHAPE_DB)):
    d89 = at(arr, 89.) - at(paper, 89.)
    d45 = at(arr, 4500.) - at(paper, 4500.)
    print(f"{name:<26} {d89:+8.2f} {d45:+9.2f} {d89:+10.2f} {d45-d89:+9.2f}")
print("  (columns: excess over the paper at 89 Hz; excess at 4.5 kHz; what the")
print("   paper's invariance predicts the 4.5 kHz excess should be; what is left)")

print()
print("=" * 78)
print("F. How much of the 2.5-12.5 kHz gap survives the percussion correction?")
print("=" * 78)
for name, arr in (("captured 13", np.median(cap13, axis=0)),
                  ("service 309", np.median(svc309, axis=0)),
                  ("Shimmer out", np.median(shim, axis=0)),
                  ("SHIPPED TARGET", _REF_SHAPE_DB)):
    raw = np.asarray(arr, float)[BAND].mean() - pv
    d89 = at(arr, 89.) - at(paper, 89.)
    print(f"  {name:<24} raw gap {raw:+6.2f} dB, "
          f"bass-implied allowance {d89:+6.2f} dB, "
          f"unexplained {raw-d89:+6.2f} dB")
print("  NOTE the allowance is only argued to hold AT 4.5 kHz; above that the")
print("  paper gives no invariance, so this is an indication, not a correction.")
