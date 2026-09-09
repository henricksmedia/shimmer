import json, sys, numpy as np
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB

F = np.asarray(_REF_FREQS, float)
MID = (F >= 200) & (F <= 2000)
def rel(v):
    v = np.asarray(v, float)
    return v - np.median(v[MID])

TGT = rel(_REF_SHAPE_DB)

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
rows = [np.asarray(t["rel_db"], float) for t in lib["tracks"]]
labels = [t["label"] for t in lib["tracks"]]
secs = [t["heard_seconds"] for t in lib["tracks"]]
# reproduce the gate: reject the two broken ones by 10 kHz reading
keep = [i for i, r in enumerate(rows) if r[list(F).index(10000)] > -30]
print("kept", len(keep), "rejected:", [labels[i] for i in range(len(rows)) if i not in keep])
CAP = np.array([rel(rows[i]) for i in keep])
capmed = np.median(CAP, axis=0)

tr = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\tone-reference.json"))
allrows = np.array([rel(t["rel_db"] if "rel_db" in t else t["band_db"]) for t in tr["tracks"]])
print("tone-reference tracks:", allrows.shape)
srv_all = np.median(allrows, axis=0)
neu = tr.get("neutral")
print("neutral key type:", type(neu), (len(neu) if hasattr(neu,'__len__') else neu))

# Elowsson on the grid
def elow_psd(f):
    x = 60*np.log2(f/30.0) + 1.0   # bin index; bin1=30Hz, 60 bins/oct
    y = np.where(x <= 100,
                 -0.000907*x**2 + 0.256*x - 32.942,
                 -0.000183*x**2 + 0.0213*x - 16.735)
    return y
BW = F*(2**(1/6) - 2**(-1/6))     # 0.231563*fc
ELO = rel(elow_psd(F) + 10*np.log10(BW))

AIR = (F >= 2500) & (F <= 12500)
def m(v, mask): return float(np.mean(np.asarray(v)[mask]))
print("\n2.5-12.5k means: target %.2f  captures %.2f  service_all %.2f  elowsson %.2f"
      % (m(TGT,AIR), m(capmed,AIR), m(srv_all,AIR), m(ELO,AIR)))
print("target - captures = %+.2f ; target - elowsson = %+.2f ; captures - elowsson = %+.2f"
      % (m(TGT,AIR)-m(capmed,AIR), m(TGT,AIR)-m(ELO,AIR), m(capmed,AIR)-m(ELO,AIR)))

print("\nband   target  capmed  elow   T-cap   T-elo   n_below/13")
for i, f in enumerate(F):
    if f < 630 or f > 20000: continue
    nb = int(np.sum(CAP[:, i] < TGT[i]))
    print("%6.0f %7.2f %7.2f %7.2f %+7.2f %+7.2f   %2d" % (f, TGT[i], capmed[i], ELO[i], TGT[i]-capmed[i], TGT[i]-ELO[i], nb))

for lo, hi, name in [(630,1250,"0.63-1.25k"),(1250,2500,"1.25-2.5k"),(2500,4500,"2.5-4.5k"),(5000,12500,"5-12.5k"),(63,200,"63-200"),(250,2000,"250-2k")]:
    msk = (F>=lo)&(F<=hi)
    print("%-11s T-cap %+6.2f  T-elo %+6.2f  cap-elo %+6.2f" % (name, m(TGT,msk)-m(capmed,msk), m(TGT,msk)-m(ELO,msk), m(capmed,msk)-m(ELO,msk)))

# bootstrap on the 2.5-12.5k gap vs captures
rng = np.random.default_rng(0)
per = np.array([m(c,AIR) for c in CAP])
print("\nper-capture air means:", np.round(np.sort(per),2))
bs = [np.median(per[rng.integers(0,len(per),len(per))]) for _ in range(20000)]
print("median air %.2f  95%% CI [%.2f, %.2f]  sd %.2f  se %.2f"
      % (np.median(per), np.percentile(bs,2.5), np.percentile(bs,97.5), per.std(ddof=1), per.std(ddof=1)/np.sqrt(len(per))))
print("gap target-median = %+.2f, CI [%+.2f, %+.2f]" % (m(TGT,AIR)-np.median(per), m(TGT,AIR)-np.percentile(bs,97.5), m(TGT,AIR)-np.percentile(bs,2.5)))

# invariant slope 89 Hz - 4.5 kHz in PSD terms
def psd_at(curve, f):
    c = np.asarray(curve) - 10*np.log10(BW)
    return np.interp(np.log10(f), np.log10(F), c)
def slope(curve):
    return (psd_at(curve,4500)-psd_at(curve,89))/np.log2(4500/89.0)
print("\ninvariant slope (dB/oct): target %.3f  captures %.3f  service %.3f  elowsson %.3f"
      % (slope(TGT), slope(capmed), slope(srv_all), slope(ELO)))
print("endpoint errors vs elowsson: 89Hz %+.2f dB, 4.5kHz %+.2f dB"
      % (psd_at(TGT,89)-psd_at(ELO,89), psd_at(TGT,4500)-psd_at(ELO,4500)))
msk = (F>=89)&(F<=4500)
print("RMS residual target-elowsson over 89Hz-4.5kHz bands: %.2f dB" % np.sqrt(np.mean((TGT[msk]-ELO[msk])**2)))
# per-track slope sd
st = np.array([slope(c) for c in CAP])
print("per-capture slope sd %.3f dB/oct (n=%d)" % (st.std(ddof=1), len(st)))
sa = np.array([slope(r) for r in allrows])
print("per-service-master slope sd %.3f dB/oct (n=%d)" % (sa.std(ddof=1), len(sa)))
