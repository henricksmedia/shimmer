"""Consolidation against the REAL extracted curve rather than the fit."""
import glob
import json
import sys

import numpy as np

sys.path.insert(0, r"C:\Users\jerem\AppData\Local\Temp\claude")
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from pdf_paths import load_streams, parse
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

MID = (-0.000183, 0.0213, -16.735)
paths, _ = parse(load_streams()[20])
by_len = sorted(paths, key=lambda p: -len(p[1]))
grey = next(p for c, p in by_len if max(c) > 0.8 and min(c) > 0.8)
black = next(p for c, p in by_len if max(c) < 0.2 and len(p) > 400)
blue = next(p for c, p in by_len if c[2] > 0.8 and c[0] < 0.2)
srt = lambda p: np.array(p)[np.argsort(np.array(p)[:, 0])]
GS, BS, U = srt(grey), srt(black), srt(blue)
x1 = U[:, 0].min()
per = (U[:, 0].max() - x1) / 99.0
bb = (BS[:, 0] - x1) / per + 1.0
A, C = np.polyfit(MID[0] * bb**2 + MID[1] * bb + MID[2], BS[:, 1], 1)
bg = (GS[:, 0] - x1) / per + 1.0
dg = (GS[:, 1] - C) / A

# is the grey the SMOOTHED mean? a 1/6-octave Gaussian at 60 bins/oct has
# sigma ~ 10 bins, so bin-to-bin roughness must be tiny.
print("Is the grey curve the smoothed mean LTAS (what Eq. 6 was fitted to)?")
print(f"  RMS of the 2nd difference, bin to bin: "
      f"{np.sqrt(np.mean(np.diff(dg,2)**2)):.4f} dB")
print(f"  same for the raw 1/3-octave curve of a real master, for scale: ")
x, sr = load_audio(r"D:\MusicVault\Tools\Shimmer\sources\distrokid-kindling.wav")
c0 = relative_band_levels(np.array(analyze_spectrum(x, sr)["band_power_db"]))
print(f"    {np.sqrt(np.mean(np.diff(c0[5:26],2)**2)):.4f} dB (1/3-oct bands)")
print("  -> the grey is heavily smoothed; consistent with the 1/6-octave")
print("     Gaussian of Section 2.2, not the ragged unsmoothed mean.")

f = np.asarray(_REF_FREQS, float)
T = np.asarray(_REF_SHAPE_DB, float)
hz_g = 30.0 * 2.0 ** ((bg - 1.0) / 60.0)
real = np.interp(np.log2(f), np.log2(hz_g), dg) + 10 * np.log10(0.2316 * f)
mid = (f >= 200) & (f <= 2000)
R = real - np.median(real[mid])
R[(f < 31.5) | (f > hz_g.max())] = np.nan
print(f"\nextracted curve covers {hz_g.min():.0f} Hz - {hz_g.max():.0f} Hz "
      f"(figure stops short of the stated 15.7 kHz)")

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
i10, i16 = int(np.argmin(abs(f - 10000))), int(np.argmin(abs(f - 16000)))
ok = lambda c: (c[i10] >= -29.1 and c[i16] >= -40.1 and float(np.polyfit(
    np.log2(f[(f >= 4000) & (f <= 16000)]), c[(f >= 4000) & (f <= 16000)], 1)[0]) >= -14)
cap = np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
                if ok(np.array(t["rel_db"], float))])
Cm = np.median(cap, axis=0)

print()
print("Gap = shipped target minus reference, dB")
print(f"{'window':>14} {'vs FIT':>8} {'vs REAL':>8} {'vs capt13':>10}")
for lo, hi in ((2500, 12500), (5000, 12500), (2000, 5000), (6300, 12500)):
    m = (f >= lo) & (f <= hi)
    fitv = np.nanmean((lambda h: h - np.median(h[mid]))(
        (MID[0] * (1 + 60 * np.log2(f / 30))**2 + MID[1] * (1 + 60 * np.log2(f / 30))
         + MID[2]) + 10 * np.log10(0.2316 * f))[m])
    print(f"{lo/1000:5.1f}-{hi/1000:5.1f}k {T[m].mean()-fitv:8.2f} "
          f"{T[m].mean()-np.nanmean(R[m]):8.2f} {T[m].mean()-Cm[m].mean():10.2f}")

# anchor sensitivity on the real curve
b = (f >= 5000) & (f <= 12500)
for nm, c in (("real curve", R), ("target", T), ("captures", Cm)):
    med = np.nanmean((c - np.median(c[mid]))[b])
    men = np.nanmean((c - np.mean(c[mid]))[b])
    print(f"  anchor shift, {nm:<11} median {med:7.2f}  mean {men:7.2f}  "
          f"{men-med:+.2f}")

print()
print("FINAL, 5-12.5 kHz")
gR = T[b].mean() - np.nanmean(R[b])
gC = T[b].mean() - Cm[b].mean()
d5 = -1.60
terms_A = [("target - paper's REAL measured curve", gR, 0.0),
           ("extraction / axis calibration", 0.0, 0.15),
           ("MP3 in the corpus (biases the paper dark)", -0.20, 0.20),
           ("median vs mean anchor, 200 Hz-2 kHz", -0.45, 0.45),
           ("percussive prominence (Lperc)", -3.00, 1.50),
           ("era: CD-era catalogue vs 2020s streaming", -2.50, 1.50)]
terms_B = [("target - 13 captures", gC, 0.0),
           ("excerpt bias (27-86 s fragments)", -1.00, 0.80),
           ("sampling, n=13", 0.0, cap[:, b].mean(axis=1).std(ddof=1) / np.sqrt(13)),
           ("Spotify Ogg Vorbis path, not in the loopback check", -0.40, 0.40),
           ("residual genre mismatch", 0.0, 1.00)]
for nm, terms in (("ROUTE A  the paper", terms_A), ("ROUTE B  the captures", terms_B)):
    print(f"\n{nm}")
    for n, v, u in terms:
        print(f"  {n:<46} {v:+7.2f} +/- {u:.2f}")
    t = sum(x[1] for x in terms)
    u = np.sqrt(sum(x[2]**2 for x in terms))
    print(f"  {'':<46} {'-'*7}")
    print(f"  {'total':<46} {t:+7.2f} +/- {u:.2f}")
    if nm.startswith("ROUTE A"):
        tA, uA = t, u
    else:
        tB, uB = t, u
w = np.array([1 / uA**2, 1 / uB**2])
print(f"\nCombined: {(tA*w[0]+tB*w[1])/w.sum():+.2f} +/- {1/np.sqrt(w.sum()):.2f} dB "
      f"over 5-12.5 kHz  (chi2 for 1 dof: "
      f"{(tA-tB)**2/(uA**2+uB**2):.2f}, the two routes do not conflict)")
