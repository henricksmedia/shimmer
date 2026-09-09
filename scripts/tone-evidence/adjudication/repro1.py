import sys
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
from shimmer.presets import PRESETS
from shimmer.params import apply_preset_strength, preset_overrides

def sim(preset, detected, slider):
    eff = max(0.0, min(2.0, detected * slider))
    eff_r = round(eff, 2)
    p = PRESETS[preset]()
    if abs(eff - 1.0) > 1e-6:
        apply_preset_strength(p, eff)      # what the server applies (unrounded)
    ov = preset_overrides(p, preset, eff_r)  # what the note diffs against (rounded)
    return eff, eff_r, ov

for preset, d, s in [("vocal_glaze_plus", 1.25, 0.85),
                     ("generic", 1.25, 0.85),
                     ("air_brittle", 0.95, 0.85),
                     ("broadband_fizz", 1.15, 0.75),
                     ("checkerboard_grid", 1.10, 0.95),
                     ("cymbal_chatter", 0.65, 1.05)]:
    if preset not in PRESETS:
        print("MISSING preset", preset); continue
    eff, eff_r, ov = sim(preset, d, s)
    print(f"{preset:20s} detected={d} slider={s} eff={eff!r} rounded={eff_r}  spurious={len(ov)}")
    print("   ", ov)
