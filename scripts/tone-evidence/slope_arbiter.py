"""Which curve looks like commercial music: the shipped tone target, or the
15 captured tracks?

Neither side of this argument is neutral. The target was built entirely from
one mastering service's output on AI renders; the captures came off Spotify
through a chain we only just validated. So judge both against a third party:
the published spectral-corpus slope for commercial popular music.

Pestana, Reiss & Barbosa, AES 135 (2013) fit the long-term average spectrum
of commercial masters as a power law. The comparable figure is the slope of
the power spectral DENSITY, in dB per octave, over the mid decade. A
1/3-octave band-power curve is not PSD: each band is 23.16% of its centre
frequency wide, so wider bands at the top collect more energy. Subtract the
bandwidth to get back to density before fitting anything against that
literature.
"""
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB

f = np.asarray(_REF_FREQS, dtype=float)


def psd(band_db):
    """1/3-octave band power (dB) -> power spectral density (dB/Hz)."""
    return np.asarray(band_db, float) - 10.0 * np.log10(0.2316 * f)


def slope(band_db, lo, hi):
    """dB per octave of the PSD across [lo, hi], least squares on log2 f."""
    m = (f >= lo) & (f <= hi)
    return float(np.polyfit(np.log2(f[m]), psd(band_db)[m], 1)[0])


lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
rows = np.array([t["rel_db"] for t in lib["tracks"]], dtype=float)
captured = np.median(rows, axis=0)

tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
service = np.median(np.array([t["rel_db"] for t in tone["tracks"]], float), axis=0)

curves = {
    "shipped target": np.asarray(_REF_SHAPE_DB, float),
    "service corpus (309)": service,
    "captured commercial (15)": captured,
}

print("PSD slope, dB/octave (Pestana et al. AES 135: commercial pop)")
print(f"{'curve':<26} {'100Hz-4k':>10} {'1k-10k':>10} {'2.5k-12.5k':>12}")
for name, c in curves.items():
    print(f"{name:<26} {slope(c,100,4000):10.2f} {slope(c,1000,10000):10.2f} "
          f"{slope(c,2500,12500):12.2f}")

print()
print(f"{'Hz':>7} {'shipped':>9} {'service':>9} {'captured':>9} {'cap-ship':>9}")
for i, hz in enumerate(f):
    if hz < 100 or hz > 20000:
        continue
    print(f"{hz:7.0f} {_REF_SHAPE_DB[i]:9.2f} {service[i]:9.2f} "
          f"{captured[i]:9.2f} {captured[i]-_REF_SHAPE_DB[i]:+9.2f}")

band = (f >= 2500) & (f <= 12500)
print()
print(f"captured - shipped, 2.5-12.5 kHz mean: "
      f"{np.mean(captured[band] - _REF_SHAPE_DB[band]):+.2f} dB")

# How much of the 15 agrees? A median hides whether this is 15 tracks saying
# the same thing or 3 outliers dragging it.
per = rows[:, band].mean(axis=1) - _REF_SHAPE_DB[band].mean()
print(f"per-track offsets: {np.sort(np.round(per,1))}")
print(f"{int((per < -4).sum())}/{len(per)} tracks are more than 4 dB darker")
