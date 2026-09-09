import numpy as np, sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import budget as B
from shimmer import perceptual as P
SR=48000
def music(secs=3.0,seed=1,sr=SR):
    rng=np.random.default_rng(seed); t=np.arange(int(secs*sr))/sr
    x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))
    x+=0.03*rng.standard_normal(t.size)
    return (0.4*x/np.max(np.abs(x)))[:,None]

x=music()
rng=np.random.default_rng(11)
# a "cleaner" that only ADDS: broadband hiss at -34 dBFS, plainly audible
noisy=x+0.02*rng.standard_normal(x.shape)
b=B.estimate_budget(None,SR,flicker_excess_db=1.0)
y,rep=B.apply_within_budget(x,noisy,SR,b)
d=P.measure_damage(x,noisy,SR)
print("added-only 'cleaning' (0.02 rms hiss):", d.as_dict())
print("  budget:", b.as_dict())
print("  fits() ->", b.fits(d), " report mix:", rep.mix, " held_back:", rep.held_back)
print("  returned == the noisy signal?", np.allclose(y,noisy))
print("  reason:", rep.reason)

print()
print("=== stereo: budget enforcement on a side-only strip ===")
mono=music()[:,0]
side=0.25*np.random.default_rng(5).standard_normal(mono.size)
orig=np.stack([mono+side, mono-side],axis=1)
strip=np.stack([mono, mono],axis=1)          # side content removed entirely
zero=B.estimate_budget(None,SR,flicker_excess_db=-0.28)   # NO artifact at all
d2=P.measure_damage(orig,strip,SR)
print("  damage of removing 100% of the side channel:", d2.as_dict())
big=B.Budget(sones=1e-9, lin_dist=1e-9, flicker_excess_db=0.0, reason="x")
print("  even a 1e-9 budget says fits() ->", big.fits(d2))
