"""
make_round5_solo.py — Round 5 extras: the modelled hash on its own.

  only-model-aperiodic-2.wav    the aperiodic model alone, at the gain that
                                injects 2.0 sones into "Alive Again"
  only-model-aperiodic-05.wav   the same at the 0.5-sone gain
  only-model-periodic-2.wav     the periodic model alone at its 2.0 gain
  only-real-removed-<render>.wav  what per-bin gated subtraction (the
                                prototype in checklist item 15) takes out
                                of a real render's hot window: mostly hash,
                                with some cymbal and hit energy in it —
                                nothing isolates the real thing cleanly

Solo files are level-matched to each other at -30 LUFS so none can win by
being louder; they are quiet on purpose, as the artifact is.
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
from shimmer.mastering import apply_gain_to_lufs          # noqa: E402
from scipy import signal as ss                            # noqa: E402
import efficacy_harness as E                              # noqa: E402
from make_round5 import aperiodic_hash                    # noqa: E402

SOLO_LUFS = -30.0


def at(x, sr, target=SOLO_LUFS):
    y, _ = apply_gain_to_lufs(x, sr, target)
    peak = float(np.max(np.abs(y))) or 1.0
    return y * (0.99 / peak) if peak > 0.99 else y


def subtract_removed(x, sr, lo=4500.0, hi=12000.0, n_fft=1024, hop=256,
                     thr_db=1.0, range_db=6.0, floor_up_db_s=20.0, bin_track_ms=400.0):
    """The prototype from item 15, returning what it removed."""
    out = np.empty_like(x)
    fps = sr / hop
    up = floor_up_db_s / fps
    a_bin = float(np.exp(-1.0 / (bin_track_ms * 1e-3 * fps)))
    for c in range(x.shape[1]):
        f, t, Z = ss.stft(x[:, c], fs=sr, nperseg=n_fft, noverlap=n_fft - hop, boundary="zeros", padded=True)
        P = np.abs(Z) ** 2
        idx = np.where((f >= lo) & (f < hi))[0]
        e = 10 * np.log10(P[idx].mean(axis=0) + 1e-18)
        floor = np.empty_like(e); cur = e[0]
        for i in range(e.size):
            cur = min(e[i], cur + up); floor[i] = cur
        g = np.clip((e - floor - thr_db) / range_db, 0.0, 1.0)
        Pb = P[idx]
        noff = np.empty_like(Pb); cur = Pb[:, 0].copy()
        for i in range(Pb.shape[1]):
            cur = cur + (1.0 - a_bin) * (1.0 - g[i]) * (Pb[:, i] - cur)
            noff[:, i] = cur
        hash_est = np.clip(Pb - noff, 0.0, None) * g[None, :]
        gain = np.sqrt(np.clip((Pb - hash_est) / (Pb + 1e-18), 0.01, 1.0))
        G = np.ones_like(P); G[idx] = gain
        _, y = ss.istft(Z * G, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, input_onesided=True, boundary=True)
        out[:, c] = x[:, c] - y[:x.shape[0]]
    return out.astype(np.float32)


def main(argv):
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(ROOT, "listening-test", "round-5")
    key_path = os.path.join(out, "KEY.json")
    key = json.load(open(key_path, encoding="utf-8")) if os.path.exists(key_path) else {"files": {}}
    hname, H, sr, _ = E.hosts(["distrokid-alive-again"])[0]
    for label, raw, L in (("aperiodic-2", aperiodic_hash(H.shape[0], sr), 2.0),
                          ("aperiodic-05", aperiodic_hash(H.shape[0], sr), 0.5),
                          ("periodic-2", A.make("hash", H.shape[0], sr, host=H), 2.0)):
        art, d = E.match_level(H, raw, sr, L)
        name = f"only-model-{label}.wav"
        save_audio(os.path.join(out, name), at(art, sr), sr, subtype="PCM_24")
        key["files"][name] = (f"the {label.split('-')[0]} model alone, at the gain that injects "
                              f"{L} sones into Alive Again; matched to {SOLO_LUFS:.0f} LUFS")
        print(name, flush=True)
    for rel in ("sources/suno-the-little-things.wav", "sources/suno-kindling.wav"):
        x, sr = load_audio(os.path.join(ROOT, rel))
        scan = D.evidence_scan(x, sr)
        w0 = int(scan.window_start_s * sr)
        clip = np.ascontiguousarray(x[w0:w0 + int(8.0 * sr)]).astype(np.float32)
        rem = subtract_removed(clip, sr)
        name = "only-real-removed-" + os.path.splitext(os.path.basename(rel))[0] + ".wav"
        save_audio(os.path.join(out, name), at(rem, sr), sr, subtype="PCM_24")
        key["files"][name] = ("what per-bin gated subtraction takes out of the real render's hot "
                              "window: mostly hash, with some cymbal and hit energy in it; matched "
                              f"to {SOLO_LUFS:.0f} LUFS")
        print(name, flush=True)
    with open(key_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(key, f, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
