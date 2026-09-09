"""How much does a short excerpt lie about a master's tone?

The tone target was built from 90 s excerpts. The captured library holds
25-86 s fragments that begin wherever the listener pressed start, which in
practice is often an intro. Before treating the 8.4 dB gap as a fact about
music, measure how big an error that difference in method can produce on
files whose real curve is known.

Eight finished masters, on disk, measured whole; then the same masters
sampled the way the capture samples them.
"""
import glob
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

f = np.asarray(_REF_FREQS, float)
band = (f >= 2500) & (f <= 12500)


def curve(x, sr):
    return relative_band_levels(np.array(analyze_spectrum(x, sr)["band_power_db"]))


files = sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\distrokid-*.wav"))
print(f"{'master':<34} {'whole':>7} {'0-30s':>7} {'worst30':>8} {'spread':>7}")
allw, allb = [], []
for p in files:
    x, sr = load_audio(p)
    whole = curve(x, sr)[band].mean()
    n = int(30 * sr)
    offs = []
    for start in range(0, max(1, x.shape[0] - n), n):          # every 30 s window
        seg = np.ascontiguousarray(x[start:start + n])
        if seg.shape[0] < n // 2:
            continue
        offs.append(curve(seg, sr)[band].mean())
    offs = np.array(offs)
    name = p.rsplit("\\", 1)[-1].replace("distrokid-", "").replace(".wav", "")
    print(f"{name:<34} {whole:7.2f} {offs[0]:7.2f} {offs.min():8.2f} "
          f"{offs.max()-offs.min():7.2f}")
    allw.append(whole)
    allb.append(offs)

first = np.array([o[0] for o in allb])
worst = np.array([o.min() for o in allb])
whole = np.array(allw)
print()
print(f"opening 30 s vs whole master : mean {np.mean(first-whole):+.2f} dB, "
      f"worst {np.min(first-whole):+.2f} dB")
print(f"darkest 30 s vs whole master : mean {np.mean(worst-whole):+.2f} dB, "
      f"worst {np.min(worst-whole):+.2f} dB")
print(f"within-track spread across 30 s windows: "
      f"mean {np.mean([o.max()-o.min() for o in allb]):.2f} dB, "
      f"max {np.max([o.max()-o.min() for o in allb]):.2f} dB")
print()
print("These masters, measured whole, vs the shipped target:")
print(f"  mean {np.mean(whole) - _REF_SHAPE_DB[band].mean():+.2f} dB "
      f"across 2.5-12.5 kHz")
