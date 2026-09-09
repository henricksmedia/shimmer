"""Independent audit of the Figure 5 vector extraction.

Three things must hold if the grey polyline really is the smoothed mean LTAS
that Eq. 6 was fitted to:
  1. refitting a quadratic to it over bins 100-543 must return Eq. 6's own
     coefficients,
  2. its RMS residual against Eq. 6 must equal the 0.676 dB that the paper's
     reported "norm of residuals reduced by a factor of 4.1" implies,
  3. its least-squares LINE over the same bins must have the 5.79 dB/octave
     slope the paper reports for the linear fitting.
None of those three numbers were used to build the extraction, so agreement
is not circular.
"""
import sys

import numpy as np

sys.path.insert(0, r"C:\Users\jerem\AppData\Local\Temp\claude")
from pdf_paths import load_streams, parse

MID = (-0.000183, 0.0213, -16.735)


def eq6(b):
    return MID[0] * np.asarray(b, float) ** 2 + MID[1] * np.asarray(b, float) + MID[2]


paths, _ = parse(load_streams()[20])
by_len = sorted(paths, key=lambda p: -len(p[1]))
grey = next(p for c, p in by_len if max(c) > 0.8 and min(c) > 0.8)
black = next(p for c, p in by_len if max(c) < 0.2 and len(p) > 400)
blue = next(p for c, p in by_len if c[2] > 0.8 and c[0] < 0.2)


def by_x(pts):
    a = np.array(pts)
    return a[np.argsort(a[:, 0])]


GS, BS, U = by_x(grey), by_x(black), by_x(blue)
x1, x100 = U[:, 0].min(), U[:, 0].max()
per_bin = (x100 - x1) / 99.0
bins_b = (BS[:, 0] - x1) / per_bin + 1.0
A, C = np.polyfit(eq6(bins_b), BS[:, 1], 1)

bg = (GS[:, 0] - x1) / per_bin + 1.0
dg = (GS[:, 1] - C) / A
print(f"grey polyline spans bins {bg.min():.1f} to {bg.max():.1f} "
      f"({len(bg)} points; 543 expected)")
d = np.diff(np.sort(bg))
print(f"  bin spacing: median {np.median(d):.3f}, max {d.max():.3f} "
      f"-> {int(round(543-len(bg)))} points dropped, "
      f"{'at a gap' if d.max() > 2.5 else 'as collinear runs, no gap'}")
print(f"  grey y range {dg.min():.2f} to {dg.max():.2f} dB")

m = (bg >= 100) & (bg <= 543)
g, b = dg[m], bg[m]
print()
print("1. refit a quadratic to the extracted grey, bins 100-543")
a2, a1, a0 = np.polyfit(b, g, 2)
print(f"   recovered  a={a2:+.6f}  b={a1:+.5f}  c={a0:+.3f}")
print(f"   Eq. 6      a={MID[0]:+.6f}  b={MID[1]:+.5f}  c={MID[2]:+.3f}")
print(f"   quadratic term agrees to {abs(a2-MID[0])/abs(MID[0])*100:.1f}%, "
      f"slope term to {abs(a1-MID[1])/abs(MID[1])*100:.1f}%, "
      f"offset to {abs(a0-MID[2]):.3f} dB")

print()
print("2. residual of the extracted grey against Eq. 6")
r = g - eq6(b)
print(f"   RMS {np.sqrt(np.mean(r**2)):.3f} dB   max |r| {np.abs(r).max():.2f} dB")
print(f"   predicted from the paper's 'factor of 4.1': 0.676 dB")

print()
print("3. least-squares LINE through the extracted grey, bins 100-543")
s = np.polyfit(b, g, 1)[0] * 60.0
print(f"   {s:+.2f} dB/octave   (paper's linear fitting: -5.79)")

print()
print("Where the residual lives (the quadratic minus the real curve):")
hz = 30.0 * 2.0 ** ((b - 1.0) / 60.0)
print(f"{'octave band':>16} {'mean fit-real':>14}")
for lo, hi in ((94, 250), (250, 630), (630, 1600), (1600, 4000),
               (4000, 4500), (4500, 6300), (6300, 10000), (10000, 15700)):
    k = (hz >= lo) & (hz < hi)
    print(f"{lo:6.0f}-{hi:6.0f} Hz {-r[k].mean():14.2f}")
print("  positive = the quadratic sits ABOVE the real measured curve")
print(f"  the 'sharp fall at around 4.5 kHz' the paper describes in 6.1 is")
print(f"  visible: the real curve drops {dg[np.argmin(np.abs(bg-434))]-dg[np.argmin(np.abs(bg-455))]:.2f} dB "
      f"between 4.5 and 5.4 kHz, against {eq6(434)-eq6(455):.2f} dB for the fit.")
