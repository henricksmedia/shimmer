"""Compare like with like: put every corpus through the paper's OWN
two-quadratic fitting procedure before comparing it to the paper's equation.

Also: how big is the paper's "invariant" slope tolerance really, and is the
2.5-12.5 kHz arithmetic in the conclusion self-consistent?
"""
import glob
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

f3 = np.asarray(_REF_FREQS, float)
MIDB = (f3 >= 200) & (f3 <= 2000)
AIR = (f3 >= 2500) & (f3 <= 12500)
X = np.arange(1, 544, dtype=float)
HZ = 30.0 * 2 ** ((X - 1) / 60.0)
BASSC, MIDC = (-0.000907, 0.256, -32.942), (-0.000183, 0.0213, -16.735)


def paper_density(x):
    a, b, c = (np.where(x < 100, BASSC[0], MIDC[0]),
               np.where(x < 100, BASSC[1], MIDC[1]),
               np.where(x < 100, BASSC[2], MIDC[2]))
    return a * x ** 2 + b * x + c


def two_quadratics(y):
    lo, hi = X <= 100, X >= 100
    cb, cm = np.polyfit(X[lo], y[lo], 2), np.polyfit(X[hi], y[hi], 2)
    cb[2] += np.polyval(cm, 100.0) - np.polyval(cb, 100.0)
    return np.where(X < 100, np.polyval(cb, X), np.polyval(cm, X))


def band_to_density_on_logaxis(rel_db):
    """Shimmer 1/3-oct band power -> density, sampled on the paper's axis."""
    dens = np.asarray(rel_db, float) - 10 * np.log10(0.2316 * f3)
    return np.interp(np.log2(HZ), np.log2(f3), dens)


def density_to_shimmer(dens_on_logaxis):
    v = np.interp(np.log2(f3), np.log2(HZ), dens_on_logaxis,
                  left=np.nan, right=np.nan)
    b = v + 10 * np.log10(0.2316 * f3)
    ok = np.isfinite(b)
    return b - np.median(b[MIDB & ok])


lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
i10, i16 = int(np.argmin(abs(f3 - 10000))), int(np.argmin(abs(f3 - 16000)))


def keep(c):
    m = (f3 >= 4000) & (f3 <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f3[m]), c[m], 1)[0]) >= -14.0)


cap = np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
                if keep(np.array(t["rel_db"], float))])
svc = np.array([t["rel_db"] for t in tone["tracks"]], float)
disk = {t: np.array([relative_band_levels(np.array(analyze_spectrum(
    *load_audio(p))["band_power_db"])) for p in sorted(glob.glob(
        rf"D:\MusicVault\Tools\Shimmer\sources\{t}-*.wav"))])
    for t in ("distrokid", "shimmer", "suno")}

paper_fit_grid = density_to_shimmer(paper_density(X))
sets = {"SHIPPED TARGET": np.asarray(_REF_SHAPE_DB, float),
        "service 309": np.median(svc, axis=0),
        "captured 13": np.median(cap, axis=0),
        "service on disk 8": np.median(disk["distrokid"], axis=0),
        "Shimmer out 6": np.median(disk["shimmer"], axis=0)}

print("=" * 74)
print("2.5-12.5 kHz mean vs the paper, RAW  and  after the paper's own fit")
print(f"{'':<20} {'raw':>7} {'gap':>7} | {'fitted':>7} {'gap':>7} "
      f"{'fit cost':>9}")
pa = np.nanmean(paper_fit_grid[AIR])
for n, c in sets.items():
    fitted = density_to_shimmer(two_quadratics(band_to_density_on_logaxis(c)))
    r, g = np.nanmean(c[AIR]), np.nanmean(fitted[AIR])
    print(f"{n:<20} {r:7.2f} {r-pa:7.2f} | {g:7.2f} {g-pa:7.2f} {g-r:9.2f}")
print(f"{'paper Eq.5/6':<20} {pa:7.2f} {0.0:7.2f} |")

print()
print("Same, at the bass end (63-160 Hz mean) - the end the conclusion omits")
BASS = (f3 >= 63) & (f3 <= 160)
pb = np.nanmean(paper_fit_grid[BASS])
for n, c in sets.items():
    fitted = density_to_shimmer(two_quadratics(band_to_density_on_logaxis(c)))
    print(f"{n:<20} {np.nanmean(c[BASS]):7.2f} "
          f"{np.nanmean(c[BASS])-pb:7.2f} | {np.nanmean(fitted[BASS]):7.2f} "
          f"{np.nanmean(fitted[BASS])-pb:7.2f}")
print(f"{'paper Eq.5/6':<20} {pb:7.2f} {0.0:7.2f} |")

# ---------------------------------------------------------------- invariance
print()
print("=" * 74)
print("What does the paper's sigma = 0.055 dB/oct actually bound?")


def inv_slope(c):
    p = np.asarray(c, float) - 10 * np.log10(0.2316 * f3)
    a, b = np.interp(np.log2([89.0, 4500.0]), np.log2(f3), p)
    return (b - a) / np.log2(4500.0 / 89.0)


for n, arr in (("captured commercial", cap), ("service masters", svc),
               ("Suno raw", disk["suno"]), ("Shimmer out", disk["shimmer"])):
    v = np.array([inv_slope(c) for c in arr])
    sd = float(np.std(v, ddof=1))
    print(f"  {n:<20} n={len(v):4d}  per-track SD {sd:.3f} dB/oct   "
          f"SD of a mean of 1122 tracks = {sd/np.sqrt(1122):.4f}")
print("  paper: SD BETWEEN 11 GROUP MEANS (~1122 tracks each) = 0.055")
sd_c = float(np.std([inv_slope(c) for c in cap], ddof=1))
print(f"  -> 0.055 is a spread of group MEANS, not a per-master tolerance.")
print(f"  -> for n=13 captures the standard error is "
      f"{sd_c/np.sqrt(13):.3f} dB/oct, {sd_c/np.sqrt(13)/0.055:.0f}x the paper's 0.055")
mc = float(np.median([inv_slope(c) for c in cap]))
mt = inv_slope(_REF_SHAPE_DB)
print(f"  captured 13 median {mc:+.2f} vs paper -4.53 -> off by {mc+4.53:+.2f}")
print(f"  SHIPPED TARGET     {mt:+.2f} vs paper -4.53 -> off by {mt+4.53:+.2f}")
print("  the target is CLOSER to the paper than real Spotify masters are,")
print("  on the analysis's own corpus-proof metric.")

# ---------------------------------------------------------------- arithmetic
print()
print("=" * 74)
print("The conclusion's stated range, checked")
t = np.nanmean(np.asarray(_REF_SHAPE_DB, float)[AIR])
cm = np.nanmean(np.median(cap, axis=0)[AIR])
print(f"  target {t:+.2f}   captured {cm:+.2f}   paper {pa:+.2f}")
print(f"  target excess vs captures  = {t-cm:+.2f} dB  (conclusion says +3)")
print(f"  target excess vs paper     = {t-pa:+.2f} dB  (conclusion says +11)")
print(f"  captures' distance to paper= {cm-pa:+.2f} dB  <- this is the +3.02")
print("  the low bound quoted is the CAPTURES' gap to the paper, not the")
print("  target's gap to the captures. The real low bound is ~+7.9 dB.")

# ------------------------------------------------------- where it goes wrong
print()
print("=" * 74)
print("Where does the target actually part company with real masters?")
print(f"{'Hz':>7} {'TARGET':>8} {'captured':>9} {'gap':>7}")
for i, hz in enumerate(f3):
    if hz < 315 or hz > 16000:
        continue
    g = _REF_SHAPE_DB[i] - np.median(cap[:, i])
    print(f"{hz:7.0f} {_REF_SHAPE_DB[i]:8.2f} {np.median(cap[:,i]):9.2f} "
          f"{g:7.2f}{'   <-- already >2 dB' if g > 2 else ''}")

# --------------------------------------------------------- mean-of-dB effect
print()
print("=" * 74)
print("The paper averages dB across songs (geometric mean of power).")
print("Shimmer uses medians. On Shimmer's own corpora, mean(dB) - median(dB):")
for n, arr in (("service 309", svc), ("captured 13", cap)):
    d = np.mean(arr, axis=0) - np.median(arr, axis=0)
    print(f"  {n}: 63-160 Hz {np.mean(d[BASS]):+.2f} dB, "
          f"200-2k {np.mean(d[MIDB]):+.2f} dB, 2.5-12.5k {np.mean(d[AIR]):+.2f} dB")
print("  (paper's corpus spans 60 years and is far more heterogeneous, so its")
print("   own skew penalty at the two ends will be larger than this)")
