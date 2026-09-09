"""Where the paper's curve and Shimmer's target actually part company, how
much of it percussive prominence can own, and whether 2.5-12.5 kHz is the
right window to argue in.
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
BASS, MID = (-0.000907, 0.256, -32.942), (-0.000183, 0.0213, -16.735)


def elow_psd(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    a = np.where(x < 100.0, BASS[0], MID[0])
    b = np.where(x < 100.0, BASS[1], MID[1])
    c = np.where(x < 100.0, BASS[2], MID[2])
    return a * x ** 2 + b * x + c


def to_band(hz):
    """Density -> 1/3-octave band power, integrating the power law across the
    band rather than sampling the centre (checks the centre approximation)."""
    hz = np.asarray(hz, float)
    lo, hi = hz / 2 ** (1 / 6), hz * 2 ** (1 / 6)
    g = np.linspace(0, 1, 401)
    out = []
    for l, h, c in zip(lo, hi, hz):
        ff = l * (h / l) ** g
        p = 10.0 ** (elow_psd(ff) / 10.0)
        out.append(10.0 * np.log10(np.trapezoid(p, ff)))
    return np.array(out)


VALID = (f >= 31.5) & (f <= 15700)
centre = elow_psd(f) + 10.0 * np.log10(0.2316 * f)
integ = to_band(f)
mid = (f >= 200) & (f <= 2000)

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
i10, i16 = int(np.argmin(abs(f - 10000))), int(np.argmin(abs(f - 16000)))


def ok(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


cap = np.array([np.array(t["rel_db"], float) for t in lib["tracks"]
                if ok(np.array(t["rel_db"], float))])
tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
svc = np.array([t["rel_db"] for t in tone["tracks"]], float)


def disk(tag):
    return np.array([relative_band_levels(np.array(analyze_spectrum(
        *load_audio(p))["band_power_db"]))
        for p in sorted(glob.glob(
            rf"D:\MusicVault\Tools\Shimmer\sources\{tag}-*.wav"))])


suno, shim = disk("suno"), disk("shimmer")

# ---- anchor sensitivity -------------------------------------------------
print("Does the 200 Hz - 2 kHz MEDIAN anchor bias the comparison?")
print(f"{'curve':<20} {'median-anchored':>16} {'mean-anchored':>15} {'shift':>7}")
rows = {"Elowsson (centre)": centre, "Elowsson (integrated)": integ,
        "SHIPPED TARGET": np.asarray(_REF_SHAPE_DB, float),
        "captured 13": np.median(cap, axis=0),
        "service 309": np.median(svc, axis=0)}
band = (f >= 2500) & (f <= 12500)
norm = {}
for n, c in rows.items():
    med = c - np.median(c[mid])
    men = c - np.mean(c[mid])
    norm[n] = med
    print(f"{n:<21} {med[band].mean():15.2f} {men[band].mean():14.2f} "
          f"{men[band].mean()-med[band].mean():+7.2f}")
print("  (the anchor moves the paper and the target by different amounts;")
print("   mean-anchoring narrows the paper-vs-target gap by "
      f"{(norm['SHIPPED TARGET'][band].mean()-norm['Elowsson (centre)'][band].mean()) - ((np.asarray(_REF_SHAPE_DB,float)-np.mean(np.asarray(_REF_SHAPE_DB,float)[mid]))[band].mean()-(centre-np.mean(centre[mid]))[band].mean()):.2f} dB)")

E = norm["Elowsson (centre)"].copy()
E[~VALID] = np.nan
print()
print(f"centre-sample vs in-band integration of the density, max difference "
      f"{np.nanmax(np.abs(norm['Elowsson (centre)']-norm['Elowsson (integrated)'])[VALID]):.3f} dB"
      "  (so the centre shortcut is fine)")

# ---- where do they part company? ---------------------------------------
T = np.asarray(_REF_SHAPE_DB, float)
C = np.median(cap, axis=0)
print()
print("Band by band, dB relative to the 200 Hz - 2 kHz median")
print(f"{'Hz':>7} {'paper':>7} {'capt13':>7} {'TARGET':>7} "
      f"{'T-paper':>8} {'T-capt':>7} {'capt-paper':>11}")
for i, hz in enumerate(f):
    if hz < 50 or hz > 16000:
        continue
    e = E[i]
    s = f"{e:7.1f}" if np.isfinite(e) else f"{'-':>7}"
    d1 = f"{T[i]-e:8.1f}" if np.isfinite(e) else f"{'-':>8}"
    d3 = f"{C[i]-e:11.1f}" if np.isfinite(e) else f"{'-':>11}"
    print(f"{hz:7.0f} {s} {C[i]:7.1f} {T[i]:7.1f} {d1} {T[i]-C[i]:7.1f} {d3}")

# ---- window choice ------------------------------------------------------
print()
print("Does the choice of window change the story?")
print(f"{'window':>16} {'bands':>6} {'paper':>7} {'capt13':>7} {'TARGET':>7} "
      f"{'T-paper':>8} {'T-capt':>7}")
for lo, hi in ((2500, 12500), (5000, 12500), (2500, 4000), (5000, 15700),
               (4000, 12500), (2500, 15700)):
    m = (f >= lo) & (f <= hi) & VALID
    print(f"{lo/1000:6.1f}-{hi/1000:5.1f}k {int(m.sum()):6d} "
          f"{np.nanmean(E[m]):7.2f} {C[m].mean():7.2f} {T[m].mean():7.2f} "
          f"{T[m].mean()-np.nanmean(E[m]):8.2f} {T[m].mean()-C[m].mean():7.2f}")
print("  (16 kHz band spans 14.3-18.0 kHz, past the paper's 15.7 kHz limit,")
print("   so it is excluded from every window above.)")

# ---- the 89 Hz / 4.5 kHz equal-offset anchor ---------------------------
print()
print("Section 4.2 located the pair (89 Hz, 4.5 kHz) as the frequencies where")
print("the 11 percussion groups' offsets from the corpus mean are EQUAL --")
print("that is what makes the slope between them invariant. So a corpus with")
print("more percussion should sit above the paper by the SAME amount at 89 Hz")
print("as at 4.5 kHz, and by more above 4.5 kHz.")


def at(c, hz):
    m = np.isfinite(c)
    return float(np.interp(np.log2(hz), np.log2(f[m]), np.asarray(c)[m]))


print(f"{'curve':<22} {'89 Hz':>8} {'4.5 kHz':>9} {'excess@89':>10} "
      f"{'excess@4.5k':>12} {'consistent?':>12}")
e89, e45 = at(E, 89.0), at(E, 4500.0)
for n, c in (("SHIPPED TARGET", T), ("captured 13", C),
             ("service 309", np.median(svc, axis=0)),
             ("Suno raw", np.median(suno, axis=0)),
             ("Shimmer out", np.median(shim, axis=0))):
    a, b = at(c, 89.0), at(c, 4500.0)
    d1, d2 = a - e89, b - e45
    print(f"{n:<22} {a:8.1f} {b:9.1f} {d1:10.1f} {d2:12.1f} "
          f"{d2-d1:+11.1f}")
print("  last column = how much the treble excess exceeds the bass excess.")
print("  Under the paper's own Lperc model that should be small and positive;")
print("  a large positive value is brightness the percussion model cannot own.")

# ---- what 0.61 dB actually measures ------------------------------------
print()
print("Is 0.61 dB the ceiling on the percussion explanation?")
te, ter = 3.94, 3.94 - 0.61
print(f"  Te {te:.2f} dB -> Te' {ter:.2f} dB, both means over ALL frequency bins.")
print(f"  Variance removed: sqrt({te**2:.2f} - {ter**2:.2f}) = "
      f"{np.sqrt(te**2-ter**2):.2f} dB RMS of per-track systematic, "
      "averaged over all frequencies.")
print("  Figure 9: the reduction is ~zero between 100 Hz and 2 kHz and lives")
print("  below 100 Hz and above 2 kHz -- roughly half the log-frequency axis.")
for frac in (0.4, 0.5, 0.6):
    red = 0.61 / frac
    for teb in (4.5, 5.0, 5.5):
        sys_rm = np.sqrt(max(teb**2 - (teb - red)**2, 0))
        if frac == 0.5 and teb == 5.0:
            print(f"  If the reduction is confined to {frac:.0%} of the axis "
                  f"({red:.2f} dB there) and Te is {teb:.1f} dB in the treble,")
            print(f"  the systematic the model removes there is "
                  f"{sys_rm:.2f} dB RMS across tracks -- not 0.61.")
print(f"{'  Te(treble)':<16} {'reduction there':>16} {'systematic removed':>20}")
for teb in (4.0, 4.5, 5.0, 5.5, 6.0):
    red = 0.61 / 0.5
    print(f"{teb:14.1f} dB {red:13.2f} dB {np.sqrt(max(teb**2-(teb-red)**2,0)):17.2f} dB")

# measured spread for scale
for nm, arr in (("service 309", svc), ("captured 13", cap)):
    m8 = int(np.argmin(abs(f - 8000)))
    print(f"  for scale, between-track SD at 8 kHz, {nm}: "
          f"{np.std(arr[:, m8], ddof=1):.2f} dB")
