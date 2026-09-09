"""Audit item 4.3: is measure_damage reproducible across processes?

One panelist reported a 57x spread in lin_dist across identical invocations on
byte-identical input, suggesting denormal sensitivity. Two others got stable
results. At least one of those runs was against the mutated file, so this may
be contamination — but if it is real, every absolute threshold in budget.py is
meaningless. Run in a FRESH process each time and print the values.
"""
import sys
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
import numpy as np
from shimmer import perceptual as P
from shimmer.eq import EqBand, EqParams, apply_eq

SR = 48000
rng = np.random.default_rng(1)
t = np.arange(int(3.0 * SR)) / SR
x = sum(0.3 / k * np.sin(2 * np.pi * 220 * k * t) for k in range(1, 12))
x += 0.02 * rng.standard_normal(t.size)
for onset in np.arange(0.25, 3.0, 0.5):
    i = int(onset * SR)
    env = np.exp(-np.arange(SR // 10) / (SR * 0.01))
    x[i:i + env.size] += 0.4 * env * rng.standard_normal(env.size)
x = (0.4 * x / np.max(np.abs(x)))[:, None]
y = apply_eq(x, SR, EqParams(enabled=True,
                             bands=[EqBand("high_shelf", 3000.0, -12.0, 0.7, True)]))
d = P.measure_damage(x, y, SR)
print(f"{d.lin_dist:.6f} {d.missing:.6f} {d.added:.6f}")
