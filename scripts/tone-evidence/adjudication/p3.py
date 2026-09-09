import numpy as np, sys, time
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import perceptual as P
SR=48000
rng=np.random.default_rng(1)
def music(secs):
    t=np.arange(int(secs*SR))/SR
    x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))
    x+=0.02*rng.standard_normal(t.size)
    return 0.4*x/np.max(np.abs(x))
for secs in (3.0, 10.0):
    x=music(secs); y=x*0.98
    t0=time.time(); P.measure_damage(x,y,SR); dt=time.time()-t0
    print(f"{secs:5.1f}s audio -> measure_damage {dt:6.2f}s  ({dt/secs:5.2f}x realtime-ratio)")
print("extrapolated for a 4-minute track: %.1f s per call, %.1f s for the 7 calls apply_within_budget makes"
      % (dt/secs*240, dt/secs*240*7))
