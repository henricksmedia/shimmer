"""The merge decision, judged against the 13 contemporary captures.

Commit 97609c0 replaces a hand-drawn ramp with the measured service median.
'Should not merge' is a claim about that swap, not about the new curve alone.
"""
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB

f = np.asarray(_REF_FREQS, float)
MID = (f >= 200) & (f <= 2000)
i10, i16 = int(np.argmin(abs(f - 10000))), int(np.argmin(abs(f - 16000)))

OLD = np.array([-2.5, 1.0, 3.5, 4.5, 5.0, 5.0, 4.5, 4.0, 3.5, 3.0, 2.5, 2.0,
                1.5, 1.0, 0.5, 0.0, -0.5, -1.0, -1.5, -2.0, -2.5, -3.0, -4.3,
                -5.8, -7.5, -9.5, -12.0, -16.0, -22.0])
NEW = np.asarray(_REF_SHAPE_DB, float)
OLD = OLD - np.median(OLD[MID])
NEW = NEW - np.median(NEW[MID])

BASS, MIDQ = (-0.000907, 0.256, -32.942), (-0.000183, 0.0213, -16.735)


def elow(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    a = np.where(x < 100, BASS[0], MIDQ[0])
    b = np.where(x < 100, BASS[1], MIDQ[1])
    c = np.where(x < 100, BASS[2], MIDQ[2])
    return a * x**2 + b * x + c + 10 * np.log10(0.2316 * np.asarray(hz, float))


E = elow(f)
E -= np.median(E[MID])

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json",
                     encoding="utf-8"))


def gate(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


C = np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
              if gate(np.array(t["rel_db"], float))])
i40 = int(np.argmin(abs(f - 40)))
print(f"sanity: 40 Hz band across the 13 captures -> "
      f"{np.sort(C[:, i40].round(1))}")
print("  (that band is dead in most captures; excluded below)\n")

cm = np.median(C, axis=0)
use = (f >= 31.5) & (f <= 12500) & (np.arange(f.size) != i40)

print("Per-band error against the 13-capture median")
print(f"{'Hz':>7} {'capt':>7} {'OLD(main)':>10} {'err':>6} {'NEW(97609c0)':>13} "
      f"{'err':>6} {'Elowsson':>9} {'err':>6}")
for i, hz in enumerate(f):
    if not use[i]:
        continue
    print(f"{hz:7.0f} {cm[i]:7.1f} {OLD[i]:10.1f} {OLD[i]-cm[i]:6.1f} "
          f"{NEW[i]:13.1f} {NEW[i]-cm[i]:6.1f} {E[i]:9.1f} {E[i]-cm[i]:6.1f}")

print()
print(f"{'region':<20} {'OLD':>8} {'NEW':>8} {'Elowsson':>9}   verdict")
for lo, hi, nm in ((31.5, 160, "31.5-160 Hz"), (200, 2000, "200 Hz-2 kHz"),
                   (2500, 12500, "2.5-12.5 kHz"), (31.5, 12500, "WHOLE")):
    m = use & (f >= lo) & (f <= hi)
    o = np.sqrt(np.mean((OLD[m] - cm[m])**2))
    n = np.sqrt(np.mean((NEW[m] - cm[m])**2))
    e = np.sqrt(np.mean((E[m] - cm[m])**2))
    best = min((o, "OLD"), (n, "NEW"), (e, "Elowsson"))[1]
    print(f"{nm:<20} {o:8.2f} {n:8.2f} {e:9.2f}   best: {best}")

print()
print("Same test against the 13 captures individually (whole spectrum rmse):")
for nm, cur in (("OLD (main)", OLD), ("NEW (97609c0)", NEW), ("Elowsson", E)):
    r = np.array([np.sqrt(np.mean((cur[use] - c[use])**2)) for c in C])
    print(f"  {nm:<15} median {np.median(r):5.2f} dB   wins on "
          f"{int(sum(1 for c in C if np.sqrt(np.mean((cur[use]-c[use])**2)) == min(np.sqrt(np.mean((x[use]-c[use])**2)) for x in (OLD, NEW, E))))}/13 tracks")

air = (f >= 2500) & (f <= 12500)
print()
print("Air-band mean, dB rel 200 Hz-2 kHz:")
for nm, cur in (("OLD (main)", OLD), ("NEW (97609c0)", NEW),
                ("Elowsson", E), ("capture median", cm)):
    print(f"  {nm:<16} {np.mean(cur[air]):+7.2f}")
