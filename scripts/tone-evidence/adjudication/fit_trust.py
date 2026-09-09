"""How much can Elowsson & Friberg's quadratic be wrong above 4.5 kHz?

Everything here is derived from numbers printed IN the paper, not from the
figures (which are images we cannot read).

Two published facts pin the fit's own accuracy:
  * Eq. 6 is the least-squares quadratic on log bins 100-543.
  * "It reduced the norm of residuals in y2 by a factor of 4.1 in relation
    to the linear fitting", and the linear fit's slope was 5.79 dB/octave.

Because the least-squares residual of the quadratic is orthogonal to
{1, x, x^2}, and the linear fit is the projection of the quadratic fit plus
that residual onto {1, x},

    ||r_lin||^2 = ||Qfit - Lfit||^2 + ||r_quad||^2 ,

and ||Qfit - Lfit|| is computable in closed form from Eq. 6 alone. So the
factor 4.1 gives ||r_quad|| exactly.
"""
import numpy as np

BASS = (-0.000907, 0.256, -32.942)
MID = (-0.000183, 0.0213, -16.735)
X1, X2 = 100, 543


def bin_of(hz):
    return 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)


def hz_of(x):
    return 30.0 * 2.0 ** ((np.asarray(x, float) - 1.0) / 60.0)


def Q(x):
    x = np.asarray(x, float)
    a, b, c = MID
    ab, bb, cb = BASS
    return np.where(x < 100.0, ab * x**2 + bb * x + cb, a * x**2 + b * x + c)


x = np.arange(X1, X2 + 1, dtype=float)          # 444 bins
f = hz_of(x)
q = MID[0] * x**2 + MID[1] * x + MID[2]

# ---- 1. the fit's own residual, from the paper's factor of 4.1 ----------
A = np.vstack([np.ones_like(x), x]).T
lin = A @ np.linalg.lstsq(A, q, rcond=None)[0]
d = q - lin
print("Internal consistency of the paper's own two fits")
print(f"  LS line through Eq. 6, slope           {60*np.polyfit(x, q, 1)[0]:+.3f} dB/oct"
      f"   (paper's linear fit: -5.79)")
print(f"  ||Qfit - Lfit||, RMS over bins 100-543  {np.sqrt(np.mean(d**2)):.3f} dB")
for tag, k in (("norm ratio 4.1 (MATLAB normr)", 4.1),
               ("if 4.1 meant sum-of-squares", np.sqrt(4.1))):
    rq = np.sqrt(np.mean(d**2)) / np.sqrt(k**2 - 1.0)
    print(f"  -> RMS residual of Eq. 6 vs the real smoothed mean LTAS"
          f"  [{tag}]: {rq:.3f} dB")
RQ = np.sqrt(np.mean(d**2)) / np.sqrt(4.1**2 - 1.0)
RQ_HI = np.sqrt(np.mean(d**2)) / np.sqrt(np.sqrt(4.1)**2 - 1.0)

# ---- 2. worst-case band-mean error of the fit --------------------------
# max |mean_S(r)| given sum(r)=0, r orthogonal to x and x^2, ||r||^2 = N*RQ^2
B = np.vstack([np.ones_like(x), x, x**2]).T
P = np.eye(len(x)) - B @ np.linalg.pinv(B)      # project out {1,x,x^2}
print()
print("Worst possible error in the fit's own BAND MEAN (adversarial residual)")
print(f"{'band':>14} {'n bins':>7} {'central':>9} {'conservative':>13}")
for lo, hi in ((2500, 12500), (5000, 12500), (2500, 4500), (4500, 15700),
               (8000, 15700), (10000, 15700)):
    u = ((f >= lo) & (f <= hi)).astype(float)
    up = P @ u                                   # part of the indicator the fit cannot absorb
    worst = np.linalg.norm(up) * np.sqrt(len(x)) / u.sum()
    print(f"{lo/1000:5.1f}-{hi/1000:5.1f}k {int(u.sum()):7d} "
          f"{worst*RQ:8.2f} dB {worst*RQ_HI:12.2f} dB")

# ---- 3. how deep can the "sharp fall at 4.5 kHz" be? -------------------
print()
print("The feature the paper describes in 6.1: 'the spectrum falls relatively")
print("sharply at around 4.5 kHz'.  A quadratic cannot render a step, so the")
print("step shows up whole in the residual.  How deep can it be before the")
print("residual exceeds what the paper reported?")
print(f"{'step width':>12} {'depth for RMS=%.2f' % RQ:>20} {'signed mean err 2.5-12.5k':>27}")
band = (f >= 2500) & (f <= 12500)
band2 = (f >= 5000) & (f <= 12500)
for w_oct in (0.25, 0.5, 1.0, 2.0):
    step = -0.5 * np.tanh((x - bin_of(4500)) / (60.0 * w_oct / 2.0))
    s = P @ step                                 # only the part the fit leaves behind
    depth = RQ / np.sqrt(np.mean(s**2))          # scale so residual RMS matches
    r = s * depth
    print(f"{w_oct:9.2f} oct {depth:16.2f} dB {r[band].mean():21.2f} dB"
          f"   (5-12.5k {r[band2].mean():+.2f})")

# ---- 4. same for an unmodelled roll-off at the very top ----------------
print()
print("Alternative: the real curve rolls off harder than a quadratic above")
print("some knee (CD-era HF limit, MP3 lowpass contamination in the corpus).")
print(f"{'knee':>12} {'extra fall for RMS=%.2f' % RQ:>25} {'signed mean err 2.5-12.5k':>27}")
for knee_hz in (8000, 10000, 12500):
    ramp = -np.clip(np.log2(np.maximum(f, knee_hz) / knee_hz), 0, None)
    s = P @ ramp
    scale = RQ / np.sqrt(np.mean(s**2))
    r = s * scale
    print(f"{knee_hz/1000:8.1f} kHz {scale:19.2f} dB/oct {r[band].mean():21.2f} dB"
          f"   (5-12.5k {r[band2].mean():+.2f})")

# ---- 5. the MP3 claim, localised ---------------------------------------
print()
print("The MP3 claim: mean ABSOLUTE change 0.06 dB, averaged over the 543")
print("log bins of 30 Hz - 15.7 kHz.  A mean over 9 octaves hides a localised")
print("problem.  Worst case, if ALL of that budget sat in one sub-band:")
tot = 543
for lo, hi in ((10000, 15700), (8000, 15700), (12500, 15700), (2500, 12500)):
    n = 60.0 * np.log2(hi / lo)
    print(f"  {lo/1000:5.1f}-{hi/1000:4.1f} kHz  {n:5.0f}/{tot} bins  "
          f"-> at most {0.06*tot/n:5.2f} dB mean absolute error there")

# ---- 6. log-domain averaging and a lowpassed minority -------------------
print()
print("The real MP3 risk is not the 30 test tracks (192 kbps, lowpass ~19 kHz)")
print("but the corpus MP3s, of unknown provenance.  LTAS is averaged in dB, so")
print("a lowpassed minority drags the mean down linearly:")
for p in (0.02, 0.05, 0.10, 0.20):
    for depth in (20.0, 30.0):
        pass
    print(f"  {p*100:4.0f}% of tracks lowpassed, -25 dB above the cut"
          f"  -> mean LTAS there falls {p*25:5.2f} dB")
print("  but a 128 kbps lowpass lands at 15-16 kHz, above Shimmer's 12.5 kHz")
print("  band (11.2-14.1 kHz), so this touches at most the topmost band.")
