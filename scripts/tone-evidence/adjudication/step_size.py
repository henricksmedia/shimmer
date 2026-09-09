import sys, numpy as np
sys.path.insert(0, 'D:/MusicVault/Tools/Shimmer')
from shimmer import budget as B
from shimmer.presets import PRESETS
from shimmer.engine import process

SR = 48000
rng = np.random.default_rng(1)
t = np.arange(int(4.0 * SR)) / SR
x = sum(0.3 / k * np.sin(2 * np.pi * 220 * k * t) for k in range(1, 20))
x += 0.05 * rng.standard_normal(t.size)
x = (0.4 * x / np.max(np.abs(x))).astype(np.float32)[:, None]

y = process(x, SR, PRESETS['suno_hash']())
y = np.asarray(y, dtype=np.float32)

for exc in (0.4999, 0.5001, 1.0):
    b = B.estimate_budget(None, SR, flicker_excess_db=exc)
    out, rep = B.apply_within_budget(x, y, SR, b)
    d = rep.as_dict()
    print(f"excess={exc:<7} budget_sones={b.sones:.4f} lin={b.lin_dist:.2f} "
          f"-> mix={d['mix']:.3f} damage_before={d['damage_before']} after={d['damage_after']}")
