"""Recover the paper's actual mean LTAS, not its quadratic approximation.

The whole dispute is about what commercial music does above 4.5 kHz, and so
far that has been answered with a single quadratic fitted across seven
octaves. Fits are least trustworthy at their ends, which is exactly where the
argument sits.

Figure 5 of the paper plots the fittings over the mean LTAS, and the figure
is vector art, so both curves are in the file as polylines. The fitted curve
has a known closed form (Eq. 6), so it calibrates the axes by itself: fit
page-coordinates to the equation, then apply that mapping to the grey curve
to read out the real measured mean.

Point counts confirm the identification before any of this is trusted:
543 log bins total, the bass fit covers bins 1-100 (blue, 100 points) and the
mid/high fit covers bins 100-543 (black, 444 points).
"""
import sys

import numpy as np

sys.path.insert(0, r"C:\Users\jerem\AppData\Local\Temp\claude")
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")

from pdf_paths import load_streams, parse
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB

MID = (-0.000183, 0.0213, -16.735)      # Eq. 6, bins 100-543


def eq6(binx):
    b = np.asarray(binx, float)
    return MID[0] * b ** 2 + MID[1] * b + MID[2]


paths, _ = parse(load_streams()[20])
by_len = sorted(paths, key=lambda p: -len(p[1]))
grey = next(p for c, p in by_len if max(c) > 0.8 and min(c) > 0.8)
black = next(p for c, p in by_len if max(c) < 0.2 and len(p) > 400)
blue = next(p for c, p in by_len if c[2] > 0.8 and c[0] < 0.2)
print(f"grey {len(grey)} pts, black {len(black)} pts, blue {len(blue)} pts")

def by_x(pts):
    a = np.array(pts)
    return a[np.argsort(a[:, 0])]


GS, BS, U = by_x(grey), by_x(black), by_x(blue)

# --- x axis: bins are evenly spaced on the page -----------------------
x1, x100 = U[:, 0].min(), U[:, 0].max()          # blue spans bins 1..100
per_bin = (x100 - x1) / 99.0
print(f"bin 1 at x={x1:.2f}, bin 100 at x={x100:.2f}, {per_bin:.4f} pt/bin")
print(f"  black should end at bin 543 -> x={x1 + 542 * per_bin:.2f}, "
      f"actually {BS[:, 0].max():.2f}")

# --- y axis: the black curve IS Eq. 6, so it defines the scale --------

bins_b = (BS[:, 0] - x1) / per_bin + 1.0
A, C = np.polyfit(eq6(bins_b), BS[:, 1], 1)
resid = BS[:, 1] - (A * eq6(bins_b) + C)
print(f"y calibration: page = {A:.4f} * dB + {C:.3f}, "
      f"residual rms {np.sqrt(np.mean(resid ** 2)):.3f} pt "
      f"({np.sqrt(np.mean(resid ** 2)) / abs(A):.3f} dB)")

# --- read the real mean LTAS -----------------------------------------
bins_g = (GS[:, 0] - x1) / per_bin + 1.0
db_g = (GS[:, 1] - C) / A
hz_g = 30.0 * 2.0 ** ((bins_g - 1.0) / 60.0)

f = np.asarray(_REF_FREQS, float)
ok = (f >= 31.5) & (f <= 15700)
real_psd = np.interp(np.log2(f), np.log2(hz_g), db_g)
fit_psd = np.where(f >= 94, eq6(1 + 60 * np.log2(f / 30.0)), np.nan)

band_real = real_psd + 10.0 * np.log10(0.2316 * f)
band_fit = fit_psd + 10.0 * np.log10(0.2316 * f)
mid = (f >= 200) & (f <= 2000)
rel_real = band_real - np.median(band_real[mid])
rel_fit = band_fit - np.median(band_fit[mid])
rel_real[~ok] = np.nan
rel_fit[~ok] = np.nan

print()
print(f"{'Hz':>7} {'real mean':>10} {'quadratic':>10} {'fit err':>8} "
      f"{'TARGET':>8} {'target-real':>12}")
for i, hz in enumerate(f):
    if hz < 200 or hz > 16000:
        continue
    if not np.isfinite(rel_real[i]):
        continue
    print(f"{hz:7.0f} {rel_real[i]:10.2f} {rel_fit[i]:10.2f} "
          f"{rel_fit[i] - rel_real[i]:8.2f} {_REF_SHAPE_DB[i]:8.2f} "
          f"{_REF_SHAPE_DB[i] - rel_real[i]:12.2f}")

b = (f >= 2500) & (f <= 12500)
print()
print(f"2.5-12.5 kHz mean, real measured curve : {np.nanmean(rel_real[b]):7.2f}")
print(f"2.5-12.5 kHz mean, quadratic fit       : {np.nanmean(rel_fit[b]):7.2f}")
print(f"  the fit misstates the real curve by  : "
      f"{np.nanmean(rel_fit[b]) - np.nanmean(rel_real[b]):+7.2f} dB")
print(f"shipped target vs the REAL curve       : "
      f"{_REF_SHAPE_DB[b].mean() - np.nanmean(rel_real[b]):+7.2f} dB")

np.save(r"C:\Users\jerem\AppData\Local\Temp\claude\elowsson_real.npy", rel_real)
