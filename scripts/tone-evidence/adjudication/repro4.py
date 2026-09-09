import sys, os, numpy as np, soundfile as sf
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
T = r"C:/Users/jerem/AppData/Local/Temp/claude"
sr = 44100
rng = np.random.default_rng(0)
t = np.arange(int(sr*6))/sr
x = 0.25*np.sin(2*np.pi*220*t) + 0.12*np.sin(2*np.pi*440*t) + 0.02*rng.standard_normal(t.size)
x += 0.01*np.sin(2*np.pi*9000*t)*(1+0.5*np.sin(2*np.pi*7*t))
x = np.stack([x, x], axis=1).astype(np.float32)
src = os.path.join(T, "in.wav"); dst = os.path.join(T, "out2.wav")
sf.write(src, x, sr)

import shimmer.server as S, shimmer.probe as probe
from shimmer.params import MasterParams
probe.suggest_preset = lambda path, *a, **k: {
    "preset": "vocal_glaze_plus", "strength": 1.25,
    "ranked": [{"name": "vocal_glaze_plus", "confidence": 0.8}]}

notes = {}
real_note = S.shimmer_note
S.shimmer_note = lambda *a, **k: notes.setdefault("n", real_note(*a, **k))

mp = MasterParams(enabled=True, target_lufs=-14.0, ceiling_dbtp=-1.0)
S._batch_one(src, dst, "generic", preserve_vol=False, auto_detect=True,
             preset_strength=0.85, master_params=mp, static_repair=False)
print("BATCH NOTE:\n ", notes["n"])

# --- album pass 1 ---
S.shimmer_note = real_note
info = S._album_clean_one(src, os.path.join(T, "alb.wav"), "generic",
                          auto_detect=True, preset_strength=0.85,
                          master_params=mp, eq_params=None,
                          static_repair=False, auto_eq=False, tone_family="neutral")
print("\nALBUM overrides carried to pass 2:", len(info["overrides"]))
print(" ", info["overrides"])
