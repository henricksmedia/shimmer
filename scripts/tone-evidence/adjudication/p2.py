import numpy as np, sys, warnings
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
warnings.simplefilter("error", RuntimeWarning)
from shimmer import perceptual as P
SR=48000
def music(secs=3.0, sr=SR, seed=1):
    rng=np.random.default_rng(seed)
    t=np.arange(int(secs*sr))/sr
    x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))
    x+=0.02*rng.standard_normal(t.size)
    return 0.4*x/np.max(np.abs(x))
x=music()

# --- 1. stereo: change ONLY the side signal -----------------------------
st=np.stack([x,x],axis=1)                     # mono-in-stereo
rng=np.random.default_rng(9)
side=0.3*rng.standard_normal(x.size)          # big, plainly audible
st2=np.stack([x+side, x-side],axis=1)         # identical mono downmix
d=P.measure_damage(st, st2, SR)
print("side-only change (L+s, R-s), s rms=%.3f:" % np.sqrt((side**2).mean()), d.as_dict())
print("  downmix identical?", np.allclose(st.mean(1), st2.mean(1)))

# --- 2. one channel muted ------------------------------------------------
st3=np.stack([x, np.zeros_like(x)],axis=1)
print("right channel muted:", P.measure_damage(st, st3, SR).as_dict())

# --- 3. silence / DC ------------------------------------------------------
z=np.zeros(SR*2)
print("silence vs silence:", P.measure_damage(z,z,SR).as_dict())
print("silence vs music   :", P.measure_damage(z,x,SR).as_dict())
dc=np.full(SR*2, 0.5)
print("DC vs DC*0.5       :", P.measure_damage(dc,dc*0.5,SR).as_dict())

# --- 4. short input -------------------------------------------------------
for n in (0, 1, 2047, 2048, 5000, 24*1024, 25*1024):
    d=P.measure_damage(x[:n] if n else np.zeros(0), (x[:n]*0.9) if n else np.zeros(0), SR)
    print(f"  len={n:6d} frames={d.frames:4d} gated={d.gated_frames:4d} lin={d.lin_dist:.4f}")
