import numpy as np, sys, warnings
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import perceptual as P
SR=48000
def tone(f,secs=1.0,amp=1.0):
    t=np.arange(int(secs*SR))/SR
    return amp*np.sin(2*np.pi*f*t)

print("hann gain GL =", P._hann_gain())
lo=P.loudness(P.excitation_patterns(tone(1019.5,amp=1.0),SR)[1])
print("full-scale 1019.5 Hz sine loudness (sones):", float(np.median(lo)),
      " (a 92 dB SPL 1 kHz tone is ~37 sones by 2**((92-40)/10))")

# --- overload / very loud input: NaN / Inf ? ---
with warnings.catch_warnings():
    warnings.simplefilter("error")
    for amp in (1.0, 10.0, 100.0, 1000.0):
        try:
            eu,es=P.excitation_patterns(tone(1000.0,amp=amp),SR)
            print(f"amp={amp:7.1f} maxE={es.max():.3e} finite={np.isfinite(es).all()}")
        except Exception as e:
            print(f"amp={amp:7.1f} RAISED {type(e).__name__}: {e}")

# --- effect of the 1e-30 early break in _spread ---
import shimmer.perceptual as PP
b=PP.bands()
def spread_nobreak(e,b,norm):
    n,dz=b.n,b.dz; e_pow=0.4
    a_l=10.0**(-2.7*dz); a_uc=10.0**((-2.4-23.0/b.fc)*dz)
    a_uce=a_uc*np.power(np.maximum(e,PP.E_MIN),0.2*dz)
    m=np.arange(n)
    g_il=(1.0-a_l**(m+1))/(1.0-a_l)
    g_iu=np.where(np.abs(a_uce-1.0)<1e-12,(n-m).astype(float),(1.0-a_uce**(n-m))/(1.0-a_uce))
    en=e/(g_il+g_iu-1.0); ene=np.power(np.maximum(en,0.0),e_pow)
    a_uce_e=np.power(a_uce,e_pow)
    es=np.zeros(n); a_le=a_l**e_pow; acc=0.0
    for i in range(n-1,-1,-1):
        acc=a_le*acc+ene[i]; es[i]=acc
    for i in range(n-1):
        r=ene[i]; a=a_uce_e[i]
        for j in range(i+1,n):
            r*=a; es[j]+=r          # NO break
    es=np.power(es,1.0/e_pow)
    return es if norm is None else es/norm
norm=PP._spread_norm(b)
rng=np.random.default_rng(0)
worst=0.0
for trial in range(5):
    e=10.0**(rng.uniform(-2,9,b.n))
    a=PP._spread(e,b,norm); c=spread_nobreak(e,b,norm)
    rel=np.max(np.abs(a-c)/np.maximum(np.abs(c),1e-300))
    worst=max(worst,rel)
print("max relative change from the 1e-30 early break over 5 random patterns:", worst)
