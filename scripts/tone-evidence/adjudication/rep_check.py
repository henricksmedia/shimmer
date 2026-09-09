"""Does the paper's PIPELINE, run on files whose Shimmer curve we know,
reproduce the Shimmer curve? Separates three possible error sources:

  (a) density -> 1/3-octave band-power conversion  (flat-in-band approximation)
  (b) analysis differences (mono mix vs L/R, 1/6-oct Gaussian vs 1/3-oct rect)
  (c) the two-quadratic FIT that is the only thing the paper actually publishes

If (a)+(b) are small and (c) is large, the -11.75 dB is a property of the
curve fit, not of the music.
"""
import glob
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

f3 = np.asarray(_REF_FREQS, float)
MID = (f3 >= 200) & (f3 <= 2000)
AIR = (f3 >= 2500) & (f3 <= 12500)

# ---------------------------------------------------------------- (a)
print("=" * 72)
print("(a) flat-in-band approximation:  band power vs integral of the density")
print("    exact = 10log10( (2^((p+1)/6) - 2^(-(p+1)/6)) / ((p+1)*0.2316) )")
for s in (0.0, -3.0, -6.0, -9.0, -12.0, -18.0):
    p = s / 3.010299957
    q = p + 1.0
    exact = 10 * np.log10((2 ** (q / 6) - 2 ** (-q / 6)) / (q * 0.2316))
    print(f"    PSD slope {s:6.1f} dB/oct   error of the flat approximation "
          f"{exact:+.3f} dB")
print("    -> under 0.1 dB anywhere in the disputed band. Not the explanation.")


# ---------------------------------------------------------------- pipeline
def paper_ltas(x, sr, stereo=True):
    """Elowsson & Friberg 2.2: 4096/2048 STFT, mean PSD, 1/6-oct Gaussian
    smoothing of the POWER spectrum, then 10log10."""
    n_fft, hop = 4096, 2048
    x = np.atleast_2d(np.asarray(x, float).T) if np.ndim(x) == 2 else \
        np.asarray(x, float)[None, :]
    chans = x if stereo else np.mean(x, axis=0, keepdims=True)
    win = np.hanning(n_fft)
    acc = np.zeros(n_fft // 2 + 1)
    nf = 0
    for ch in chans:
        for s0 in range(0, len(ch) - n_fft + 1, hop):
            acc += np.abs(np.fft.rfft(ch[s0:s0 + n_fft] * win)) ** 2
            nf += 1
    psd = acc / max(nf, 1)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    # iosr.dsp.smoothSpectrum: sigma = f0/(Noct*pi), Gaussian on the POWER
    sm = np.empty_like(psd)
    for i, f0 in enumerate(freqs):
        if f0 <= 0:
            sm[i] = psd[i]
            continue
        sig = f0 / (6.0 * np.pi)
        g = np.exp(-((freqs - f0) ** 2) / (2 * sig * sig))
        sm[i] = float(np.sum(g * psd) / np.sum(g))
    return freqs, 10 * np.log10(sm + 1e-30)


def to_log_axis(freqs, ltas_db):
    """543 bins, 60/octave, 30 Hz - 15.7 kHz."""
    x = np.arange(1, 544, dtype=float)
    hz = 30.0 * 2 ** ((x - 1) / 60.0)
    return x, hz, np.interp(hz, freqs[1:], ltas_db[1:])


def two_quadratics(x, y):
    """Paper 3.2: quadratic on bins 1-100 and on 100-543, joined at bin 100."""
    lo, hi = x <= 100, x >= 100
    cb = np.polyfit(x[lo], y[lo], 2)
    cm = np.polyfit(x[hi], y[hi], 2)
    # "adjusted to intersect at bin 100"
    cb[2] += np.polyval(cm, 100.0) - np.polyval(cb, 100.0)
    out = np.where(x < 100, np.polyval(cb, x), np.polyval(cm, x))
    return out, cb, cm


def onto_shimmer_grid(hz, density_db):
    v = np.interp(f3, hz, density_db, left=np.nan, right=np.nan)
    band = v + 10 * np.log10(0.2316 * f3)          # density -> band power
    ok = np.isfinite(band)
    return band - np.median(band[MID & ok])


files = sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\distrokid-*.wav"))
rows_raw, rows_fit, rows_shim, rows_mono = [], [], [], []
for p in files:
    au, sr = load_audio(p)
    shim = relative_band_levels(np.array(analyze_spectrum(au, sr)["band_power_db"]))
    fr, lt = paper_ltas(au, sr, stereo=True)
    x, hz, y = to_log_axis(fr, lt)
    fit, _, _ = two_quadratics(x, y)
    rows_shim.append(shim)
    rows_raw.append(onto_shimmer_grid(hz, y))
    rows_fit.append(onto_shimmer_grid(hz, fit))
    frm, ltm = paper_ltas(au, sr, stereo=False)
    xm, hzm, ym = to_log_axis(frm, ltm)
    rows_mono.append(onto_shimmer_grid(hzm, ym))

S = np.array(rows_shim)
R = np.array(rows_raw)
F = np.array(rows_fit)
M = np.array(rows_mono)

print()
print("=" * 72)
print("(b)+(c) same 8 service masters, three ways, dB rel. 200 Hz-2 kHz median")
print(f"{'Hz':>7} {'Shimmer':>9} {'paperPipe':>10} {'diff':>7} "
      f"{'paperFIT':>9} {'fit-pipe':>9} {'mono':>7}")
for i, hz in enumerate(f3):
    if hz < 100 or hz > 16000:
        continue
    a, b, c, d = (np.median(S[:, i]), np.median(R[:, i]),
                  np.median(F[:, i]), np.median(M[:, i]))
    print(f"{hz:7.0f} {a:9.2f} {b:10.2f} {b-a:7.2f} {c:9.2f} {c-b:9.2f} "
          f"{d-b:7.2f}")

ok = np.isfinite(np.median(R, axis=0)) & AIR
print()
print(f"2.5-12.5 kHz mean of the SAME 8 masters:")
print(f"   Shimmer's analyzer                    "
      f"{np.mean(np.median(S,axis=0)[ok]):7.2f} dB")
print(f"   paper's pipeline, no fit              "
      f"{np.mean(np.median(R,axis=0)[ok]):7.2f} dB   "
      f"(representation error {np.mean(np.median(R,axis=0)[ok]-np.median(S,axis=0)[ok]):+.2f})")
print(f"   paper's pipeline + two-quadratic fit  "
      f"{np.mean(np.median(F,axis=0)[ok]):7.2f} dB   "
      f"(FIT alone moves it {np.mean(np.median(F,axis=0)[ok]-np.median(R,axis=0)[ok]):+.2f})")
print(f"   L/R average vs mono mix                       "
      f"{np.mean(np.median(M,axis=0)[ok]-np.median(R,axis=0)[ok]):+.2f} dB")
