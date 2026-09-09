import numpy as np, sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import budget as B
from shimmer import perceptual as P
SR=48000
rng=np.random.default_rng(1)
t=np.arange(int(3.0*SR))/SR
mono=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))+0.03*rng.standard_normal(t.size)
mono=0.4*mono/np.max(np.abs(mono))
side=0.25*np.random.default_rng(5).standard_normal(mono.size)
orig=np.stack([mono+side, mono-side],axis=1)
strip=np.stack([mono, mono],axis=1)
d=P.measure_damage(orig,strip,SR)
print("raw lin_dist=%r missing=%r added=%r" % (d.lin_dist,d.missing,d.added))
print("side energy removed: %.1f%% of total"
      % (100*(side**2).sum()/ (orig**2).sum()))
zero=B.estimate_budget(None,SR,flicker_excess_db=-0.28)
tiny=B.estimate_budget(None,SR,flicker_excess_db=1.0)
print("tiny budget:", tiny.as_dict(), "fits ->", tiny.fits(d))
y,rep=B.apply_within_budget(orig,strip,SR,tiny)
print("apply_within_budget -> mix=%r held_back=%r" % (rep.mix, rep.held_back))
print("returned == fully stripped?", np.allclose(y, strip.astype(np.float32)))
print("reason:", rep.reason)
