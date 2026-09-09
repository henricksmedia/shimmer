"""What does the new target ask for, and where do the caps bind?

The caps must be set from what real corrections need, not chosen. Runs the
tone curve on every source in the corpus with the caps lifted, and reports
what the curve WANTS before clipping — so we can see how often each cap binds
and by how much.
"""
import glob
import os
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer import mastering as M
from shimmer.audio_io import load_audio

SRC = glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\suno-*.wav")
SHOW = [100, 400, 1000, 2500, 4000, 6300, 8000, 10000, 12500]
IDX = [int(np.argmin(np.abs(M._REF_FREQS - f))) for f in SHOW]

# Temporarily lift every cap so we see the raw ask.
M._MAX_EQ_BOOST_DB = 99.0
M._MAX_EQ_CUT_DB = 99.0
M._HARSH_MAX_BOOST_DB = 99.0

print("Raw correction the new target asks for, med strength (0.55), no caps")
print(f"{'track':30s}" + "".join(f"{f/1000:>8.1f}k" for f in SHOW))
rows = []
for p in sorted(SRC):
    x, sr = load_audio(p)
    c = np.array(M.compute_tone_curve(x, sr, strength=0.55, tilt="neutral"))
    rows.append(c)
    print(f"{os.path.basename(p)[5:35]:30s}"
          + "".join(f"{c[i]:9.2f}" for i in IDX))

a = np.array(rows)
print()
print("Across the corpus:")
print(f"{'band':>8} {'min':>7} {'median':>7} {'max':>7}")
for j, f in enumerate(SHOW):
    col = a[:, IDX[j]]
    print(f"{f:8.0f} {col.min():7.2f} {np.median(col):7.2f} {col.max():7.2f}")

harsh = (M._REF_FREQS >= 5000) & (M._REF_FREQS <= 12000)
hb = a[:, harsh]
print()
print("=== Where the 5-12 kHz boost guard would bind ===")
print(f"  largest boost the target asks for there : {hb.max():+.2f} dB")
print(f"  share of bands asking for > +0.5 dB     : {100.0*np.mean(hb > 0.5):.0f}%")
print(f"  share asking for > +2.0 dB              : {100.0*np.mean(hb > 2.0):.0f}%")
print()
print("=== Overall boost/cut range asked for ===")
print(f"  max boost anywhere : {a.max():+.2f} dB")
print(f"  max cut anywhere   : {a.min():+.2f} dB")
