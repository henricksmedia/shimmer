"""
make_codec_case.py — The real-codec test case for the Shimmer card
(docs/SHIMMER-RESEARCH.md, step zero; docs/STEP6-FIXES.md).

Every test model so far adds noise on top of an intact song. The research
thinks real shimmer is different: detail the AI's audio decoder rebuilt
coarsely. Suno's decoder is private, but its earlier speech model used an
open one of the same kind (EnCodec). So: take clean masters, squeeze them
through EnCodec at low bitrates, and the damage is known exactly, because the
clean original is right there.

For each song (loudest 20 s at 48 kHz, stereo) this writes, under
listening-test/codec/<song>/:

  original.wav            the clean master
  encodec-<kbps>k.wav     through EnCodec 48 kHz at each bitrate
  diff-<kbps>k.wav        what the codec changed (codec minus original)

and one blind set per song (shimmer/abtest.py) with the original and each
bitrate, for listening question 1: "does this sound like Suno shimmer?"

Two passes, because the codec needs torch and the bench needs the project's
own libraries:

  1. The codec pass, in the stems Python (torch, and `encodec` installed
     with the author's permission, 2026-09-13):
         .venv-stems\\Scripts\\python.exe
             scripts/make_codec_case.py [--kbps 3,6,12] [--songs a.wav,b.wav]
  2. The sets, in the project's Python:
         .venv\\Scripts\\python.exe scripts/make_codec_case.py --sets-only

The codec itself never ships in Shimmer: it makes test material only.
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

OUT = os.path.join(ROOT, "listening-test", "codec")
SR = 48000
SECONDS = 20.0
DEFAULT_SONGS = ["sources/distrokid-alive-again.wav", "assets/reference/reference-hey.wav",
                 "sources/distrokid-falling-for-you.wav",
                 "sources/distrokid-leave-the-world-behind.wav",
                 "sources/distrokid-we-were-meant-for-the-stars.wav"]


def _load(path):
    import soundfile as sf
    from scipy.signal import resample_poly
    from make_listening_test import loudest_excerpt
    x, sr = sf.read(path, always_2d=True, dtype="float32")
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    x = x[:, :2]
    if sr != SR:
        g = np.gcd(int(sr), SR)
        x = resample_poly(x, SR // g, int(sr) // g, axis=0).astype(np.float32)
    return loudest_excerpt(x, SR, SECONDS).astype(np.float32)


def _codec(x, model, kbps):
    """x (n, 2) float32 at 48 kHz through EnCodec at `kbps`, same length."""
    import torch
    model.set_target_bandwidth(float(kbps))
    wav = torch.from_numpy(np.ascontiguousarray(x.T))[None]          # (1, 2, n)
    with torch.no_grad():
        frames = model.encode(wav)
        y = model.decode(frames)[0].numpy().T
    n = x.shape[0]
    y = y[:n] if y.shape[0] >= n else np.pad(y, ((0, n - y.shape[0]), (0, 0)))
    return y.astype(np.float32)


def build_sets() -> list:
    """One blind set per song folder under listening-test/codec/."""
    import soundfile as sf
    from shimmer import abtest
    made = []
    for d in sorted(glob.glob(os.path.join(OUT, "*", "original.wav"))):
        folder = os.path.dirname(d)
        name = os.path.basename(folder)
        x, sr = sf.read(d, always_2d=True, dtype="float32")
        arms = [("original", x, sr)]
        coded = sorted(glob.glob(os.path.join(folder, "encodec-*.wav")),
                       key=lambda p: float(os.path.basename(p)[8:-5].rstrip("k")))
        for p in coded:
            y, ysr = sf.read(p, always_2d=True, dtype="float32")
            arms.append((os.path.basename(p)[:-4], y, ysr))
        rates = ", ".join(os.path.basename(p)[8:-5] + "bps" for p in coded)
        m = abtest.build(f"codec-{name}"[:80], f"Through an AI codec: {name}", arms, sr,
                         note=f"The clean master, and the same 20 s through EnCodec 48 kHz "
                              f"at {rates}.",
                         seed=11,
                         question="Which of these has the fizzy, flickering top you hear in "
                                  "Suno songs?",
                         tie_label="None of them")
        made.append(m.get("id"))
        print(f"built {m.get('id')}", flush=True)
    return made


def main(argv):
    def opt(flag, default=None):
        return argv[argv.index(flag) + 1] if flag in argv else default
    if "--sets-only" in argv:
        made = build_sets()
        print("sets:", ", ".join(str(m) for m in made))
        return 0
    kbps = [float(k) for k in (opt("--kbps") or "3,6,12").split(",")]
    songs = (opt("--songs").split(",") if opt("--songs") else DEFAULT_SONGS)
    try:
        from encodec import EncodecModel
    except ImportError:
        print("encodec is not installed. It is installed only with the author's "
              "permission (docs/STEP6-FIXES.md).")
        return 2
    import soundfile as sf
    model = EncodecModel.encodec_model_48khz()
    model.eval()
    for rel in songs:
        path = rel if os.path.isabs(rel) else os.path.join(ROOT, rel)
        name = os.path.splitext(os.path.basename(path))[0]
        x = _load(path)
        d = os.path.join(OUT, name)
        os.makedirs(d, exist_ok=True)
        sf.write(os.path.join(d, "original.wav"), x, SR, subtype="FLOAT")
        for k in kbps:
            y = _codec(x, model, k)
            tag = f"{k:g}k"
            sf.write(os.path.join(d, f"encodec-{tag}.wav"), y, SR, subtype="FLOAT")
            sf.write(os.path.join(d, f"diff-{tag}.wav"), y - x, SR, subtype="FLOAT")
            print(f"{name}: EnCodec {tag}bps written", flush=True)
    with open(os.path.join(OUT, "made.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"kbps": kbps, "songs": songs}, f, indent=1)
    print("Codec pass done. Build the sets with the project's Python:\n"
          "    .venv\\Scripts\\python.exe scripts/make_codec_case.py --sets-only")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
