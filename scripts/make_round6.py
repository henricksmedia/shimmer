"""
make_round6.py — Listening round 6: the learned hash remover on real renders.

Per real Suno render (hot 8 s): the untouched file and the same passage
through the learned remover (scripts/hash_learn/masknet.pt), nothing else in
the chain. Blind letters, matched to -18 LUFS, answer key names them. Also
the removed signal per song (unblinded, `-removed`), so what it took can be
heard on its own.

The harness says how much modelled hash the network removes on held-out
hosts; this round is the only test of whether it removes the real thing
without taking the music. Runs under .venv-stems.

Usage: python scripts/make_round6.py [--strength 1.0] [--out listening-test/round-6]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from scipy import signal as ss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "hash_learn"))

from shimmer import detect as D                          # noqa: E402
from shimmer.audio_io import load_audio, save_audio      # noqa: E402
from shimmer.perceptual import measure_damage            # noqa: E402
import make_ab_round                                     # noqa: E402
# Two environments: rendering needs torch (.venv-stems), blinding needs the
# loudness meter (.venv). `--blind-only` runs the second half from the
# renders the first half wrote, so each step runs where its library is.

RENDERS = ["suno-the-little-things", "suno-kindling", "suno-leave-the-world-behind",
           "suno-algorithms-lure", "suno-we-were-meant-for-the-stars", "suno-falling-for-you"]
CLIP_S = 8.0


def main(argv):
    strength = float(argv[argv.index("--strength") + 1]) if "--strength" in argv else 1.0
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "listening-test", "round-6")
    renders = os.path.join(out, "renders")
    os.makedirs(renders, exist_ok=True)
    readings = {}
    if "--blind-only" not in argv:
        from infer import Remover, SR
        rem = Remover(os.path.join(ROOT, "scripts", "hash_learn", "masknet.pt"))
        for name in RENDERS:
            x, sr = load_audio(os.path.join(ROOT, "sources", name + ".wav"))
            scan = D.evidence_scan(x, sr)
            w0 = int(scan.window_start_s * sr)
            clip = np.ascontiguousarray(x[w0:w0 + int(CLIP_S * sr)]).astype(np.float32)
            if sr != SR:
                from math import gcd
                g = gcd(sr, SR)
                clip = ss.resample_poly(clip, SR // g, sr // g, axis=0).astype(np.float32)
                sr = SR
            y = rem(clip, sr, strength)
            save_audio(os.path.join(renders, f"{name}-source.wav"), clip, sr, subtype="PCM_24")
            save_audio(os.path.join(renders, f"{name}-new.wav"), y, sr, subtype="PCM_24")
            save_audio(os.path.join(renders, f"{name}-removed.wav"), (clip - y).astype(np.float32), sr, subtype="PCM_24")
            print(f"{name}: rendered (flicker {scan.evidence.flicker_excess_db:+.2f})", flush=True)
        print("renders written; now run with --blind-only under .venv for the loudness-matched blind set")
        return 0
    for name in RENDERS:
        clip, sr = load_audio(os.path.join(renders, f"{name}-source.wav"))
        y, _ = load_audio(os.path.join(renders, f"{name}-new.wav"))
        d = measure_damage(clip, y, sr)
        readings[name] = {"damage_vs_source": d.as_dict(), "strength": strength}
        print(f"{name:36s} removed: missing {d.missing:.3f} lin {d.lin_dist:.2f} added {d.added:.3f}", flush=True)
    make_ab_round.MEANING = {"source": "the untouched render (hidden anchor)",
                             "new": f"the learned hash remover at {strength:.0%}, nothing else"}
    make_ab_round.main([renders, "--out", os.path.join(out, "blind")])
    key_path = os.path.join(out, "blind", "ANSWER-KEY.json")
    key = json.load(open(key_path, encoding="utf-8"))
    key["readings"] = readings
    key["note"] = ("Two letters per song. The question: is the shimmer gone, and is the music "
                   "intact? The -removed files in ../renders are what it took, unblinded.")
    with open(key_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(key, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
