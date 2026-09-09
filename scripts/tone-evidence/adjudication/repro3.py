import sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer.presets import PRESETS
from shimmer.params import apply_preset_strength, preset_overrides

# Same run, but diff against the SAME unrounded strength the server applied.
eff = 1.25 * 0.85
p = PRESETS["vocal_glaze_plus"]()
apply_preset_strength(p, eff)
print("unrounded strength to preset_overrides ->", preset_overrides(p, "vocal_glaze_plus", eff))

# And: round BEFORE scaling (the other fix).
eff_r = round(eff, 2)
p2 = PRESETS["vocal_glaze_plus"]()
apply_preset_strength(p2, eff_r)
print("round-before-scale                     ->", preset_overrides(p2, "vocal_glaze_plus", eff_r))

# How routine is a >2-decimal product? Both grids step by 0.05.
import numpy as np
det = [round(0.25 + 0.05*i, 2) for i in range(int((2.0-0.25)/0.05)+1)]
sli = [round(0.05*i, 2) for i in range(0, 41)]
bad = tot = 0
for d in det:
    for s in sli:
        e = max(0.0, min(2.0, d*s))
        tot += 1
        if abs(e - round(e, 2)) > 1e-9:
            bad += 1
print(f"detector-grid x slider-grid pairs whose product needs >2 decimals: {bad}/{tot} = {bad/tot:.0%}")
