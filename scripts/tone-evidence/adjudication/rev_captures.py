"""Independent re-check of the 15 loopback captures."""
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB, analyze_spectrum

f = np.asarray(_REF_FREQS, float)
band = (f >= 2500) & (f <= 12500)

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json",
                     encoding="utf-8"))
rows = lib["tracks"]
print(f"{len(rows)} captures\n")

# --- 1. the 40 Hz sentinel -------------------------------------------------
print("40 Hz band value in every capture (should be a real number):")
for t in rows:
    print(f"  {t['label'][:44]:<46} {t['rel_db'][1]:8.2f}")

# is it the -120 sentinel? band_power_db[1] == -120 exactly when no FFT bin
# lands inside 35.63-44.90 Hz.
sr = 48000
for nfft in (4096, 8192):
    fr = np.fft.rfftfreq(nfft, 1.0 / sr)
    lo, hi = 40 / 2 ** (1 / 6), 40 * 2 ** (1 / 6)
    n = int(((fr >= lo) & (fr <= hi)).sum())
    print(f"\nn_fft={nfft}: {n} FFT bins inside the 40 Hz third-octave "
          f"({lo:.2f}-{hi:.2f} Hz); bin spacing {sr/nfft:.3f} Hz")

x = np.random.randn(4096) * 0.1
sp = analyze_spectrum(x, sr)
print("white noise, one 4096 block, band_power_db[0:4] =",
      [round(v, 1) for v in sp["band_power_db"][:4]])

# --- 2. recover the absolute capture level from the sentinel ---------------
print("\nRecovered mid-band level  M = -120 - rel_db[40Hz]  (dB, unnormalised "
      "FFT power of one Hann-windowed 4096 block, averaged)")
print(f"{'track':<46} {'M dB':>8} {'~dBFS':>8} {'secs':>6} {'10k':>7} {'16k':>7} "
      f"{'2.5-12.5k':>10}")
# calibrate M -> dBFS with a full-scale-ish reference
cal = analyze_spectrum(np.random.randn(4096).astype(np.float64), sr)
# reference: sine at 1 kHz, amplitude 1.0 -> its band power in the same units
t = np.arange(4096) / sr
sine = np.sin(2 * np.pi * 1000 * t)
sp_s = analyze_spectrum(sine, sr)
ref_band = max(sp_s["band_power_db"])
print(f"(a 0 dBFS 1 kHz sine reads {ref_band:.1f} in these units)")
info = []
for t_ in rows:
    c = np.array(t_["rel_db"], float)
    M = -120.0 - c[1]
    info.append((t_["label"], M, t_.get("heard_seconds"), c))
for lab, M, s, c in sorted(info, key=lambda r: r[1]):
    print(f"{lab[:44]:<46} {M:8.2f} {M-ref_band:8.1f} {s:6.1f} "
          f"{c[25]:7.1f} {c[27]:7.1f} {c[band].mean():10.2f}")
