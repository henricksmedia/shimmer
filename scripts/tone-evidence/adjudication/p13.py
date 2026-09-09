import numpy as np, sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import perceptual as P
from shimmer import budget as B
from shimmer.eq import EqBand, EqParams, apply_eq
SR=48000
rng=np.random.default_rng(1); t=np.arange(int(3.0*SR))/SR
x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))+0.03*rng.standard_normal(t.size)
x=(0.4*x/np.max(np.abs(x)))[:,None]
heavy=apply_eq(x,SR,EqParams(enabled=True,bands=[EqBand("high_shelf",3000.0,-12.0,0.7,True)]))
bad=0
for e in (0.6, 1.0, 2.0, 5.0, 20.0):
    b=B.estimate_budget(None,SR,flicker_excess_db=e)
    y,rep=B.apply_within_budget(x,heavy,SR,b)
    d=P.measure_damage(x.astype(np.float32),y,SR)     # re-measure the RETURNED audio
    ok=b.fits(d)
    bad += (not ok)
    print(f" excess={e:5.1f} mix={rep.mix:.3f} returned-audio missing={d.missing:.4f}<={b.sones:.3f} "
          f"lin={d.lin_dist:.3f}<={b.lin_dist:.3f}  ceilings honoured={ok}")
print("violations:", bad)
