"""Error budget for the gap above 4.5 kHz, and where the divergence starts."""
import glob
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

f = np.asarray(_REF_FREQS, float)
T = np.asarray(_REF_SHAPE_DB, float)
BASS, MID = (-0.000907, 0.256, -32.942), (-0.000183, 0.0213, -16.735)


def elow(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    a = np.where(x < 100.0, BASS[0], MID[0])
    b = np.where(x < 100.0, BASS[1], MID[1])
    c = np.where(x < 100.0, BASS[2], MID[2])
    return a * x**2 + b * x + c + 10.0 * np.log10(0.2316 * np.asarray(hz, float))


mid = (f >= 200) & (f <= 2000)
E = elow(f) - np.median(elow(f)[mid])
E[(f < 31.5) | (f > 15700)] = np.nan

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
i10, i16 = int(np.argmin(abs(f - 10000))), int(np.argmin(abs(f - 16000)))
durs = {t["label"]: t.get("heard_seconds") for t in lib["tracks"]}


def ok(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


cap = np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
                if ok(np.array(t["rel_db"], float))])
kept = [t["label"] for t in lib["tracks"] if ok(np.array(t["rel_db"], float))]
print("capture lengths (s):", sorted(round(durs[k], 0) for k in kept))
print()

# ---- crossover ---------------------------------------------------------
C = np.median(cap, axis=0)
print("Where does the shipped target start running bright?")
print(f"{'Hz':>7} {'vs paper':>9} {'vs capt13':>10}")
for i, hz in enumerate(f):
    if hz < 500 or hz > 5000:
        continue
    print(f"{hz:7.0f} {T[i]-E[i]:9.1f} {T[i]-C[i]:10.1f}")


def cross(ref, thresh=2.0):
    d = T - ref
    m = np.isfinite(d) & (f >= 400) & (f <= 12500)
    return float(np.interp(thresh, d[m], np.log2(f[m])))


for nm, ref in (("paper", E), ("captures", C)):
    print(f"  target exceeds {nm} by 2 dB at "
          f"{2**cross(ref,2.0):.0f} Hz, by 4 dB at {2**cross(ref,4.0):.0f} Hz")

# ---- excerpt bias in the disputed window only --------------------------
print()
b25, b5 = (f >= 2500) & (f <= 12500), (f >= 5000) & (f <= 12500)
print("Excerpt bias, recomputed for 5-12.5 kHz (the window that matters):")
print(f"{'master':<32} {'whole':>7} {'0-30s':>7} {'0-60s':>7}")
d25, d5, d5_60 = [], [], []
for p in sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\distrokid-*.wav")):
    x, sr = load_audio(p)
    def cv(seg):
        return relative_band_levels(np.array(
            analyze_spectrum(np.ascontiguousarray(seg), sr)["band_power_db"]))
    w, a, b = cv(x), cv(x[:30 * sr]), cv(x[:60 * sr])
    d25.append(a[b25].mean() - w[b25].mean())
    d5.append(a[b5].mean() - w[b5].mean())
    d5_60.append(b[b5].mean() - w[b5].mean())
    print(f"{p.rsplit(chr(92),1)[-1][11:-4][:31]:<32} {w[b5].mean():7.2f} "
          f"{a[b5].mean():7.2f} {b[b5].mean():7.2f}")
d25, d5, d5_60 = np.array(d25), np.array(d5), np.array(d5_60)
print(f"  opening 30 s vs whole, 2.5-12.5k: {d25.mean():+.2f} dB "
      f"(sd {d25.std(ddof=1):.2f})")
print(f"  opening 30 s vs whole, 5-12.5k  : {d5.mean():+.2f} dB "
      f"(sd {d5.std(ddof=1):.2f}, se {d5.std(ddof=1)/np.sqrt(len(d5)):.2f})")
print(f"  opening 60 s vs whole, 5-12.5k  : {d5_60.mean():+.2f} dB "
      f"(sd {d5_60.std(ddof=1):.2f})")

# ---- the gap, per window, with sampling error --------------------------
print()
print("Gap = shipped target minus reference, dB")
print(f"{'window':>14} {'vs paper':>9} {'vs capt13':>10} {'capt se':>8} "
      f"{'capt corrected':>15}")
for lo, hi in ((2500, 12500), (5000, 12500), (5000, 10000), (6300, 12500)):
    m = (f >= lo) & (f <= hi)
    v = cap[:, m].mean(axis=1)
    se = v.std(ddof=1) / np.sqrt(len(v))
    bias = d5.mean() if lo >= 5000 else d25.mean()
    print(f"{lo/1000:5.1f}-{hi/1000:5.1f}k {T[m].mean()-np.nanmean(E[m]):9.2f} "
          f"{T[m].mean()-np.median(v):10.2f} {se:8.2f} "
          f"{T[m].mean()-np.median(v)+bias:15.2f}")

# ---- headline ----------------------------------------------------------
print()
m = (f >= 5000) & (f <= 12500)
gp = T[m].mean() - np.nanmean(E[m])
gc = T[m].mean() - np.median(cap[:, m].mean(axis=1))
print(f"5-12.5 kHz: target is {gp:+.2f} dB on the paper, {gc:+.2f} dB on the captures.")
print()
print("ROUTE A  paper, with every correction I can defend:")
terms = [("raw target - paper", gp, 0.0),
         ("quadratic misfit (4.5 kHz knee, both signs)", 0.0, 1.1),
         ("MP3 in the corpus (biases paper dark)", -0.20, 0.20),
         ("median vs mean anchor over 200 Hz-2 kHz", -0.45, 0.45),
         ("percussive prominence (Lperc), our material high", -3.0, 1.5),
         ("era: CD-era folk-rock vs 2020s streaming pop", -2.5, 1.5)]
tot = sum(t[1] for t in terms)
unc = np.sqrt(sum(t[2] ** 2 for t in terms))
for n, v, u in terms:
    print(f"  {n:<48} {v:+7.2f} +/- {u:.2f}")
print(f"  {'ROUTE A':<48} {tot:+7.2f} +/- {unc:.2f}")
print()
print("ROUTE B  the 13 captures, era- and genre-matched, validated chain:")
seB = cap[:, m].mean(axis=1).std(ddof=1) / np.sqrt(cap.shape[0])
terms = [("raw target - captures", gc, 0.0),
         ("excerpt bias (opening 30 s vs whole)", d5.mean(),
          abs(d5.std(ddof=1) / np.sqrt(len(d5)))),
         ("sampling, n=13", 0.0, seB),
         ("residual genre mismatch", 0.0, 1.0)]
totB = sum(t[1] for t in terms)
uncB = np.sqrt(sum(t[2] ** 2 for t in terms))
for n, v, u in terms:
    print(f"  {n:<48} {v:+7.2f} +/- {u:.2f}")
print(f"  {'ROUTE B':<48} {totB:+7.2f} +/- {uncB:.2f}")
print()
w = np.array([1 / unc**2, 1 / uncB**2])
comb = (tot * w[0] + totB * w[1]) / w.sum()
print(f"Inverse-variance combination: {comb:+.2f} +/- {1/np.sqrt(w.sum()):.2f} dB "
      "over 5-12.5 kHz")
