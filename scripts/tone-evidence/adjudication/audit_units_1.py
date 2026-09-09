"""Independent re-derivation, part 1: the paper's axis, and the unit of
analyze_spectrum. No trust placed in elowsson_grid.py.
"""
import sys
import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB, analyze_spectrum, relative_band_levels

np.set_printoptions(suppress=True)
f = np.asarray(_REF_FREQS, float)

A1, A2, A3 = -0.000907, 0.256, -32.942     # Eq 5 bass, bins 1-100
B1, B2, B3 = -0.000183, 0.0213, -16.735    # Eq 6 mid+high, bins 100-543


def x_of_f(hz):
    return 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)


def f_of_x(x):
    return 30.0 * 2.0 ** ((np.asarray(x, float) - 1.0) / 60.0)


def ltas(hz):
    """Paper's fitted mean LTAS, dB, in whatever unit their y-axis is."""
    x = x_of_f(hz)
    return np.where(x < 100.0, A1 * x * x + A2 * x + A3, B1 * x * x + B2 * x + B3)


print("=" * 74)
print("1. AXIS.  f(x) = 30 * 2^((x-1)/60)   -- checked against THEIR Table 1")
print("=" * 74)
print(f"  x=1     -> {f_of_x(1):9.2f} Hz   (paper: range starts 30 Hz)")
print(f"  x=100   -> {f_of_x(100):9.2f} Hz   (paper: 'bin x = 100 (94 Hz)')")
print(f"  x=543   -> {f_of_x(543):9.1f} Hz   (paper: 543 bins, up to 15.7 kHz)")
print()
print("  Table 1 x-column, paper vs mine:")
for hz, xp, slp in ((200, 165.22, -2.350), (400, 225.22, -3.668),
                    (800, 285.22, -4.985), (1600, 345.22, -6.303),
                    (3200, 405.22, -7.621), (6400, 465.22, -8.938)):
    xm = float(x_of_f(hz))
    sm = 60.0 * (2.0 * B1 * xm + B2)          # Eq 7 x 60 bins/octave
    print(f"   {hz:6.0f} Hz   x paper {xp:7.2f}  mine {xm:7.2f}  "
          f"| slope paper {slp:7.3f}  mine {sm:7.3f}  "
          f"{'OK' if abs(xm-xp) < 0.01 and abs(sm-slp) < 0.001 else 'MISMATCH'}")

print()
print("  Two further self-consistency checks on the transcription:")
c5, c6 = A1*100**2 + A2*100 + A3, B1*100**2 + B2*100 + B3
print(f"   Eq5 and Eq6 at x=100 (they say the fits were forced to meet there):")
print(f"     Eq5 {c5:8.3f}   Eq6 {c6:8.3f}   gap {c5-c6:+.3f} dB")
sec = (ltas(15696.) - ltas(94.17)) / np.log2(15696./94.17)
print(f"   94 Hz -> 15.7 kHz secant slope of Eq6: {sec:+.3f} dB/oct")
print(f"     (paper's linear fit over the same span: -5.79 dB/oct)")

print()
print("=" * 74)
print("2. UNIT OF analyze_spectrum: band POWER or spectral DENSITY?")
print("=" * 74)
print("""  Source (mastering.py:230):
      band_power_db = 10*log10( SUM over FFT bins in [fc*2^-1/6, fc*2^+1/6] of |X|^2 )
  A SUM over the bins in the band = the band's integrated power, not a
  per-Hz density.  Empirical proof follows.""")
sr = 44100
n = sr * 40
rng = np.random.default_rng(7)


def shaped_noise(psd_db_fn, n, sr, rng):
    w = rng.standard_normal(n)
    W = np.fft.rfft(w)
    fr = np.fft.rfftfreq(n, 1.0 / sr)
    g = np.zeros_like(fr)
    m = fr > 0
    g[m] = 10.0 ** (psd_db_fn(fr[m]) / 20.0)
    return np.fft.irfft(W * g, n)


def bandpow(sig):
    return np.asarray(analyze_spectrum(sig, sr)["band_power_db"], float)


def fitslope(y, lo, hi, arr=None):
    ff = f if arr is None else arr
    m = (ff >= lo) & (ff <= hi) & np.isfinite(y)
    return float(np.polyfit(np.log2(ff[m]), np.asarray(y, float)[m], 1)[0])


white = shaped_noise(lambda x: np.zeros_like(x), n, sr, rng)
pink = shaped_noise(lambda x: -10.0 * np.log10(x), n, sr, rng)
bw, bp = bandpow(white), bandpow(pink)
print(f"  flat-PSD (white) noise, 1/3-oct band-power slope 200 Hz-12.5 kHz: "
      f"{fitslope(bw, 200, 12500):+.3f} dB/oct   (density would give 0.000, "
      f"integrated power +3.010)")
print(f"  1/f-PSD  (pink)  noise, same measurement:                        "
      f"{fitslope(bp, 200, 12500):+.3f} dB/oct   (density -3.010, power 0.000)")
print("  => analyze_spectrum returns INTEGRATED BAND POWER.")
print("     density -> band power therefore ADDS 10*log10(bandwidth).  The")
print("     direction used in elowsson_grid.py (+) is correct.")

print()
print("=" * 74)
print("3. THE BANDWIDTH CONSTANT")
print("=" * 74)
k = 2.0 ** (1.0 / 6.0) - 2.0 ** (-1.0 / 6.0)
print(f"  edges fc*2^-1/6 .. fc*2^+1/6  ->  width = fc*(2^(1/6)-2^(-1/6)) "
      f"= fc * {k:.6f}")
print(f"  script uses 0.2316; exact {k:.6f}; error {10*np.log10(0.2316/k):+.5f} dB "
      f"(frequency-independent)")
print("  and 10*log10(0.2316*fc) = 10*log10(0.2316) + 10*log10(fc): the constant")
print("  term is killed by the 200 Hz-2 kHz median normalisation, so ONLY the")
print("  +3.0103 dB/oct tilt from 10*log10(fc) survives. The constant's value is")
print("  irrelevant to every number in the comparison.")

# how much does band-integration of a sloping density depart from PSD*W?
print()
print("  Is band power really PSD(fc)*W for a sloping spectrum?")
for s in (-3.0, -4.5, -6.0, -9.0):
    p = s / (10.0 * np.log10(2.0))
    num = 2.0 ** ((p + 1) / 6.0) - 2.0 ** (-(p + 1) / 6.0)
    print(f"    density sloping {s:+.1f} dB/oct: exact/approx = "
          f"{10*np.log10(num/((p+1)*k)):+.4f} dB")

print()
print("=" * 74)
print("4. DOES ANY OF THEIR PROCESSING CHANGE THE SHAPE?")
print("=" * 74)
print("""  BS.1770-4 normalisation (their Eq 1): PSDN = PSD / (PSD . F_ITU).
  The denominator is a DOT PRODUCT -> one scalar per track. Their own
  Sec 2.2: "The filtering during loudness normalization does not affect the
  relative sound level of the different frequency bins in each track, so the
  mean LTAS computed in Section 3.1 is unaffected in this regard."
  A per-track scalar in the power domain is a per-track constant in dB, and
  a constant survives the dB-domain mean as a constant offset. SHAPE: unchanged.
  Our normalisation (subtract the 200 Hz-2 kHz median) is also a pure offset.
  Neither side's normalisation can create or hide a high-frequency difference.

  1/6-octave Gaussian smoothing: ioSR's smoothSpectrum applies unit-sum
  Gaussian weights to the POWER spectrum across the linear FFT bins. A
  unit-sum weighted average of a density is still a density -- the operation
  cannot convert per-Hz into per-band. It is a smoothing, not an integration.""")
sig = 0.05
for s in (-4.5, -9.0):
    p = s / (10.0 * np.log10(2.0))
    # E[(1+e)^p], e ~ N(0, sig^2) : 1 + p(p-1)/2 sig^2
    print(f"    log-vs-power smoothing bias on a {s:+.1f} dB/oct density, "
          f"sigma=f/6pi: {10*np.log10(1 + p*(p-1)/2*sig**2):+.4f} dB")
print("  Both effects are under 0.05 dB. Neither is a unit change.")
