"""Independent re-check of the 'target is too bright' conclusion.

Everything here is recomputed from the raw data, not taken from the prior
scripts. Four questions:
  1. What is the per-track spread of the 13 captures, and where does
     Shimmer's actual output sit inside it?
  2. Where does the target/capture divergence actually begin?
  3. What does the target DO, after the +2/-3 dB caps? i.e. how much of the
     nominal excess can reach the audio at all?
  4. If you swapped the shipped target for Elowsson's curve, would the
     output land closer to, or further from, the captured commercial median?
"""
import glob
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
import shimmer.mastering as M
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               compute_tone_curve, relative_band_levels)

f = np.asarray(_REF_FREQS, float)
AIR = (f >= 2500) & (f <= 12500)
LIB = r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"
TONE = r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"
i10, i16 = int(np.argmin(abs(f - 10000))), int(np.argmin(abs(f - 16000)))


def gate(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


lib = json.load(open(LIB, encoding="utf-8"))
caps = [(t["label"], np.array(t["rel_db"], float), t.get("heard_seconds"))
        for t in lib["tracks"]]
good = [(n, c, s) for n, c, s in caps if gate(c)]
C = np.array([c for _, c, _ in good])

# Elowsson on the grid (same conversion the prior work used).
BASS, MID = (-0.000907, 0.256, -32.942), (-0.000183, 0.0213, -16.735)


def elow_band(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    a = np.where(x < 100, BASS[0], MID[0])
    b = np.where(x < 100, BASS[1], MID[1])
    c = np.where(x < 100, BASS[2], MID[2])
    return a * x ** 2 + b * x + c + 10.0 * np.log10(0.2316 * np.asarray(hz, float))


E = elow_band(f)
E = E - np.median(E[(f >= 200) & (f <= 2000)])
E[(f < 31.5) | (f > 15700)] = np.nan
T = np.asarray(_REF_SHAPE_DB, float)
T = T - np.median(T[(f >= 200) & (f <= 2000)])

print("=" * 74)
print("1. THE 13 CAPTURES, TRACK BY TRACK   (2.5-12.5 kHz mean, dB rel 200-2k)")
print("=" * 74)
v = np.array([np.mean(c[AIR]) for _, c, _ in good])
order = np.argsort(v)
for k in order:
    n, c, s = good[k]
    print(f"  {v[k]:7.2f}   {s:5.1f}s  {n[:46]}")
print(f"\n  n={len(v)}  mean {v.mean():.2f}  median {np.median(v):.2f}  "
      f"sd {v.std(ddof=1):.2f}  min {v.min():.2f}  max {v.max():.2f}")
se = v.std(ddof=1) / np.sqrt(len(v))
print(f"  standard error of the mean {se:.2f} dB -> 95% CI "
      f"[{v.mean()-1.96*se:.2f}, {v.mean()+1.96*se:.2f}]")
print(f"  full range spanned by 13 contemporary masters: {v.max()-v.min():.1f} dB")
SHIM_OUT = -6.53
print(f"\n  Shimmer's measured output ({SHIM_OUT:+.2f}) is brighter than "
      f"{int((v < SHIM_OUT).sum())}/{len(v)} of them "
      f"-> {100*(v < SHIM_OUT).mean():.0f}th percentile of this commercial sample")
print(f"  Elowsson's fitted mean (-11.75) is darker than "
      f"{int((v > -11.75).sum())}/{len(v)} of them")

print()
print("=" * 74)
print("2. WHERE THE DIVERGENCE ACTUALLY STARTS")
print("=" * 74)
cm = np.median(C, axis=0)
print(f"{'Hz':>7} {'target':>8} {'capt.med':>9} {'T-cap':>7} {'tol':>6} "
      f"{'sigmas':>7} {'Elowsson':>9} {'T-E':>7}")
for i, hz in enumerate(f):
    if hz < 630 or hz > 16000:
        continue
    tol = M._REF_TOL_DB[i]
    print(f"{hz:7.0f} {T[i]:8.1f} {cm[i]:9.1f} {T[i]-cm[i]:7.1f} {tol:6.1f} "
          f"{(T[i]-cm[i])/tol:7.2f} "
          f"{E[i]:9.1f} {T[i]-E[i]:7.1f}" if np.isfinite(E[i]) else
          f"{hz:7.0f} {T[i]:8.1f} {cm[i]:9.1f} {T[i]-cm[i]:7.1f} {tol:6.1f} "
          f"{(T[i]-cm[i])/tol:7.2f} {'-':>9} {'-':>7}")
lo = (f >= 1600) & (f <= 4000)
hi = (f >= 5000) & (f <= 12500)
print(f"\n  mean target-minus-capture, 1.6-4 kHz  (BELOW the claimed 4.5k line): "
      f"{np.mean(T[lo]-cm[lo]):+.2f} dB")
print(f"  mean target-minus-capture, 5-12.5 kHz (ABOVE it):                   "
      f"{np.mean(T[hi]-cm[hi]):+.2f} dB")

print()
print("=" * 74)
print("3. WHAT THE TARGET CAN ACTUALLY DO, AFTER THE CAPS")
print("=" * 74)
print(f"  _MAX_EQ_BOOST_DB = {M._MAX_EQ_BOOST_DB}   _MAX_EQ_CUT_DB = "
      f"{M._MAX_EQ_CUT_DB}   _HARSH_MAX_BOOST_DB = {M._HARSH_MAX_BOOST_DB}")
suno = sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\suno-*.wav"))
rows = []
for p in suno:
    x, sr = load_audio(p)
    spec = analyze_spectrum(x, sr)
    raw = np.array(spec["rel_db"], float)
    d_ship = np.array(compute_tone_curve(x, sr, strength=1.0, raw_spectrum=spec))
    nominal = T - raw
    rows.append((p.split("suno-")[1][:-4], raw, nominal, d_ship))

print(f"\n{'render':<30} {'raw air':>8} {'nominal':>9} {'realised':>9} "
      f"{'clipped':>9}")
for name, raw, nom, d in rows:
    print(f"{name:<30} {np.mean(raw[AIR]):8.2f} {np.mean(nom[AIR]):9.2f} "
          f"{np.mean(d[AIR]):9.2f} {np.mean(nom[AIR])-np.mean(d[AIR]):9.2f}")
nomv = np.array([np.mean(n[AIR]) for _, _, n, _ in rows])
relv = np.array([np.mean(d[AIR]) for _, _, _, d in rows])
print(f"\n  mean nominal air-band demand : {nomv.mean():+.2f} dB")
print(f"  mean air-band boost delivered: {relv.mean():+.2f} dB   "
      f"(hard ceiling {M._MAX_EQ_BOOST_DB:+.1f} dB per band)")
print(f"  the caps swallow {nomv.mean()-relv.mean():.2f} dB of the nominal demand")

print()
print("=" * 74)
print("4. SWAP THE TARGET FOR ELOWSSON'S CURVE AND RE-MASTER THE SAME RENDERS")
print("=" * 74)
Efill = np.where(np.isfinite(E), E, np.nan)
Efill[~np.isfinite(Efill)] = np.interp(
    np.log2(f[~np.isfinite(Efill)]),
    np.log2(f[np.isfinite(E)]), E[np.isfinite(E)])
saved = M._REF_DB.copy()
print(f"{'render':<30} {'ship out':>9} {'elow out':>9} "
      f"{'|ship-cap|':>11} {'|elow-cap|':>11}")
sd, ed = [], []
for name, raw, _, d_ship in rows:
    M._REF_DB = Efill - np.median(Efill[(f >= 200) & (f <= 2000)])
    x, sr = load_audio(
        rf"D:\MusicVault\Tools\Shimmer\sources\suno-{name}.wav")
    spec = analyze_spectrum(x, sr)
    d_elow = np.array(compute_tone_curve(x, sr, strength=1.0, raw_spectrum=spec))
    M._REF_DB = saved
    out_s, out_e = raw + d_ship, raw + d_elow
    out_s = out_s - np.median(out_s[(f >= 200) & (f <= 2000)])
    out_e = out_e - np.median(out_e[(f >= 200) & (f <= 2000)])
    a, b = np.mean(out_s[AIR]), np.mean(out_e[AIR])
    sd.append(abs(a - np.mean(cm[AIR])))
    ed.append(abs(b - np.mean(cm[AIR])))
    print(f"{name:<30} {a:9.2f} {b:9.2f} {sd[-1]:11.2f} {ed[-1]:11.2f}")
M._REF_DB = saved
print(f"\n  captured commercial median over 2.5-12.5 kHz: "
      f"{np.mean(cm[AIR]):+.2f} dB")
print(f"  mean |error| vs that median, shipped target : {np.mean(sd):.2f} dB")
print(f"  mean |error| vs that median, Elowsson target: {np.mean(ed):.2f} dB")

print()
print("=" * 74)
print("5. ESTIMATOR: MEAN-OF-dB (what the paper averages) vs ENERGY MEAN")
print("=" * 74)
tone = json.load(open(TONE, encoding="utf-8"))
S = np.array([t["rel_db"] for t in tone["tracks"]], float)
for nm, A in (("service 309", S), ("captures 13", C)):
    mdb = A.mean(axis=0)
    pwr = 10 * np.log10(np.mean(10 ** (A / 10), axis=0))
    mdb -= np.median(mdb[(f >= 200) & (f <= 2000)])
    pwr -= np.median(pwr[(f >= 200) & (f <= 2000)])
    print(f"  {nm}: between-track sd at 1k={A[:, 15].std():.1f} "
          f"4k={A[:, 21].std():.1f} 10k={A[:, 25].std():.1f} dB;  "
          f"energy-mean minus dB-mean over 2.5-12.5 kHz = "
          f"{np.mean(pwr[AIR]-mdb[AIR]):+.2f} dB")
print("  (the paper builds its curve as mean of 10*log10 per track, Sec 2.2)")
