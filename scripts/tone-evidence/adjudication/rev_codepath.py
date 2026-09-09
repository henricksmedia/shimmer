"""Does the capture CODE PATH itself bias the top end?

The loopback validation (0.28 dB) tested audio-chain + code together, once.
This isolates the code: take a file whose curve is known, run it through the
exact accumulation references._run performs (4096-sample non-overlapping
blocks, one Hann-windowed 4096-pt FFT each, -60 dBFS RMS gate, linear band
power summed, then relative_band_levels) and compare with the whole-file
8192-pt / 75%-overlap analysis the reference corpus used.
"""
import glob
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, analyze_spectrum,
                               relative_band_levels)

f = np.asarray(_REF_FREQS, float)
band = (f >= 2500) & (f <= 12500)
BLOCK, SILENCE = 4096, -60.0


def capture_style(x, sr, limit_s=None):
    """Exactly what references._run accumulates."""
    mono = x.mean(axis=1) if x.ndim > 1 else x
    if limit_s:
        mono = mono[:int(limit_s * sr)]
    acc, n, heard = None, 0, 0.0
    for s0 in range(0, len(mono) - BLOCK + 1, BLOCK):
        blk = np.ascontiguousarray(mono[s0:s0 + BLOCK])
        rms = float(np.sqrt(np.mean(blk ** 2)))
        if rms <= 10.0 ** (SILENCE / 20.0):
            continue
        bp = np.array(analyze_spectrum(blk, sr)["band_power_db"])
        lin = 10.0 ** (bp / 10.0)
        acc = lin if acc is None else acc + lin
        n += 1
        heard += BLOCK / sr
    return relative_band_levels(10.0 * np.log10(np.maximum(acc / n, 1e-20))), heard


def whole(x, sr, limit_s=None):
    mono = x.mean(axis=1) if x.ndim > 1 else x
    if limit_s:
        mono = mono[:int(limit_s * sr)]
    return relative_band_levels(
        np.array(analyze_spectrum(np.ascontiguousarray(mono), sr)["band_power_db"]))


files = sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\*.wav"))
print(f"{'file':<38} {'whole':>7} {'capstyle':>9} {'delta':>7}   "
      f"{'d@5k':>6} {'d@8k':>6} {'d@10k':>6} {'d@12.5k':>8} {'d@16k':>7}")
deltas, per_band = [], []
for p in files:
    x, sr = load_audio(p)
    w = whole(x, sr)
    c, _ = capture_style(x, sr)
    d = c - w
    deltas.append(c[band].mean() - w[band].mean())
    per_band.append(d)
    name = p.rsplit("\\", 1)[-1].replace(".wav", "")
    print(f"{name:<38} {w[band].mean():7.2f} {c[band].mean():9.2f} "
          f"{deltas[-1]:7.2f}   {d[22]:6.2f} {d[24]:6.2f} {d[25]:6.2f} "
          f"{d[26]:8.2f} {d[27]:7.2f}")
D = np.array(per_band)
print(f"\ncode-path bias, 2.5-12.5 kHz mean: {np.mean(deltas):+.3f} dB "
      f"(min {np.min(deltas):+.3f}, max {np.max(deltas):+.3f}, n={len(deltas)})")
print("per-band mean bias (capture code minus file code):")
for i, hz in enumerate(f):
    if hz < 100 or hz > 20000:
        continue
    print(f"  {hz:7.0f} {D[:, i].mean():+7.2f}")
