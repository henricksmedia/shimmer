"""What does a real master's top end actually do?

Calling a captured curve "impossible" is an assertion until it is checked
against masters known to be real. 309 service masters plus 8 on disk give a
distribution for the high bands. Anything far outside it is not a quiet mix,
it is a broken capture.

The test deliberately does NOT ask whether a curve resembles the tone target
-- that would reject every capture that disagrees, which is the question
being asked. It asks only whether the roll-off is physically like music.
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
i10 = int(np.argmin(np.abs(f - 10000)))
i16 = int(np.argmin(np.abs(f - 16000)))
band = (f >= 2500) & (f <= 12500)

tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
known = [np.array(t["rel_db"], float) for t in tone["tracks"]]
for p in sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\distrokid-*.wav")):
    x, sr = load_audio(p)
    known.append(relative_band_levels(
        np.array(analyze_spectrum(x, sr)["band_power_db"])))
K = np.array(known)


def band_slope(c, lo, hi):
    m = (f >= lo) & (f <= hi)
    return float(np.polyfit(np.log2(f[m]), np.asarray(c, float)[m], 1)[0])


ks = np.array([band_slope(c, 4000, 16000) for c in K])
print(f"{len(K)} masters known to be real:")
for name, v in (("10 kHz", K[:, i10]), ("16 kHz", K[:, i16]),
                ("4-16k slope dB/oct", ks)):
    print(f"  {name:<20} min {v.min():7.1f}  p1 {np.percentile(v,1):7.1f}  "
          f"median {np.median(v):7.1f}  max {v.max():7.1f}")

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
lo10, lo16 = np.percentile(K[:, i10], 1), np.percentile(K[:, i16], 1)
loslope = np.percentile(ks, 1)
print()
print(f"gate (1st percentile of real masters): 10 kHz >= {lo10:.1f} dB, "
      f"16 kHz >= {lo16:.1f} dB, slope >= {loslope:.1f} dB/oct")
print()
print(f"{'capture':<40} {'10k':>7} {'16k':>7} {'slope':>7}  verdict")
keep = []
for t in sorted(lib["tracks"], key=lambda t: np.array(t["rel_db"], float)[i10]):
    c = np.array(t["rel_db"], float)
    s = band_slope(c, 4000, 16000)
    ok = c[i10] >= lo10 and c[i16] >= lo16 and s >= loslope
    print(f"{t['label'][:39]:<40} {c[i10]:7.1f} {c[i16]:7.1f} {s:7.1f}  "
          f"{'ok' if ok else 'REJECT'}")
    if ok:
        keep.append(c)

print()
tgt = _REF_SHAPE_DB[band].mean()
allc = np.median(np.array([np.array(t["rel_db"], float)
                           for t in lib["tracks"]]), axis=0)
print(f"all 15 captures      : {allc[band].mean()-tgt:+.2f} dB vs target")
if keep:
    kc = np.median(np.array(keep), axis=0)
    print(f"{len(keep)} that pass the gate : {kc[band].mean()-tgt:+.2f} dB vs target")
    print(f"  minus excerpt bias (-1.35 dB measured): "
          f"{kc[band].mean()-tgt+1.35:+.2f} dB")
