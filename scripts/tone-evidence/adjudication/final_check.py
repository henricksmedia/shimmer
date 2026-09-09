import glob, json, sys
import numpy as np
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)
f3 = np.asarray(_REF_FREQS, float)
AIR = (f3 >= 2500) & (f3 <= 12500)
i10, i16 = int(np.argmin(abs(f3-10000))), int(np.argmin(abs(f3-16000)))
lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
def keep(c):
    m = (f3>=4000)&(f3<=16000)
    return c[i10]>=-29.1 and c[i16]>=-40.1 and float(np.polyfit(np.log2(f3[m]),c[m],1)[0])>=-14.0
cap = np.array([np.array(t["rel_db"],float) for t in lib["tracks"] if keep(np.array(t["rel_db"],float))])
svc = np.array([t["rel_db"] for t in tone["tracks"]], float)

print("captures' low end (median, dB rel 200Hz-2kHz median):")
for i,hz in enumerate(f3):
    if hz<=200: print(f"  {hz:6.1f} {np.median(cap[:,i]):7.2f}   target {_REF_SHAPE_DB[i]:7.2f}")

# Broadband PSD slope 94 Hz - 15.7 kHz: paper's own linear fit = 5.79 dB/oct
def psd_slope(c, lo, hi):
    p = np.asarray(c,float) - 10*np.log10(0.2316*f3)
    m = (f3>=lo)&(f3<=hi)
    return float(np.polyfit(np.log2(f3[m]), p[m], 1)[0])
print()
print("Broadband PSD slope 94 Hz - 15.7 kHz (paper's own linear fit: -5.79;")
print("Pestana et al. 772 commercial recordings, cited by the paper: ~ -5)")
for n, arr in (("captured 13", cap), ("service 309", svc)):
    v = np.array([psd_slope(c,94,15700) for c in arr])
    print(f"  {n:<16} median {np.median(v):+.2f}  p16 {np.percentile(v,16):+.2f}"
          f"  p84 {np.percentile(v,84):+.2f}")
print(f"  {'SHIPPED TARGET':<16} {psd_slope(_REF_SHAPE_DB,94,15700):+.2f}")

print()
print("Spread of individual masters around their own corpus median, 2.5-12.5k:")
for n, arr in (("captured 13", cap), ("service 309", svc)):
    v = arr[:,AIR].mean(axis=1)
    print(f"  {n:<16} median {np.median(v):+.2f}  SD {np.std(v,ddof=1):.2f}"
          f"  min {v.min():+.2f}  max {v.max():+.2f}  SE {np.std(v,ddof=1)/np.sqrt(len(v)):.2f}")
v = cap[:,AIR].mean(axis=1)
t = _REF_SHAPE_DB[AIR].mean()
print(f"  target {t:+.2f} -> sits above ALL {int((v<t).sum())}/{len(v)} captures;"
      f"  gap in SEs: {(t-np.median(v))/(np.std(v,ddof=1)/np.sqrt(len(v))):.1f}")
print(f"  brightest single capture {v.max():+.2f} dB, still {t-v.max():+.2f} below target")
