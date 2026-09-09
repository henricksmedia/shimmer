"""Part 2: end-to-end validation of the density -> band-power conversion.

Synthesise noise whose PSD IS the paper's fitted curve, push it through
Shimmer's own analyze_spectrum + relative_band_levels, and see whether the
analytic conversion 10*log10(0.2316*fc) recovers it. If the conversion is
right this closes the loop with no assumptions left.
"""
import sys
import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.mastering import _REF_FREQS, analyze_spectrum, relative_band_levels

f = np.asarray(_REF_FREQS, float)
A1, A2, A3 = -0.000907, 0.256, -32.942
B1, B2, B3 = -0.000183, 0.0213, -16.735


def ltas_psd_db(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    return np.where(x < 100.0, A1*x*x + A2*x + A3, B1*x*x + B2*x + B3)


sr = 44100
n = sr * 120
rng = np.random.default_rng(11)
W = np.fft.rfft(rng.standard_normal(n))
fr = np.fft.rfftfreq(n, 1.0 / sr)
g = np.zeros_like(fr)
m = (fr >= 20.0) & (fr <= 20000.0)
g[m] = 10.0 ** (ltas_psd_db(fr[m]) / 20.0)
sig = np.fft.irfft(W * g, n)

measured = relative_band_levels(np.asarray(
    analyze_spectrum(sig, sr)["band_power_db"], float))
predicted_raw = ltas_psd_db(f) + 10.0 * np.log10(0.231563 * f)
mid = (f >= 200) & (f <= 2000)
predicted = predicted_raw - np.median(predicted_raw[mid])

print("Noise built to have EXACTLY the paper's PSD, then measured by Shimmer.")
print(f"{'Hz':>7} {'measured':>10} {'predicted':>10} {'diff':>7}")
d = []
for i, hz in enumerate(f):
    if hz < 31.5 or hz > 15700:
        continue
    print(f"{hz:7.0f} {measured[i]:10.2f} {predicted[i]:10.2f} "
          f"{measured[i]-predicted[i]:+7.2f}")
    d.append(measured[i] - predicted[i])
d = np.array(d)
print(f"\n  mean |error| {np.abs(d).mean():.3f} dB   max {np.abs(d).max():.3f} dB")

band = (f >= 2500) & (f <= 12500)
print(f"  2.5-12.5 kHz mean: measured {measured[band].mean():+.2f}, "
      f"predicted {predicted[band].mean():+.2f}, "
      f"diff {measured[band].mean()-predicted[band].mean():+.3f} dB")

print("\n  Counterfactual: what if the conversion were OMITTED, or its sign flipped?")
none_ = ltas_psd_db(f); none_ = none_ - np.median(none_[mid])
flip = ltas_psd_db(f) - 10.0*np.log10(0.231563*f)
flip = flip - np.median(flip[mid])
print(f"    with conversion   2.5-12.5 kHz mean = {predicted[band].mean():+7.2f} dB")
print(f"    no conversion                       = {none_[band].mean():+7.2f} dB "
      f"({none_[band].mean()-predicted[band].mean():+.2f} vs correct)")
print(f"    conversion subtracted               = {flip[band].mean():+7.2f} dB "
      f"({flip[band].mean()-predicted[band].mean():+.2f} vs correct)")
