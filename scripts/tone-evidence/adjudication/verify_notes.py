"""Reproduce the audit's two shipping defects and confirm they are gone."""
import sys
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.params import preset_overrides, apply_preset_strength
from shimmer.presets import PRESETS, get_preset

print("2E — server-set cutoff_hz must not appear as a user tweak")
p = get_preset("generic")
print("   stock generic, untouched          :", preset_overrides(p, "generic", 1.0))
p.cutoff_hz = 16193.0                      # what the server sets from analysis
print("   after server sets cutoff_hz=16193 :", preset_overrides(p, "generic", 1.0))

print()
print("2F — unrounded scaling diffed against a rounded baseline")
exact = 1.0625
rounded = round(exact, 2)
p2 = get_preset("vocal_glaze_plus")
apply_preset_strength(p2, exact)           # what the pipeline actually applies
print(f"   applied {exact}, diffed vs {rounded}   :",
      len(preset_overrides(p2, "vocal_glaze_plus", rounded)), "entries (was 12)")
print(f"   applied {exact}, diffed vs {exact} :",
      preset_overrides(p2, "vocal_glaze_plus", exact))

print()
print("a genuine tweak is still reported")
p3 = get_preset("suno_hash")
p3.deharsh = 0.66
p3.cutoff_hz = 16193.0
print("   deharsh moved + analysis field set:", preset_overrides(p3, "suno_hash", 1.0))
