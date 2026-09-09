import numpy as np, sys
sys.path.insert(0, "D:/MusicVault/Tools/Shimmer")
from shimmer import budget as B
sr=44100
t=np.arange(int(sr*3))/sr
x=np.zeros_like(t)
for k in range(1,40): x += (1.0/k)*np.sin(2*np.pi*220*k*t+k)
x*=0.2/np.max(np.abs(x))
x=np.stack([x,x],axis=1).astype(np.float32)
b=B.estimate_budget(x, sr)   # no flicker passed -> evidence_scan branch
print("OK", b.as_dict())
