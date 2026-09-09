import sys, os
sys.path.insert(0, r"D:\MusicVault\Tools\Shimmer")
from shimmer.tags import read_tags
from shimmer.audio_io import load_audio
from shimmer.mastering import measure_loudness, measure_true_peak_db

B = r"D:\MusicVault\The Treq\albums\The Fifth Direction"
song = "Cedar After Rain.wav"
for sub in ("suno", "shimmer 1", "shimmer"):
    p = os.path.join(B, sub, song)
    t = read_tags(p) or {}
    x, sr = load_audio(p)
    L = measure_loudness(x, sr)
    c = (t.get("comment") or "")[:100]
    print(f"{sub:10s} LUFS {L['lufs_i']:7.2f}  TP {measure_true_peak_db(x, sr):6.2f}")
    print(f"           tag: {c or '(none)'}")
