"""
make_round5.py — Listening round 5: does the modelled hash sound like the
real thing?

Everything in checklist item 15 rests on the hash model: the harness judges
presets against it, and any learned separator would be trained on it. So
before training anything, the author listens. Per clean host:

  <host>-clean.wav              the untouched finished master
  <host>-model-aperiodic-2.wav  plus the aperiodic hash model at 2.0 sones
  <host>-model-aperiodic-05.wav plus the same at 0.5 sones
  <host>-model-periodic-2.wav   plus the periodic (20 Hz gated) model at 2.0

and, for comparison, the real thing:

  real-<render>.wav             the detector's hot 8 s of a Suno render
                                whose flicker excess is high

All at -18 LUFS. The question is one question: do the modelled files carry
the same kind of noise the real renders carry? Not blind; the names say
what each is, because the point is to compare the model with the real
artifact, not to rank.

Usage: python scripts/make_round5.py [--out listening-test/round-5]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from shimmer import artifacts as A                        # noqa: E402
from shimmer import detect as D                           # noqa: E402
from shimmer.audio_io import load_audio, save_audio       # noqa: E402
from shimmer.perceptual import measure_damage             # noqa: E402
from scipy import signal as ss                            # noqa: E402
import efficacy_harness as E                              # noqa: E402
from make_ab_round import at_lufs                         # noqa: E402

HOSTS = ["reference-hey", "distrokid-alive-again"]
REAL = ["sources/suno-the-little-things.wav", "sources/suno-kindling.wav"]
CLIP_S = 8.0


def aperiodic_hash(n, sr, seed=11, lo=4500.0, hi=12000.0, cutoff_hz=12.0):
    """Band noise gated by a random envelope whose modulation energy is
    spread over 0-cutoff Hz, the measured shape of real hash (2-2.6 dB rms
    flat over 2-50 Hz, no line)."""
    rng = np.random.default_rng(seed)
    nz = A._band_noise(n, sr, lo, hi, rng)
    env_sr = 200.0
    m = int(n / sr * env_sr) + 2
    e = ss.sosfilt(ss.butter(2, cutoff_hz, fs=env_sr, output="sos"), rng.standard_normal(m))
    e = (e - e.min()) / (e.max() - e.min() + 1e-9)
    env = np.interp(np.arange(n) / sr, np.arange(m) / env_sr, e)
    return (nz * env[:, None] ** 2).astype(np.float32)


def main(argv):
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "listening-test", "round-5")
    os.makedirs(out, exist_ok=True)
    key = {"question": "Do the modelled files carry the same kind of noise as the real renders?",
           "files": {}}
    for hname, H, sr, flick in E.hosts(HOSTS):
        save_audio(os.path.join(out, f"{hname}-clean.wav"), at_lufs(H, sr), sr, subtype="PCM_24")
        key["files"][f"{hname}-clean.wav"] = "untouched finished master"
        for label, raw, L in (("model-aperiodic-2", aperiodic_hash(H.shape[0], sr), 2.0),
                              ("model-aperiodic-05", aperiodic_hash(H.shape[0], sr), 0.5),
                              ("model-periodic-2", A.make("hash", H.shape[0], sr, host=H), 2.0)):
            art, d = E.match_level(H, raw, sr, L)
            R = (H + art).astype(np.float32)
            save_audio(os.path.join(out, f"{hname}-{label}.wav"), at_lufs(R, sr), sr, subtype="PCM_24")
            fl = D.evidence_scan(R, sr).evidence.flicker_excess_db
            key["files"][f"{hname}-{label}.wav"] = (f"{label.replace('-', ' ')} sones of modelled hash; "
                                                   f"hearing model added {d.added:.2f}, flicker excess {fl:+.2f} dB")
            print(f"{hname}-{label}: added {d.added:.2f}, flicker {fl:+.2f}", flush=True)
    for rel in REAL:
        x, sr = load_audio(os.path.join(ROOT, rel))
        scan = D.evidence_scan(x, sr)
        w0 = int(scan.window_start_s * sr)
        clip = np.ascontiguousarray(x[w0:w0 + int(CLIP_S * sr)])
        name = "real-" + os.path.splitext(os.path.basename(rel))[0] + ".wav"
        save_audio(os.path.join(out, name), at_lufs(clip, sr), sr, subtype="PCM_24")
        key["files"][name] = f"real Suno render, hot window, flicker excess {scan.evidence.flicker_excess_db:+.2f} dB"
        print(f"{name}: flicker {scan.evidence.flicker_excess_db:+.2f}", flush=True)
    with open(os.path.join(out, "KEY.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(key, f, indent=1)
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
