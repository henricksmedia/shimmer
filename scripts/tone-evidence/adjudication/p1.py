import numpy as np, sys, time
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
np.seterr(all='warn')
from shimmer import perceptual as P

SR=48000
def music(secs=3.0, sr=SR, seed=1):
    rng=np.random.default_rng(seed)
    t=np.arange(int(secs*sr))/sr
    x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))
    x+=0.02*rng.standard_normal(t.size)
    for onset in np.arange(0.25,secs,0.5):
        i=int(onset*sr); env=np.exp(-np.arange(sr//10)/(sr*0.01))
        x[i:i+env.size]+=0.4*env*rng.standard_normal(env.size)
    return 0.4*x/np.max(np.abs(x))

x=music()
print("identity:", P.measure_damage(x,x.copy(),SR).as_dict())
for g_db in (-0.1,-0.5,-1.0,-3.0,-6.0):
    g=10**(g_db/20)
    d=P.measure_damage(x, x*g, SR)
    print(f"pure gain {g_db:+.1f} dB -> lin_dist={d.lin_dist:.3f} missing={d.missing:.4f} added={d.added:.4f}")
