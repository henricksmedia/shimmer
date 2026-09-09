import numpy as np, sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import perceptual as P
from shimmer import budget as B
from shimmer.eq import EqBand, EqParams, apply_eq
SR=48000
def music(secs=3.0,seed=1):
    rng=np.random.default_rng(seed); t=np.arange(int(secs*SR))/SR
    x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))
    x+=0.03*rng.standard_normal(t.size)
    for onset in np.arange(0.25,secs,0.5):
        i=int(onset*SR); env=np.exp(-np.arange(SR//10)/(SR*0.01))
        x[i:i+env.size]+=0.4*env*rng.standard_normal(env.size)
    return (0.4*x/np.max(np.abs(x)))[:,None]
x=music()

print("=== monotonicity of damage in mix (high shelf 3k -12 dB) ===")
heavy=apply_eq(x,SR,EqParams(enabled=True,bands=[EqBand("high_shelf",3000.0,-12.0,0.7,True)]))
for m in (0.0,0.125,0.25,0.375,0.5,0.625,0.75,0.875,1.0):
    d=P.measure_damage(x, x+m*(heavy-x), SR)
    print(f"  mix={m:5.3f} missing={d.missing:.4f} lin_dist={d.lin_dist:8.3f} added={d.added:.4f}")

print()
print("=== does `missing` see a top-octave strip? (this is the reported failure) ===")
for f,g in ((3000,-12),(8000,-12),(12000,-12),(16000,-12),(16000,-24)):
    y=apply_eq(x,SR,EqParams(enabled=True,bands=[EqBand("high_shelf",float(f),float(g),0.7,True)]))
    d=P.measure_damage(x,y,SR)
    print(f"  high_shelf {f:6d} Hz {g:+4d} dB -> missing={d.missing:.4f} lin_dist={d.lin_dist:8.3f}")
