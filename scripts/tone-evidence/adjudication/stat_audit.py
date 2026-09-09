"""Statistical audit of the tone-target conclusion."""
import glob
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

rng = np.random.default_rng(20260908)
f = np.asarray(_REF_FREQS, float)
band = (f >= 2500) & (f <= 12500)
i10 = int(np.argmin(abs(f - 10000)))
i16 = int(np.argmin(abs(f - 16000)))

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
tone = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
SVC = np.array([t["rel_db"] for t in tone["tracks"]], float)
NEU = np.array([t["rel_db"] for t in tone["tracks"]
                if t["eq"] == "Neutral"], float)

CAP = np.array([t["rel_db"] for t in lib["tracks"]], float)
LAB = [t["label"] for t in lib["tracks"]]
SEC = np.array([t["heard_seconds"] for t in lib["tracks"]], float)


def bslope(c, lo, hi):
    m = (f >= lo) & (f <= hi)
    return float(np.polyfit(np.log2(f[m]), np.asarray(c, float)[m], 1)[0])


def gate(c):
    return c[i10] >= -29.1 and c[i16] >= -40.1 and bslope(c, 4000, 16000) >= -14.0


keepmask = np.array([gate(c) for c in CAP])
G = CAP[keepmask]
GLAB = [l for l, k in zip(LAB, keepmask) if k]

# artist / album clusters
def cluster(lab):
    a = lab.split("\u2014")[0].strip()
    return a


CL = np.array([cluster(l) for l in GLAB])

BM = G[:, band].mean(axis=1)          # per-track 2.5-12.5 kHz mean
TGT = _REF_SHAPE_DB[band].mean()

print("=" * 78)
print("1. THE CAPTURED SAMPLE, TRACK BY TRACK (2.5-12.5 kHz mean, dB)")
print("=" * 78)
order = np.argsort(BM)
for j in order:
    print(f"  {BM[j]:7.2f}   {SEC[keepmask][j]:5.1f}s  {GLAB[j][:52]}")
print(f"\n  n={len(BM)}  median {np.median(BM):.2f}  mean {BM.mean():.2f}  "
      f"sd {BM.std(ddof=1):.2f}  min {BM.min():.2f}  max {BM.max():.2f}")
print(f"  distinct artists: {len(set(CL))}  -> {sorted(set(CL))}")

# bootstrap: naive iid vs cluster
def boot(vals, groups=None, n=40000, stat=np.median):
    out = np.empty(n)
    if groups is None:
        for i in range(n):
            out[i] = stat(rng.choice(vals, len(vals), replace=True))
    else:
        uq = np.unique(groups)
        idx = {g: np.where(groups == g)[0] for g in uq}
        for i in range(n):
            pick = rng.choice(uq, len(uq), replace=True)
            s = np.concatenate([idx[g] for g in pick])
            out[i] = stat(vals[s])
    return out


for nm, gr in (("iid bootstrap (track)", None),
               ("cluster bootstrap (artist)", CL)):
    for st, sn in ((np.median, "median"), (np.mean, "mean")):
        b = boot(BM, gr, stat=st)
        lo, hi = np.percentile(b, [2.5, 97.5])
        print(f"  {nm:<28} {sn:<7} {st(BM):7.2f}  95% CI [{lo:6.2f},{hi:6.2f}]"
              f"  width {hi-lo:5.2f}")

print()
print("=" * 78)
print("2. HOW MUCH DOES THE ANSWER MOVE WITH SAMPLE CHOICES?")
print("=" * 78)
allbm = CAP[:, band].mean(axis=1)
print(f"  all 15 captures, median          {np.median(allbm):7.2f}"
      f"   gap vs target {np.median(allbm)-TGT:+6.2f}")
print(f"  13 that pass the gate, median    {np.median(BM):7.2f}"
      f"   gap vs target {np.median(BM)-TGT:+6.2f}")
print(f"  13, mean                         {BM.mean():7.2f}"
      f"   gap vs target {BM.mean()-TGT:+6.2f}")
# one per artist (median within artist first)
per_artist = np.array([np.median(BM[CL == g]) for g in np.unique(CL)])
print(f"  1 value per artist (n={len(per_artist)}), median {np.median(per_artist):7.2f}"
      f"   gap vs target {np.median(per_artist)-TGT:+6.2f}")
jk = np.array([np.median(np.delete(BM, k)) for k in range(len(BM))])
print(f"  jackknife median range           [{jk.min():.2f}, {jk.max():.2f}]"
      f"   -> single track moves it {jk.max()-jk.min():.2f} dB")
print(f"  drop brightest + darkest (n=11)  {np.median(np.sort(BM)[1:-1]):7.2f}")

print()
print("=" * 78)
print("3. EXCERPT BIAS: IS -1.35 dB A NUMBER OR A GUESS?")
print("=" * 78)
files = sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\distrokid-*.wav"))
first, whole, wins = [], [], []
for p in files:
    x, sr = load_audio(p)
    whole.append(relative_band_levels(
        np.array(analyze_spectrum(x, sr)["band_power_db"]))[band].mean())
    n = int(30 * sr)
    o = []
    for s in range(0, max(1, x.shape[0] - n), n):
        seg = np.ascontiguousarray(x[s:s + n])
        if seg.shape[0] < n // 2:
            continue
        o.append(relative_band_levels(
            np.array(analyze_spectrum(seg, sr)["band_power_db"]))[band].mean())
    wins.append(np.array(o))
    first.append(o[0])
first, whole = np.array(first), np.array(whole)
d = first - whole
sd = d.std(ddof=1)
se = sd / np.sqrt(len(d))
from math import sqrt, erf, comb
t975 = 2.364624  # t_{0.975, df=7}
print(f"  opening-30s minus whole, per master: "
      f"{np.array2string(d, precision=2, floatmode='fixed')}")
print(f"  mean {d.mean():+.2f}  sd {sd:.2f}  se {se:.2f}  "
      f"95% CI [{d.mean()-t975*se:+.2f}, {d.mean()+t975*se:+.2f}]  "
      f"t={d.mean()/se:.2f}")
print(f"  -> the correction is NOT significantly different from zero (p~"
      f"{2*(1-0.5*(1+erf(abs(d.mean()/se)/np.sqrt(2)))):.2f} normal approx)")
wsd = np.array([w.std(ddof=1) for w in wins])
print(f"  within-track sd across 30 s windows: mean {wsd.mean():.2f} dB "
      f"(range {wsd.min():.2f}-{wsd.max():.2f})")
print(f"  -> a single 25-86 s excerpt carries ~{wsd.mean():.2f} dB of measurement")
print(f"     noise per track; over n=13 that alone is "
      f"{wsd.mean()/np.sqrt(13):.2f} dB of SE, before any real between-track spread")

print()
print("=" * 78)
print("4. WHERE DOES THE TARGET ACTUALLY DIVERGE?  (per band, not just >4.5k)")
print("=" * 78)
BASS, MID = (-0.000907, 0.256, -32.942), (-0.000183, 0.0213, -16.735)


def elow_psd(hz):
    x = 1.0 + 60.0 * np.log2(np.asarray(hz, float) / 30.0)
    a = np.where(x < 100.0, BASS[0], MID[0])
    b = np.where(x < 100.0, BASS[1], MID[1])
    c = np.where(x < 100.0, BASS[2], MID[2])
    return a * x ** 2 + b * x + c


elow = elow_psd(f) + 10.0 * np.log10(0.2316 * f)
mid = (f >= 200) & (f <= 2000)
elow = elow - np.median(elow[mid])
elow[(f < 31.5) | (f > 15700)] = np.nan

print(f"{'Hz':>7} {'TARGET':>8} {'capt med':>9} {'CI(capt)':>16} "
      f"{'T-capt':>7} {'sign':>6} {'Elowsson':>9} {'T-Elow':>7}")
for i, hz in enumerate(f):
    if hz < 500 or hz > 12500:
        continue
    b = boot(G[:, i], CL, n=8000)
    lo, hi = np.percentile(b, [2.5, 97.5])
    nabove = int((G[:, i] < _REF_SHAPE_DB[i]).sum())
    print(f"{hz:7.0f} {_REF_SHAPE_DB[i]:8.1f} {np.median(G[:,i]):9.1f} "
          f"[{lo:6.1f},{hi:6.1f}] {_REF_SHAPE_DB[i]-np.median(G[:,i]):7.1f} "
          f"{nabove:3d}/13 {elow[i]:9.1f} {_REF_SHAPE_DB[i]-elow[i]:7.1f}")

for lo_, hi_ in ((1000, 2500), (2500, 4500), (4500, 12500), (2500, 8000),
                 (8000, 12500)):
    m = (f >= lo_) & (f <= hi_)
    v = G[:, m].mean(axis=1)
    print(f"  {lo_:>6}-{hi_:<6} Hz  target {_REF_SHAPE_DB[m].mean():6.2f}  "
          f"capt {np.median(v):6.2f}  gap {_REF_SHAPE_DB[m].mean()-np.median(v):+6.2f}"
          f"   Elowsson {np.nanmean(elow[m]):6.2f}  gap "
          f"{_REF_SHAPE_DB[m].mean()-np.nanmean(elow[m]):+6.2f}")

print()
print("=" * 78)
print("5. THE 89 Hz - 4.5 kHz 'INVARIANT SLOPE': WHAT IT CAN AND CANNOT SEE")
print("=" * 78)


def psd(c):
    return np.asarray(c, float) - 10.0 * np.log10(0.2316 * f)


def two_pt(c, F1=89.0, F2=4500.0):
    p = psd(c)
    a, b = np.interp(np.log2([F1, F2]), np.log2(f), p)
    return (b - a) / np.log2(F2 / F1)


pe = psd(elow)
e89, e45 = np.interp(np.log2([89.0, 4500.0]), np.log2(f[np.isfinite(pe)]),
                     pe[np.isfinite(pe)])
for nm, c in (("SHIPPED TARGET", _REF_SHAPE_DB),
              ("captured median", np.median(G, axis=0)),
              ("service median", np.median(SVC, axis=0))):
    p = psd(c)
    a, b = np.interp(np.log2([89.0, 4500.0]), np.log2(f), p)
    print(f"  {nm:<17} err at 89 Hz {a-e89:+6.2f} dB, err at 4.5 kHz "
          f"{b-e45:+6.2f} dB  -> 2-pt slope err "
          f"{((b-e45)-(a-e89))/np.log2(4500/89):+5.2f} dB/oct")
    m = (f >= 89) & (f <= 4500)
    print(f"  {'':17} rms residual vs Elowsson over 89 Hz-4.5 kHz: "
          f"{np.sqrt(np.mean((np.asarray(c,float)[m]-elow[m])**2)):5.2f} dB  "
          f"max {np.max(np.abs(np.asarray(c,float)[m]-elow[m])):5.2f} dB")

print()
print("  per-track spread of the 'invariant' slope (the paper's 0.055 is a")
print("  between-GROUP sd of 11 means of ~1122 tracks each):")
for nm, arr in (("captured 13", G), ("service 309", SVC),
                ("service Neutral 135", NEU)):
    v = np.array([two_pt(c) for c in arr])
    print(f"    {nm:<22} n={len(v):4d}  sd {v.std(ddof=1):.3f} dB/oct  "
          f"se of the mean {v.std(ddof=1)/np.sqrt(len(v)):.3f}  "
          f"implied se of a 1122-track mean "
          f"{v.std(ddof=1)/np.sqrt(1122):.3f}")

print()
print("=" * 78)
print("6. DOES THE HEADLINE SURVIVE A DIFFERENT NORMALISATION ANCHOR?")
print("=" * 78)
anchors = {"median 200-2k (shipped)": lambda c: np.median(c[mid]),
           "mean 200-2k": lambda c: np.mean(c[mid]),
           "1 kHz band": lambda c: c[int(np.argmin(abs(f - 1000)))],
           "mean 200-500": lambda c: np.mean(c[(f >= 200) & (f <= 500)]),
           "mean 315-1250": lambda c: np.mean(c[(f >= 315) & (f <= 1250)])}
print(f"{'anchor':<26} {'TARGET':>8} {'capt':>8} {'Elow':>8} {'T-capt':>8} {'T-Elow':>8}")
for nm, fn in anchors.items():
    t = _REF_SHAPE_DB - fn(_REF_SHAPE_DB)
    cm = np.median(np.array([c - fn(c) for c in G]), axis=0)
    el = elow - fn(np.nan_to_num(elow, nan=0.0)) if False else elow - fn(elow)
    print(f"{nm:<26} {t[band].mean():8.2f} {cm[band].mean():8.2f} "
          f"{np.nanmean(el[band]):8.2f} {t[band].mean()-cm[band].mean():8.2f} "
          f"{t[band].mean()-np.nanmean(el[band]):8.2f}")

print()
print("=" * 78)
print("7. FORMAL TEST OF THE HEADLINE CLAIM")
print("=" * 78)
gap = np.median(BM) - TGT
bg = boot(BM, CL, n=40000) - TGT
lo, hi = np.percentile(bg, [2.5, 97.5])
print(f"  captured median - target      {gap:+.2f} dB  cluster-boot 95% CI "
      f"[{lo:+.2f}, {hi:+.2f}]   P(gap>=0) = {(bg >= 0).mean():.4f}")
# add excerpt-bias uncertainty as an independent normal
sim = boot(BM, CL, n=40000) - TGT - rng.normal(d.mean(), se, 40000)
lo2, hi2 = np.percentile(sim, [2.5, 97.5])
print(f"  after excerpt-bias correction {np.median(sim):+.2f} dB  95% CI "
      f"[{lo2:+.2f}, {hi2:+.2f}]   P(gap>=0) = {(sim >= 0).mean():.4f}")
print(f"  sign test: {int((BM < TGT).sum())}/13 captures darker than target, "
      f"two-sided p = {2*sum(comb(13,k) for k in range(0,14-int((BM<TGT).sum())))/2**13:.5f}"
      if (BM < TGT).sum() >= 7 else "")
