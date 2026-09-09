import sys, os
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer"); os.chdir(r"D:\MusicVault\Tools\Shimmer")
import numpy as np
from shimmer import budget as B

sr=44100
rng=np.random.default_rng(1); t=np.arange(int(4.0*sr))/sr
x=sum(0.3/k*np.sin(2*np.pi*220*k*t) for k in range(1,12))+0.02*rng.standard_normal(t.size)
x=(0.4*x/np.max(np.abs(x)))[:,None]
print("--- estimate_budget(x, sr) with flicker_excess_db=None (the 149-150 branch) ---")
b = B.estimate_budget(x, sr)
print(" OK ->", b.as_dict())

print("\n--- reachability of budget.py:162 (MIN_BUDGET_SONES branch) ---")
print(" SONES_BASE =", B.SONES_BASE, " MIN_BUDGET_SONES =", B.MIN_BUDGET_SONES)
worst = min(B.SONES_BASE + e*B.SONES_PER_DB for e in (1e-12, 1e-9, 1e-6))
print(f" smallest sones reachable at line 161 = {worst!r}")
print(" line 162 reachable?", worst < B.MIN_BUDGET_SONES)

print("\n--- as_dict smoke ---")
_, rep = B.apply_within_budget(x, x*0.5, sr, B.estimate_budget(None, sr, flicker_excess_db=-0.28))
print(" BudgetReport.as_dict ->", {k: rep.as_dict()[k] for k in ("mix","budget_sones","held_back")})
