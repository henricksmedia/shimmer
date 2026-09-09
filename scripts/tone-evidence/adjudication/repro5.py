import sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer.presets import PRESETS
from shimmer.params import apply_preset_strength, preset_overrides
def n_spurious(preset, d, s):
    eff = max(0.0, min(2.0, d*s)); p = PRESETS[preset]()
    if abs(eff-1.0) > 1e-6: apply_preset_strength(p, eff)
    return len(preset_overrides(p, preset, round(eff, 2)))
print("slider at default 1.00, detected 1.25 :", n_spurious("vocal_glaze_plus", 1.25, 1.00))
print("slider 0.85,            detected 1.25 :", n_spurious("vocal_glaze_plus", 1.25, 0.85))
print("slider 0.90,            detected 1.25 :", n_spurious("vocal_glaze_plus", 1.25, 0.90))
print("slider 0.95,            detected 1.15 :", n_spurious("vocal_glaze_plus", 1.15, 0.95))
print("slider 1.10,            detected 0.70 :", n_spurious("vocal_glaze_plus", 0.70, 1.10))
