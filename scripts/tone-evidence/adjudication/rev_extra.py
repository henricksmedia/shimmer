"""Odds and ends: duration vs brightness, leave-one-out, and what the target
would have to be for the captures to agree."""
import json
import sys

import numpy as np

sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.mastering import _REF_FREQS, _REF_SHAPE_DB

f = np.asarray(_REF_FREQS, float)
band = (f >= 2500) & (f <= 12500)
TGT = _REF_SHAPE_DB[band].mean()
lib = json.load(open(r"D:\MusicVault\Tools\Shimmer\docs\reference-library.json",
                     encoding="utf-8"))
i10, i16 = 25, 27


def gate(c):
    m = (f >= 4000) & (f <= 16000)
    return (c[i10] >= -29.1 and c[i16] >= -40.1
            and float(np.polyfit(np.log2(f[m]), c[m], 1)[0]) >= -14.0)


kept = [(t["label"].split(" \u2014 ")[0], np.array(t["rel_db"], float),
         t["heard_seconds"]) for t in lib["tracks"]
        if gate(np.array(t["rel_db"], float))]
v = np.array([c[band].mean() for _, c, _ in kept])
s = np.array([x for _, _, x in kept])
print(f"brightness vs heard_seconds: r = {np.corrcoef(v, s)[0,1]:+.3f} (n={len(v)})")
print(f"  <=35 s (n={(s<=35).sum()}): median {np.median(v[s<=35]):+.2f}   "
      f">35 s (n={(s>35).sum()}): median {np.median(v[s>35]):+.2f}")

print("\nleave-one-out median gap:")
for i, (a, _, _) in enumerate(kept):
    m = np.median(np.delete(v, i)) - TGT
    print(f"  drop {a[:26]:<28} {m:+.2f}")

print(f"\n10%-trimmed mean gap: "
      f"{np.mean(np.sort(v)[1:-1]) - TGT:+.2f}")
print(f"electronic-only (ODESZA/EotS/deadmau5/Devault/HENGE/Younger): ", end="")
el = [i for i, (a, _, _) in enumerate(kept)
      if a.split()[0] in {"ODESZA", "Empire", "deadmau5", "Devault", "HENGE",
                          "Younger"}]
ot = [i for i in range(len(kept)) if i not in el]
print(f"n={len(el)} median {np.median(v[el])-TGT:+.2f}; "
      f"rest n={len(ot)} median {np.median(v[ot])-TGT:+.2f}")

print("\nper-band captured median minus shipped target:")
C = np.array([c for _, c, _ in kept])
for i, hz in enumerate(f):
    if hz < 1000 or hz > 20000:
        continue
    d = np.median(C[:, i]) - _REF_SHAPE_DB[i]
    sd = C[:, i].std(ddof=1)
    print(f"  {hz:7.0f}  captured {np.median(C[:,i]):7.2f}  target "
          f"{_REF_SHAPE_DB[i]:7.2f}  diff {d:+7.2f}  (track sd {sd:5.2f}, "
          f"se {sd/np.sqrt(len(C)):4.2f})")
