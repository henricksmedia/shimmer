import json, sys, numpy as np, soundfile as sf
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB, analyze_spectrum, relative_band_levels

F = np.asarray(_REF_FREQS, float); MID = (F>=200)&(F<=2000)
AIR = (F>=2500)&(F<=12500)
def rel(v):
    v=np.asarray(v,float); return v-np.median(v[MID])

lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json"))
cap = {t["label"]: rel(t["rel_db"]) for t in lib["tracks"]}

for name in ["distrokid-leave-the-world-behind", "distrokid-algorithms-lure"]:
    x, sr = sf.read(rf"D:\MusicVault\Tools\Shimmer\sources\{name}.wav", always_2d=True)
    mono = x.mean(axis=1)
    spec = analyze_spectrum(mono, sr)
    fileref = rel(np.array(spec["rel_db"], float)) if "rel_db" in spec else None
    c = cap[name]
    d = c - fileref
    print("\n%s   file-vs-capture delta (capture minus file)" % name)
    print("  air mean: file %+.2f  capture %+.2f  delta %+.2f"
          % (fileref[AIR].mean(), c[AIR].mean(), d[AIR].mean()))
    for i, f in enumerate(F):
        if 200 <= f <= 16000:
            print("   %6.0f  file %+7.2f  cap %+7.2f  d %+6.2f" % (f, fileref[i], c[i], d[i]))
