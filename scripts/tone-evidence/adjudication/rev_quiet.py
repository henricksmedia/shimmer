"""Does a quiet passage read dark? The mechanism behind the two rejects.

The two rejected captures sit 9-19 dB below every keeper in recovered level.
If loud/quiet tracks with the 2.5-12.5 kHz level, then the rejects are faithful
recordings of quiet material, not broken chains -- and the gate is testing the
wrong thing.
"""
import glob
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import _REF_FREQS, analyze_spectrum, relative_band_levels

f = np.asarray(_REF_FREQS, float)
band = (f >= 2500) & (f <= 12500)
i10 = 25

lv, br, tk = [], [], []
for p in sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\distrokid-*.wav")):
    x, sr = load_audio(p)
    m = x.mean(axis=1) if x.ndim > 1 else x
    n = 30 * sr
    for s0 in range(0, max(1, len(m) - n), n):
        seg = np.ascontiguousarray(m[s0:s0 + n])
        if len(seg) < n // 2:
            continue
        bp = np.array(analyze_spectrum(seg, sr)["band_power_db"])
        c = relative_band_levels(bp)
        lv.append(20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12))
        br.append(c[band].mean())
        tk.append(c[i10])
lv, br, tk = np.array(lv), np.array(br), np.array(tk)
print(f"{len(lv)} 30-s windows from 8 masters")
print(f"window RMS dBFS: {lv.min():.1f} to {lv.max():.1f}")
print(f"corr(RMS, 2.5-12.5 kHz rel) = {np.corrcoef(lv, br)[0,1]:+.3f}")
print(f"corr(RMS, 10 kHz rel)       = {np.corrcoef(lv, tk)[0,1]:+.3f}")
q = lv <= np.percentile(lv, 20)
print(f"quietest 20% of windows: median brightness {np.median(br[q]):+.2f} dB, "
      f"10 kHz {np.median(tk[q]):+.2f}")
print(f"rest:                    median brightness {np.median(br[~q]):+.2f} dB, "
      f"10 kHz {np.median(tk[~q]):+.2f}")
print(f"slope: {np.polyfit(lv, br, 1)[0]:+.2f} dB of brightness per dB of level")
print(f"       {np.polyfit(lv, tk, 1)[0]:+.2f} dB at 10 kHz per dB of level")
print("\nExtrapolated to the rejects' deficit:")
for d in (9.2, 14.2, 19.0):
    print(f"  a passage {d:.0f} dB quieter would read "
          f"{np.polyfit(lv, tk, 1)[0]*d:+.1f} dB at 10 kHz")
print(f"\n(rejects read -43.6 and -50.6 at 10 kHz; keepers -3.7 to -17.0)")
