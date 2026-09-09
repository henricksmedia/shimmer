import sys, os, numpy as np, soundfile as sf
sys.path.insert(0, r"D:/MusicVault/Tools/Shimmer")
T = r"C:/Users/jerem/AppData/Local/Temp/claude"
sr = 44100
rng = np.random.default_rng(0)
t = np.arange(int(sr*6))/sr
# music-ish bed + hiss + a bright fizz so the detector has something to chew
x = 0.25*np.sin(2*np.pi*220*t) + 0.12*np.sin(2*np.pi*440*t) + 0.02*rng.standard_normal(t.size)
x += 0.01*np.sin(2*np.pi*9000*t)*(1+0.5*np.sin(2*np.pi*7*t))
x = np.stack([x, x], axis=1).astype(np.float32)
src = os.path.join(T, "in.wav"); dst = os.path.join(T, "out.wav")
sf.write(src, x, sr)

import shimmer.server as S
import shimmer.probe as probe

# Pin the detector's pick so the run is deterministic; strength 1.25 is on
# the detector's own 0.05 quantisation grid (STRENGTH_STEP=0.05).
real = probe.suggest_preset
def fake(path, *a, **k):
    return {"preset": "vocal_glaze_plus", "strength": 1.25,
            "ranked": [{"name": "vocal_glaze_plus", "confidence": 0.8}]}
probe.suggest_preset = fake

captured = {}
real_note = S.shimmer_note
def spy_note(*a, **k):
    captured["overrides"] = k.get("overrides")
    captured["strength_arg"] = a[3] if len(a) > 3 else None
    return real_note(*a, **k)
S.shimmer_note = spy_note

res = S._batch_one(src, dst, "generic", preserve_vol=False,
                   auto_detect=True, preset_strength=0.85,
                   master_params=None, static_repair=False)
print("effective_strength stored :", res.get("effective_strength"))
print("strength passed to note   :", captured["strength_arg"])
print("overrides reported        :", len(captured["overrides"]))
for o in captured["overrides"]:
    print("   ", o)
probe.suggest_preset = real
