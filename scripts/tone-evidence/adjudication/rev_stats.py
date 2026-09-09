"""Excerpt bias, re-done duration-matched; and a real confidence interval."""
import glob
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.audio_io import load_audio
from shimmer.mastering import (_REF_FREQS, _REF_SHAPE_DB, analyze_spectrum,
                               relative_band_levels)

rng = np.random.default_rng(0)
f = np.asarray(_REF_FREQS, float)
band = (f >= 2500) & (f <= 12500)
TGT = _REF_SHAPE_DB[band].mean()


def curve(x, sr):
    return relative_band_levels(
        np.array(analyze_spectrum(np.ascontiguousarray(x), sr)["band_power_db"]))


# ---------------------------------------------------------------- captures
lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json",
                     encoding="utf-8"))
rows = lib["tracks"]
i10, i16 = 25, 27


def gate(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


kept = [(t["label"], np.array(t["rel_db"], float), t["heard_seconds"])
        for t in rows if gate(np.array(t["rel_db"], float))]
v = np.array([c[band].mean() for _, c, _ in kept])
secs = np.array([s for _, _, s in kept])
print(f"kept {len(kept)} captures; heard_seconds {secs.min():.0f}-{secs.max():.0f} "
      f"(median {np.median(secs):.0f})")
print(f"2.5-12.5 kHz mean per track: min {v.min():.2f} max {v.max():.2f} "
      f"sd {v.std(ddof=1):.2f}")
print(f"median {np.median(v):+.2f}   mean {v.mean():+.2f}   target {TGT:+.2f}")

# --------------------------------------------- excerpt bias, duration-matched
files = sorted(glob.glob(r"D:\MusicVault\Tools\Shimmer\sources\distrokid-*.wav"))
DUR = float(np.median(secs))
print(f"\nExcerpt bias, opening {DUR:.0f} s (the captures' median) vs whole:")
b30, bdur, bany = [], [], []
for p in files:
    x, sr = load_audio(p)
    w = curve(x, sr)[band].mean()
    o30 = curve(x[:int(30 * sr)], sr)[band].mean()
    od = curve(x[:int(DUR * sr)], sr)[band].mean()
    # every window of length DUR, to bound where a listener could have started
    n = int(DUR * sr)
    ws = [curve(x[s:s + n], sr)[band].mean()
          for s in range(0, max(1, x.shape[0] - n), n)]
    name = p.rsplit("\\", 1)[-1][10:-4]
    print(f"  {name:<32} whole {w:6.2f}  0-30s {o30-w:+6.2f}  "
          f"0-{DUR:.0f}s {od-w:+6.2f}  any-window sd {np.std(ws, ddof=1):5.2f}")
    b30.append(o30 - w)
    bdur.append(od - w)
    bany.extend([q - w for q in ws])
b30, bdur, bany = np.array(b30), np.array(bdur), np.array(bany)
for nm, b in (("opening 30 s", b30), (f"opening {DUR:.0f} s", bdur)):
    se = b.std(ddof=1) / np.sqrt(len(b))
    print(f"  {nm:<16} mean {b.mean():+.2f} dB, sd {b.std(ddof=1):.2f}, "
          f"se {se:.2f}, 95% CI [{b.mean()-1.96*se:+.2f},{b.mean()+1.96*se:+.2f}]")
print(f"  all {len(bany)} windows of {DUR:.0f}s: mean {bany.mean():+.2f}, "
       f"sd {bany.std(ddof=1):.2f}")

# ------------------------------------------------------------------- the CI
BIAS = bdur.mean()
BIAS_SE = bdur.std(ddof=1) / np.sqrt(len(bdur))
gap_raw = np.median(v) - TGT
print(f"\nGap, uncorrected (median): {gap_raw:+.2f} dB")

# bootstrap the median of the 13
bs = np.array([np.median(rng.choice(v, len(v), replace=True)) for _ in range(20000)])
lo, hi = np.percentile(bs - TGT, [2.5, 97.5])
print(f"  bootstrap 95% CI on the median gap: [{lo:+.2f}, {hi:+.2f}]")
bsm = np.array([rng.choice(v, len(v), replace=True).mean() for _ in range(20000)])
lo2, hi2 = np.percentile(bsm - TGT, [2.5, 97.5])
print(f"  bootstrap 95% CI on the MEAN gap:   [{lo2:+.2f}, {hi2:+.2f}]  "
      f"(point {v.mean()-TGT:+.2f})")

# cluster by artist -- 3 ODESZA, 2 Empire of the Sun
art = [lab.split(" \u2014 ")[0] for lab, _, _ in kept]
uniq = sorted(set(art))
print(f"  {len(uniq)} distinct artists among {len(kept)} tracks: "
      + ", ".join(f"{a.split()[0]}x{art.count(a)}" for a in uniq if art.count(a) > 1))
groups = [v[[i for i, a in enumerate(art) if a == u]] for u in uniq]
bsc = []
for _ in range(20000):
    pick = [groups[i] for i in rng.integers(0, len(groups), len(groups))]
    bsc.append(np.median(np.concatenate(pick)))
lo3, hi3 = np.percentile(np.array(bsc) - TGT, [2.5, 97.5])
print(f"  artist-clustered bootstrap 95% CI:  [{lo3:+.2f}, {hi3:+.2f}]")

# propagate the excerpt correction
tot_se = np.sqrt((np.std(bs) ** 2) + BIAS_SE ** 2)
corr = gap_raw - BIAS
print(f"\nCorrected for the {BIAS:+.2f} dB excerpt bias: {corr:+.2f} dB")
print(f"  combined se {tot_se:.2f} -> 95% CI [{corr-1.96*tot_se:+.2f}, "
      f"{corr+1.96*tot_se:+.2f}]")
print(f"  P(true gap darker than -3 dB) is what the claim needs; "
      f"z = {(corr+3.0)/tot_se:+.2f}")

# ------------------------------------------------- level vs brightness
M = np.array([-120.0 - np.array(t["rel_db"], float)[1] for t in rows])
B = np.array([np.array(t["rel_db"], float)[band].mean() for t in rows])
keepmask = np.array([gate(np.array(t["rel_db"], float)) for t in rows])
print(f"\nRecovered capture level vs brightness:")
print(f"  all 15: r = {np.corrcoef(M, B)[0,1]:+.3f}")
print(f"  13 kept: r = {np.corrcoef(M[keepmask], B[keepmask])[0,1]:+.3f}")
print(f"  kept level range {M[keepmask].min():.1f}-{M[keepmask].max():.1f} dB; "
      f"rejects {sorted(np.round(M[~keepmask],1))}")
