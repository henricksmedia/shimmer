"""Part 4: the two claims in the conclusion, split apart."""
import glob, json, sys
import numpy as np
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

f = np.asarray(_REF_FREQS, float)
MID = (f >= 200) & (f <= 2000)
BWDB = 10.0 * np.log10(0.231563 * f)
A = (-0.000907, 0.256, -32.942); B = (-0.000183, 0.0213, -16.735)


def ltas(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    return np.where(x < 100, A[0]*x*x+A[1]*x+A[2], B[0]*x*x+B[1]*x+B[2])


pr = ltas(f) + BWDB
paper = pr - np.median(pr[MID])
paper[(f < 30) | (f > 15719)] = np.nan
d = _REF_SHAPE_DB - paper

print("Where the +10.95 dB actually lives (TARGET minus paper, per band):")
lo = (f >= 2500) & (f < 4500)
hi = (f >= 4500) & (f <= 12500)
print(f"  2.5-4.0 kHz  (BELOW the 4.5 kHz invariance limit): "
      f"{d[lo].mean():+6.2f} dB   bands {[int(v) for v in f[lo]]}")
print(f"  5.0-12.5 kHz (above it)                          : "
      f"{d[hi].mean():+6.2f} dB   bands {[int(v) for v in f[hi]]}")
print(f"  63-200 Hz    (the bass, never mentioned)         : "
      f"{d[(f>=63)&(f<=200)].mean():+6.2f} dB")
print(f"  250 Hz-2 kHz (the anchor region)                 : "
      f"{d[(f>=250)&(f<=2000)].mean():+6.2f} dB")
print()
print("  If the fix were 'flatten only above 4.5 kHz to meet the paper', the")
print(f"  2.5-12.5 kHz mean would land at "
      f"{np.concatenate([_REF_SHAPE_DB[lo], paper[hi]]).mean():+.2f} dB, still "
      f"{np.concatenate([_REF_SHAPE_DB[lo], paper[hi]]).mean()-np.nanmean(paper[(f>=2500)&(f<=12500)]):+.2f} "
      "above the paper.")

print()
print("Sensitivity of the two headline numbers to every unit choice I could")
print("plausibly get wrong:")
band = (f >= 2500) & (f <= 12500)
base = _REF_SHAPE_DB[band].mean() - np.nanmean(paper[band])
print(f"  as computed                                   gap {base:+7.2f} dB")
for lbl, k in (("bandwidth const 0.2316 not 0.231563", 0.2316),
               ("bandwidth const 0.23 (2 s.f.)", 0.23),
               ("bandwidth const 1.0 (i.e. dropped)", 1.0)):
    p2 = ltas(f) + 10*np.log10(k*f); p2 = p2 - np.median(p2[MID])
    p2[(f < 30) | (f > 15719)] = np.nan
    print(f"  {lbl:<45} {_REF_SHAPE_DB[band].mean()-np.nanmean(p2[band]):+7.2f} dB")
for lbl, mlo, mhi in (("anchor 200-2k (shipped)", 200, 2000),
                      ("anchor 300-3k", 300, 3000),
                      ("anchor 100-1k", 100, 1000),
                      ("anchor = 1 kHz band only", 900, 1100)):
    m2 = (f >= mlo) & (f <= mhi)
    p2 = pr - np.median(pr[m2]); p2[(f < 30) | (f > 15719)] = np.nan
    t2 = _REF_SHAPE_DB - np.median(_REF_SHAPE_DB[m2])
    print(f"  {lbl:<45} {t2[band].mean()-np.nanmean(p2[band]):+7.2f} dB")

print()
print("89 Hz - 4.5 kHz PSD slope, three ways, for the shipped target:")
p = _REF_SHAPE_DB - BWDB
a, b = np.interp(np.log2([89., 4500.]), np.log2(f), p)
print(f"  two-point secant (paper's method)            {(b-a)/np.log2(4500/89):+.3f}")
m = (f >= 89) & (f <= 4500)
print(f"  least-squares over the 1/3-oct bands inside  "
      f"{np.polyfit(np.log2(f[m]), p[m], 1)[0]:+.3f}   (bands "
      f"{int(f[m][0])}-{int(f[m][-1])} Hz, midpoint shifted)")
m2 = (f >= 80) & (f <= 5000)
print(f"  least-squares 80 Hz-5 kHz                    "
      f"{np.polyfit(np.log2(f[m2]), p[m2], 1)[0]:+.3f}")
pp = paper - BWDB
a2, b2 = np.interp(np.log2([89., 4500.]), np.log2(f), np.nan_to_num(pp, nan=0.0))
print(f"  reference values: paper Eq5/6 -4.463, paper on my grid "
      f"{(b2-a2)/np.log2(4500/89):+.3f}, paper as reported -4.53")
print(f"  1.4 dB accumulates over the 5.66 octaves at the 0.25 dB/oct gap")
print(f"  between -4.28 and -4.53; method spread on the reference alone is")
print(f"  0.12 dB/oct = 0.7 dB. So the slope agreement is good but not exact.")
