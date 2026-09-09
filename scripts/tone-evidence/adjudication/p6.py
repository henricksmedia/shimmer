import numpy as np, sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer import budget as B
from shimmer import perceptual as P
SR=48000

print("=== is the MIN_BUDGET_SONES branch reachable? ===")
lowest=None
for e in np.arange(0.4, 3.0, 0.0005):
    b=B.estimate_budget(None,SR,flicker_excess_db=float(e))
    if b.sones>0 and (lowest is None or b.sones<lowest[1]):
        lowest=(float(e), b.sones)
print("  SONES_BASE=",B.SONES_BASE," MIN_BUDGET_SONES=",B.MIN_BUDGET_SONES)
print("  smallest non-zero budget over excess in [0.4,3.0):", lowest)
print("  -> 'too faint to act on' branch fires at least once? ",
      any("too faint" in B.estimate_budget(None,SR,flicker_excess_db=float(e)).reason
          for e in np.arange(-5,50,0.001)))

print()
print("=== the knife-edge at EXCESS_FLOOR_DB ===")
for e in (0.499, 0.4999, 0.5, 0.5001, 0.501, 0.6):
    b=B.estimate_budget(None,SR,flicker_excess_db=e)
    print(f"  flicker_excess={e:<7} sones={b.sones:.4f} lin_dist={b.lin_dist:.3f}")

print()
print("=== shape / dtype contract of apply_within_budget on 1-D mono ===")
x=(0.3*np.sin(2*np.pi*440*np.arange(2*SR)/SR)).astype(np.float64)
zero=B.estimate_budget(None,SR,flicker_excess_db=-0.28)
y,rep=B.apply_within_budget(x, x*0.5, SR, zero)
print("  input shape",x.shape,x.dtype,"-> output shape",y.shape,y.dtype)
