import numpy as np, sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import budget as B
from shimmer import perceptual as P
SR=48000
rng=np.random.default_rng(1); t=np.arange(int(3.0*SR))/SR
x=(sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))+0.03*rng.standard_normal(t.size))
x=(0.4*x/np.max(np.abs(x)))[:,None]
bad=x.copy(); bad[SR]=np.nan
d=P.measure_damage(x,bad,SR)
print("one NaN sample in `cleaned`:", d.as_dict())
b=B.estimate_budget(None,SR,flicker_excess_db=1.0)
print("  fits() ->", b.fits(d))
y,rep=B.apply_within_budget(x,bad,SR,b)
print("  apply_within_budget mix=",rep.mix," NaNs in output:",int(np.isnan(y).sum()))
print("  reason:", rep.reason[:90])
