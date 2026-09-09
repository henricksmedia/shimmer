import json, sys, numpy as np, soundfile as sf
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
import shimmer.mastering as M
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB, analyze_spectrum, compute_tone_curve

F = np.asarray(_REF_FREQS, float); MID=(F>=200)&(F<=2000); AIR=(F>=2500)&(F<=12500)
def rel(v):
    v=np.asarray(v,float); return v-np.median(v[MID])
TGT = rel(_REF_SHAPE_DB)

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
comm = [t for t in lib["tracks"] if not t["label"].startswith("distrokid-")]
i10 = list(F).index(10000)
kept = [t for t in comm if rel(t["rel_db"])[i10] > -30]
print("commercial rows %d, kept %d" % (len(comm), len(kept)))
CAP = np.array([rel(t["rel_db"]) for t in kept])
capmed = np.median(CAP, axis=0)
print("capture median air mean %.2f" % capmed[AIR].mean())
print("target - capmed air = %+.2f" % (TGT[AIR].mean()-capmed[AIR].mean()))
for lo,hi,n in [(1000,2000,"1-2k"),(2500,4000,"2.5-4k"),(5000,12500,"5-12.5k")]:
    m=(F>=lo)&(F<=hi); print("  %-9s %+.2f" % (n, TGT[m].mean()-capmed[m].mean()))

# what the shipped target actually delivers on Suno renders
names = ["algorithms-lure","alive-again","falling-for-you","kindling",
         "leave-the-world-behind","we-were-meant-for-the-stars",
         "couldve-been-stories","the-little-things"]
capref = capmed + 0.0
print("\nper-render delivered EQ (shipped target vs capture-derived target)")
rows=[]
for n in names:
    x,sr = sf.read(rf"D:\MusicVault\Tools\Shimmer\sources\suno-{n}.wav", always_2d=True)
    spec = analyze_spectrum(x.mean(axis=1), sr)
    meas = rel(np.array(spec["rel_db"], float))
    ask_t = TGT - meas
    dl_t = np.array(compute_tone_curve(None, sr, raw_spectrum=spec, strength=1.0))
    old = M._REF_DB.copy()
    M._REF_DB = capref - np.median(capref[MID])
    dl_c = np.array(compute_tone_curve(None, sr, raw_spectrum=spec, strength=1.0))
    M._REF_DB = old
    hb=(F>=5000)&(F<=12500)
    rows.append((n, ask_t[hb].mean(), dl_t[hb].mean(), dl_c[hb].mean(),
                 dl_t[(F>=2500)&(F<=4000)].mean(), dl_c[(F>=2500)&(F<=4000)].mean()))
    print("  %-28s ask5-12k %+6.2f  delivered %+5.2f  (capture-tgt %+5.2f) | 2.5-4k del %+5.2f vs %+5.2f"
          % rows[-1])
a=np.array([r[1:] for r in rows])
print("  MEAN                         ask %+6.2f  delivered %+5.2f  (capture %+5.2f) | %+5.2f vs %+5.2f" % tuple(a.mean(axis=0)))

# shimmer outputs vs captures
print("\nshimmer output vs capture median, air 2.5-12.5k:")
outs=[]
for n in ["algorithms-lure","alive-again","falling-for-you","kindling","leave-the-world-behind","we-were-meant-for-the-stars"]:
    x,sr=sf.read(rf"D:\MusicVault\Tools\Shimmer\sources\shimmer-{n}.wav", always_2d=True)
    s=rel(np.array(analyze_spectrum(x.mean(axis=1),sr)["rel_db"],float))
    outs.append(s[AIR].mean()); print("  %-28s %+6.2f" % (n, s[AIR].mean()))
print("  mean %+.2f  (capture median %+.2f, target %+.2f)" % (np.mean(outs), capmed[AIR].mean(), TGT[AIR].mean()))
