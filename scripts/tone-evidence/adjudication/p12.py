import numpy as np, sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import perceptual as P
from shimmer import budget as B
from shimmer.eq import EqBand, EqParams, apply_eq
SR=48000
rng=np.random.default_rng(1); t=np.arange(int(3.0*SR))/SR
x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))+0.02*rng.standard_normal(t.size)
for onset in np.arange(0.25,3.0,0.5):
    i=int(onset*SR); env=np.exp(-np.arange(SR//10)/(SR*0.01))
    x[i:i+env.size]+=0.4*env*rng.standard_normal(env.size)
x=(0.4*x/np.max(np.abs(x)))[:,None]
print("LIN_DIST_BASE (budget.py:102) =", B.LIN_DIST_BASE, " MAX_LIN_DIST =", B.MAX_LIN_DIST)
cases=[("pure gain -0.5 dB", x*10**(-0.5/20)),
       ("pure gain -1.0 dB", x*10**(-1.0/20)),
       ("pure gain -6.0 dB", x*10**(-6.0/20)),
       ("high shelf 3 kHz -12 dB", apply_eq(x,SR,EqParams(enabled=True,bands=[EqBand("high_shelf",3000.0,-12.0,0.7,True)]))),
       ("high shelf 16 kHz -12 dB", apply_eq(x,SR,EqParams(enabled=True,bands=[EqBand("high_shelf",16000.0,-12.0,0.7,True)])))]
for name,y in cases:
    d=P.measure_damage(x,y,SR)
    print(f"  {name:26s} lin_dist={d.lin_dist:8.3f}  missing={d.missing:.4f}  over LIN_DIST_BASE? {d.lin_dist>B.LIN_DIST_BASE}")
