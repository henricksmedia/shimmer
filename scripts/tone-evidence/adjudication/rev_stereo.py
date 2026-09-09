"""The confound no chain validation can catch: mono summing.

Both paths mono-sum (mean of L,R) before the FFT. Out-of-phase high-frequency
content -- stereo reverb, widening, chorused synths -- cancels in that sum.
So a wide master measures darker than a narrow one carrying the same energy.

The corpus that defines the target is AI renders; the captures are heavily
widened commercial electronic. If their widths differ, part of the "gap" is
the measurement method, not the masters.

Measure the cost on the files that ARE on disk: mono sum vs the power average
of the two channels (what a width-blind analyser would see).
"""
import glob
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import _REF_FREQS, analyze_spectrum, relative_band_levels

f = np.asarray(_REF_FREQS, float)
band = (f >= 2500) & (f <= 12500)


def bp(x, sr):
    return np.array(analyze_spectrum(np.ascontiguousarray(x), sr)["band_power_db"])


print(f"{'file':<38} {'mono-sum loss, dB (+ = mono is darker)':>0}")
print(f"{'':<38} {'1k':>6} {'2.5k':>6} {'5k':>6} {'8k':>6} {'12.5k':>7} "
      f"{'2.5-12.5k rel':>14}")
for p in sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\*.wav")):
    x, sr = load_audio(p)
    if x.ndim < 2 or x.shape[1] < 2:
        print(f"{p.rsplit(chr(92),1)[-1][:37]:<38}  mono file")
        continue
    m = bp(x.mean(axis=1), sr)
    l, r = bp(x[:, 0], sr), bp(x[:, 1], sr)
    ch = 10 * np.log10((10 ** (l / 10) + 10 ** (r / 10)) / 2.0)
    d = ch - m                      # positive: mono sum lost energy
    dr = relative_band_levels(ch) - relative_band_levels(m)
    name = p.rsplit("\\", 1)[-1].replace(".wav", "")
    print(f"{name:<38} {d[15]:6.2f} {d[19]:6.2f} {d[22]:6.2f} {d[24]:6.2f} "
          f"{d[26]:7.2f} {dr[band].mean():14.2f}")
