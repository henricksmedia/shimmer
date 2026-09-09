import numpy as np, sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import budget as B
SR=48000
rng=np.random.default_rng(1); t=np.arange(int(6.0*SR))/SR
x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))+0.03*rng.standard_normal(t.size)
x=(0.4*x/np.max(np.abs(x)))[:,None]
try:
    b=B.estimate_budget(x, SR)
    print("estimate_budget(x, sr) ->", b.as_dict())
except Exception as e:
    print("RAISED", type(e).__name__, e)
# short clip
try:
    b=B.estimate_budget(x[:1000], SR)
    print("short clip ->", b.as_dict())
except Exception as e:
    print("short clip RAISED", type(e).__name__+":", e)
