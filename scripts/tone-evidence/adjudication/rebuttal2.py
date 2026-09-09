import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

f = np.asarray(_REF_FREQS, float)
AIR = (f >= 2500) & (f <= 12500)
MID = (f >= 200) & (f <= 2000)
i10, i16 = int(np.argmin(abs(f - 10000))), int(np.argmin(abs(f - 16000)))
S = r"D:\MusicVault\Tools\Shimmer\sources"


def gate(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json",
                     encoding="utf-8"))
C = np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
              if gate(np.array(t["rel_db"], float))])
cm = np.median(C, axis=0)

BASS, MIDQ = (-0.000907, 0.256, -32.942), (-0.000183, 0.0213, -16.735)


def elow(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    a = np.where(x < 100, BASS[0], MIDQ[0])
    b = np.where(x < 100, BASS[1], MIDQ[1])
    c = np.where(x < 100, BASS[2], MIDQ[2])
    return a * x**2 + b * x + c + 10 * np.log10(0.2316 * np.asarray(hz, float))


E = elow(f)
E -= np.median(E[MID])
T = np.asarray(_REF_SHAPE_DB, float)
T -= np.median(T[MID])

print("A. REALISED BRIGHTENING: the six suno -> shimmer pairs that exist on disk")
print(f"{'track':<30} {'suno':>8} {'shimmer':>9} {'delta':>7}")
d = []
for p in sorted(glob.glob(os.path.join(S, "shimmer-*.wav"))):
    name = os.path.basename(p)[len("shimmer-"):-4]
    sp = os.path.join(S, f"suno-{name}.wav")
    if not os.path.exists(sp):
        continue
    a = relative_band_levels(np.array(
        analyze_spectrum(*load_audio(sp))["band_power_db"]))
    b = relative_band_levels(np.array(
        analyze_spectrum(*load_audio(p))["band_power_db"]))
    d.append((np.mean(a[AIR]), np.mean(b[AIR])))
    print(f"{name:<30} {d[-1][0]:8.2f} {d[-1][1]:9.2f} "
          f"{d[-1][1]-d[-1][0]:7.2f}")
d = np.array(d)
print(f"\n  median suno {np.median(d[:,0]):+.2f} -> median shimmer "
      f"{np.median(d[:,1]):+.2f};  the whole chain moves the air band "
      f"{np.median(d[:,1]-d[:,0]):+.2f} dB")
print(f"  captured commercial median {np.mean(cm[AIR]):+.2f} dB; "
      f"shimmer sits {np.median(d[:,1])-np.mean(cm[AIR]):+.2f} dB from it")

print()
print("B. WHOLE-SPECTRUM ERROR vs THE SAME 13 CAPTURES (not just the air band)")
band = np.isfinite(E) & (f >= 31.5) & (f <= 12500)
print(f"{'Hz':>7} {'capt':>7} {'target':>8} {'err':>6} {'Elowsson':>9} {'err':>6}")
for i, hz in enumerate(f):
    if not band[i]:
        continue
    print(f"{hz:7.0f} {cm[i]:7.1f} {T[i]:8.1f} {T[i]-cm[i]:6.1f} "
          f"{E[i]:9.1f} {E[i]-cm[i]:6.1f}")
for lo, hi, nm in ((31.5, 200, "31.5-200 Hz "), (200, 2000, "200 Hz-2 kHz"),
                   (2500, 12500, "2.5-12.5 kHz"), (31.5, 12500, "WHOLE 31.5-12.5k")):
    m = band & (f >= lo) & (f <= hi)
    print(f"  {nm:<18} rmse  target {np.sqrt(np.mean((T[m]-cm[m])**2)):5.2f} dB   "
          f"Elowsson {np.sqrt(np.mean((E[m]-cm[m])**2)):5.2f} dB")

print()
print("C. PER-BAND ENERGY MEAN minus dB MEAN (the paper averages in dB)")
tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json",
                      encoding="utf-8"))
A = np.array([t["rel_db"] for t in tone["tracks"]], float)
mdb = A.mean(axis=0) - np.median(A.mean(axis=0)[MID])
pwr = 10 * np.log10(np.mean(10 ** (A / 10), axis=0))
pwr -= np.median(pwr[MID])
for i, hz in enumerate(f):
    if hz in (1000., 2500., 4000., 6300., 10000., 12500.):
        print(f"  {hz:7.0f} Hz  sd {A[:,i].std():5.2f}   "
              f"energy-mean - dB-mean {pwr[i]-mdb[i]:+.2f} dB")
