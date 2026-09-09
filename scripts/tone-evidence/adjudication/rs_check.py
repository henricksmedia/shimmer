import sys, os
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer"); os.chdir(r"D:\MusicVault\Tools\Shimmer")
import numpy as np
from shimmer import perceptual as P
from shimmer.eq import EqBand, EqParams, apply_eq

def music(sr, secs=3.0, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(int(secs*sr))/sr
    x = sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))
    x += 0.02*rng.standard_normal(t.size)
    return 0.4*x/np.max(np.abs(x))

for sr in (48000, 44100, 96000, 22050):
    x = music(sr)
    y = apply_eq(x[:,None], sr, EqParams(enabled=True,
        bands=[EqBand("high_shelf", 4000.0, -6.0, 0.7, True)]))[:,0]
    d = P.measure_damage(x, y, sr)
    print(f"sr={sr:6d}  missing={d.missing:.4f}  lin_dist={d.lin_dist:.3f}  added={d.added:.4f}  frames={d.frames}")
