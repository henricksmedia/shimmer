"""Do the captures differ from the paper the way the paper says they should?

Elowsson & Friberg Section 4.1 and Figure 7: tracks with more percussion sit
ABOVE the dataset mean in the bass AND in the treble, and track it in the
mids. Their 11 groups all show it, monotonically in Lperc.

Contemporary pop and electronic music is at the percussive end, and Hove,
Vuust & Stupacher (JASA 145, 2019) separately show bass has risen since 1955
in Billboard material, strongest below 100 Hz. So relative to a mean built on
Dylan-and-Beatles-weighted CD masters, contemporary captures should show a
smile: up at both ends, flat in the middle.

If they do, the captures behave the way the literature predicts and the
shipped target -- which is up in the bass but ALSO up across the whole top --
is the odd one out. If they do not, the captures are suspect.
"""
import glob
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

f = np.asarray(_REF_FREQS, float)
real = np.load(r"C:\Users\jerem\AppData\Local\Temp\claude\elowsson_real.npy")

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
i10, i16 = int(np.argmin(abs(f - 10000))), int(np.argmin(abs(f - 16000)))


def ok(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


cap = np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
                if ok(np.array(t["rel_db"], float))])
tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
svc = np.median(np.array([t["rel_db"] for t in tone["tracks"]], float), axis=0)
dk = np.median(np.array([relative_band_levels(np.array(analyze_spectrum(
    *load_audio(p))["band_power_db"])) for p in sorted(glob.glob(
        r"D:\MusicVault\Tools\Shimmer\sources\distrokid-*.wav"))]), axis=0)

capm = np.median(cap, axis=0)
lo = np.percentile(cap, 16, axis=0)
hi = np.percentile(cap, 84, axis=0)

print("Departure from the paper's measured mean, in dB.")
print("The paper predicts a percussive/contemporary corpus is UP at both")
print("ends and FLAT in the mids.")
print()
print(f"{'Hz':>7} {'captured':>9} {'p16..p84':>14} {'service':>9} "
      f"{'TARGET':>8}")
for i, hz in enumerate(f):
    if hz < 63 or hz > 12500 or not np.isfinite(real[i]):
        continue
    print(f"{hz:7.0f} {capm[i]-real[i]:+9.1f} "
          f"{lo[i]-real[i]:+6.1f}..{hi[i]-real[i]:+6.1f} "
          f"{svc[i]-real[i]:+9.1f} {_REF_SHAPE_DB[i]-real[i]:+8.1f}")

zones = (("bass 63-160", 63, 160), ("low-mid 200-500", 200, 500),
         ("mid 630-1.6k", 630, 1600), ("presence 2-5k", 2000, 5000),
         ("air 6.3-12.5k", 6300, 12500))
print()
print(f"{'zone':<18} {'captured':>9} {'service':>9} {'TARGET':>9} "
      f"{'Shimmer out':>12}")
sh = np.median(np.array([relative_band_levels(np.array(analyze_spectrum(
    *load_audio(p))["band_power_db"])) for p in sorted(glob.glob(
        r"D:\MusicVault\Tools\Shimmer\sources\shimmer-*.wav"))]), axis=0)
for name, a, b in zones:
    m = (f >= a) & (f <= b) & np.isfinite(real)
    print(f"{name:<18} {np.mean(capm[m]-real[m]):+9.1f} "
          f"{np.mean(svc[m]-real[m]):+9.1f} "
          f"{np.mean(_REF_SHAPE_DB[m]-real[m]):+9.1f} "
          f"{np.mean(sh[m]-real[m]):+12.1f}")

print()
print("Read: a smile (up, flat, up) is what the paper predicts for")
print("contemporary percussive material. A rising ramp that never comes")
print("back down is not predicted by anything in the literature.")
