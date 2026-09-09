"""ISO 226:2003, Acoustics - Normal equal-loudness-level contours.

Equations (1) and (2) and Table 1, transcribed from the standard's own
published preview (ISO 226:2003(E), Clause 4, Table 1).

Eq. (1)  Lp = (10/af)*lg(Af) - Lu + 94 dB
         Af = 4.47e-3*(10^(0.025*Ln) - 1.15)
              + [0.4*10^(((Tf + Lu)/10) - 9)]^af

Eq. (2)  Ln = 40*lg(Bf) + 94 phon
         Bf = (0.4*10^((Lp + Lu)/10 - 9))^af
              - (0.4*10^((Tf + Lu)/10 - 9))^af + 0.005135

Validity: 20 phon lower limit; upper limit 90 phon for 20 Hz - 4 kHz and
80 phon for 5 kHz - 12.5 kHz.
"""
import numpy as np

F = np.array([20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315,
              400, 500, 630, 800, 1000, 1250, 1600, 2000, 2500, 3150, 4000,
              5000, 6300, 8000, 10000, 12500], float)
AF = np.array([0.532, 0.506, 0.480, 0.455, 0.432, 0.409, 0.387, 0.367, 0.349,
               0.330, 0.315, 0.301, 0.288, 0.276, 0.267, 0.259, 0.253, 0.250,
               0.246, 0.244, 0.243, 0.243, 0.243, 0.242, 0.242, 0.245, 0.254,
               0.271, 0.301])
LU = np.array([-31.6, -27.2, -23.0, -19.1, -15.9, -13.0, -10.3, -8.1, -6.2,
               -4.5, -3.1, -2.0, -1.1, -0.4, 0.0, 0.3, 0.5, 0.0, -2.7, -4.1,
               -1.0, 1.7, 2.5, 1.2, -2.1, -7.1, -11.2, -10.7, -3.1])
TF = np.array([78.5, 68.7, 59.5, 51.1, 44.0, 37.5, 31.5, 26.5, 22.1, 17.9,
               14.4, 11.4, 8.6, 6.2, 4.4, 3.0, 2.2, 2.4, 3.5, 1.7, -1.3,
               -4.2, -6.0, -5.4, -1.5, 6.0, 12.6, 13.9, 12.3])


def spl_from_phon(ln):
    """Eq. (1): SPL of the equal-loudness contour at loudness level ln."""
    af = 4.47e-3 * (10.0 ** (0.025 * ln) - 1.15) \
        + (0.4 * 10.0 ** (((TF + LU) / 10.0) - 9.0)) ** AF
    return (10.0 / AF) * np.log10(af) - LU + 94.0


def phon_from_spl(lp):
    """Eq. (2): loudness level of a tone at per-band SPL lp."""
    bf = (0.4 * 10.0 ** ((np.asarray(lp, float) + LU) / 10.0 - 9.0)) ** AF \
        - (0.4 * 10.0 ** ((TF + LU) / 10.0 - 9.0)) ** AF + 0.005135
    return 40.0 * np.log10(bf) + 94.0


k1k = int(np.where(F == 1000)[0][0])

print("Self-check against the 1 kHz definition (phon == dB SPL at 1 kHz):")
for ln in (20, 40, 60, 80, 90):
    print(f"  Ln={ln:3d} phon -> Eq.(1) Lp(1kHz) = {spl_from_phon(ln)[k1k]:6.2f} dB"
          f"   Eq.(2) round-trip = {phon_from_spl(spl_from_phon(ln))[k1k]:6.2f} phon")

print()
print("=" * 74)
print("A. CONTOUR-SHAPE METHOD")
print("   How much relative apparent gain each band picks up when overall")
print("   loudness level rises by 2.8 phon. Positive = sounds brighter.")
print("=" * 74)
D = 2.8
print(f"{'Hz':>7} " + " ".join(f"{f'{b} phon':>10}" for b in (60, 70, 80)))
for base in (60, 70, 80):
    pass
rows = {}
for base in (60, 70, 80):
    a = spl_from_phon(base)
    b = spl_from_phon(base + D)
    rel = (a - a[k1k]) - (b - b[k1k])
    rows[base] = rel
for i, f in enumerate(F):
    if f < 200:
        continue
    print(f"{f:7.0f} " + " ".join(f"{rows[b][i]:10.2f}" for b in (60, 70, 80)))

print()
print("=" * 74)
print("B. DIRECT METHOD - the actual A/B")
print("   Give each 1/3-oct band the SPL a real master would put there,")
print("   raise the whole thing by 2.8 dB, and ask how many phons each band")
print("   gains. Brightness change = gain(presence band) - gain(midrange).")
print("=" * 74)

# relative 1/3-octave shape of the captured commercial median, 200 Hz up
SHAPE = {200: 2.2, 250: 1.8, 315: 2.7, 400: 1.5, 500: 0.0, 630: 0.8, 800: 0.0,
         1000: -1.6, 1250: -2.8, 1600: -3.2, 2000: -4.5, 2500: -5.8,
         3150: -5.4, 4000: -7.4, 5000: -8.2, 6300: -9.3, 8000: -10.2,
         10000: -10.6, 12500: -12.8}
idx = [int(np.where(F == f)[0][0]) for f in SHAPE]
rel = np.array(list(SHAPE.values()))

print(f"{'1kHz band SPL':>14} " + " ".join(
    f"{f'{f/1000:g}k':>7}" for f in SHAPE if f >= 2000))
print(f"{'':>14} " + " ".join(f"{'dPhon':>7}" for f in SHAPE if f >= 2000)
      + "   |  4-10k mean minus 1k")
for mid in (55, 65, 75):
    lp = np.full(len(F), -200.0)
    lp[idx] = rel + mid + 1.6      # anchor: 1 kHz band sits at `mid`
    lo = phon_from_spl(lp)
    hi = phon_from_spl(lp + D)
    d = hi - lo
    dmid = d[int(np.where(F == 1000)[0][0])]
    hf = [int(np.where(F == f)[0][0]) for f in (4000, 5000, 6300, 8000, 10000)]
    print(f"{mid:11d} dB " + " ".join(
        f"{d[int(np.where(F==f)[0][0])]:7.2f}" for f in SHAPE if f >= 2000)
        + f"   |  {np.mean(d[hf]) - dmid:+.2f} dB")

print()
print("Reference: the whole 2.8 dB shows up as 2.8 phon at every band once")
print("the ear is well above threshold; only the residual differences above")
print("are 'extra brightness'.")
