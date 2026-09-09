import numpy as np, sys
sys.path.insert(0, "D:/MusicVault/Tools/Shimmer")
from shimmer import perceptual as P
from shimmer import eq as E

def tone(sr, dur=2.0):
    t = np.arange(int(sr*dur))/sr
    x = np.zeros_like(t)
    for k in range(1, 40):
        x += (1.0/k)*np.sin(2*np.pi*220*k*t + k)
    x *= 0.1/np.max(np.abs(x))*3
    return np.stack([x, x], axis=1).astype(np.float32)

for sr in (48000, 44100):
    x = tone(sr)
    # crude high shelf cut via FFT to avoid depending on eq API
    X = np.fft.rfft(x[:,0]); f = np.fft.rfftfreq(len(x), 1/sr)
    g = np.where(f > 8000, 10**(-6/20), 1.0)
    y0 = np.fft.irfft(X*g, n=len(x))
    y = np.stack([y0, y0], axis=1).astype(np.float32)
    d = P.measure_damage(x, y, sr)
    print(sr, "missing=%.5f lin_dist=%.4f added=%.5f" % (d.missing, d.lin_dist, d.added))
    d0 = P.measure_damage(x, x.copy(), sr)
    print(sr, "identity ->", "missing=%.6f lin_dist=%.6f" % (d0.missing, d0.lin_dist))
