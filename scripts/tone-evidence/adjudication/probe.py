import sys, numpy as np
root = sys.argv[1]
sys.path.insert(0, root)
import shimmer.perceptual as P, shimmer.budget as B
from shimmer.eq import EqBand, EqParams, apply_eq
print("loaded:", P.__file__)
SR=48000
def _music(secs=3.0, sr=SR, seed=1):
    rng=np.random.default_rng(seed); t=np.arange(int(secs*sr))/sr
    x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))
    x+=0.02*rng.standard_normal(t.size)
    return (0.4*x/np.max(np.abs(x)))[:,None]
x=_music()
heavy=apply_eq(x,SR,EqParams(enabled=True,bands=[EqBand("high_shelf",3000.0,-12.0,0.7,True)]))
d=P.measure_damage(x,heavy,SR)
print("  -12dB/3kHz shelf   lin_dist=%.3f  missing=%.5f" % (d.lin_dist, d.missing))
b=B.estimate_budget(None,SR,flicker_excess_db=1.0)
print("  budget ceilings    lin=%.3f  sones=%.4f" % (b.lin_dist, b.sones))
y,rep=B.apply_within_budget(x,heavy,SR,b)
print("  enforcement        mix=%.3f  held_back=%s" % (rep.mix, rep.held_back))
