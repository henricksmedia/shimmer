import numpy as np, sys, time
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import perceptual as P
from shimmer.eq import EqBand, EqParams, apply_eq

def music(secs,sr,seed=1):
    rng=np.random.default_rng(seed); t=np.arange(int(secs*sr))/sr
    x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))
    x+=0.03*rng.standard_normal(t.size)
    return (0.4*x/np.max(np.abs(x)))[:,None]

print("=== same content + same EQ at different sample rates ===")
for sr in (48000, 44100, 96000, 22050):
    x=music(3.0,sr)
    y=apply_eq(x,sr,EqParams(enabled=True,bands=[EqBand("high_shelf",6000.0,-8.0,0.7,True)]))
    t0=time.time(); d=P.measure_damage(x[:,0],y[:,0],sr); dt=time.time()-t0
    print(f"  sr={sr:6d} missing={d.missing:.4f} lin_dist={d.lin_dist:8.3f} frames={d.frames} ({dt:.1f}s)")

print()
print("=== gate discontinuity around start=ceil(0.5*Fss)=24 frames ===")
sr=48000
x=music(1.0,sr)[:,0]
y=x*0.9
for nframes in (22,23,24,25,26,30):
    n=(nframes-1)*1024+2048
    d=P.measure_damage(x[:n],y[:n],sr)
    print(f"  frames={d.frames:3d} gated_frames={d.gated_frames:3d} lin_dist={d.lin_dist:7.3f}")
