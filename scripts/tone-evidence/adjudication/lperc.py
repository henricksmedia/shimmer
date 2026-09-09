"""Where does Shimmer's material sit on the paper's percussion axis?

The genre objection only bites if our material really is far up the Lperc
distribution. Eq. 4 is RMS(percussive)/RMS(original) in dB. The paper's
HPSS is two-stage (STFT median filtering per FitzGerald, then a CQT stage);
only stage one is reproduced here, so treat the ABSOLUTE value as
uncalibrated -- what is meaningful is the ordering and the spread, plus a
sanity check that the numbers land inside the paper's -30..-5 dB range with
a mean near -15 (their Figure 1).
"""
import glob
import sys

import numpy as np
from scipy.ndimage import median_filter

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio

N, H, L = 4096, 2048, 17          # their STFT settings; FitzGerald's filter len


def lperc(x, sr):
    m = x.mean(axis=1) if x.ndim > 1 else x
    n = 1 + (len(m) - N) // H
    w = np.hanning(N)
    S = np.stack([np.fft.rfft(m[i * H:i * H + N] * w) for i in range(n)], 1)
    A = np.abs(S)
    Hh = median_filter(A, size=(1, L), mode="reflect")      # harmonic: smooth in time
    Pp = median_filter(A, size=(L, 1), mode="reflect")      # percussive: smooth in freq
    mask = Pp ** 2 / (Hh ** 2 + Pp ** 2 + 1e-20)
    # Parseval: RMS ratio can be read straight off the masked spectrogram
    num = float(np.sum((A * mask) ** 2))
    den = float(np.sum(A ** 2))
    return 10.0 * np.log10(num / den + 1e-20)


print(f"{'file':<40} {'Lperc (stage-1 only)':>21}")
out = {}
for tag in ("suno", "shimmer", "distrokid"):
    v = []
    for p in sorted(glob.glob(rf"D:\MusicVault\Tools\Shimmer\sources\{tag}-*.wav")):
        x, sr = load_audio(p)
        if x.shape[0] > sr * 120:
            x = x[:sr * 120]
        val = lperc(x, sr)
        v.append(val)
        print(f"{p.rsplit(chr(92),1)[-1][:39]:<40} {val:21.1f}")
    out[tag] = np.array(v)
print()
for k, v in out.items():
    print(f"{k:<12} n={len(v)}  mean {v.mean():6.1f}  min {v.min():6.1f}  "
          f"max {v.max():6.1f}")
print()
print("Paper Figure 1 / Table 2: corpus Lperc runs -30 to -5, mean about -15;")
print("group 6 (the corpus centre) is -15.3, group 11 (most percussive) -9.8.")
