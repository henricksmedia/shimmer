"""
hash_learn/infer.py — Apply the trained mask network to audio, and measure
it with the harness definitions on the held-out hosts.

    python scripts/hash_learn/infer.py --model scripts/hash_learn/masknet.pt --eval
    python scripts/hash_learn/infer.py --model ... --in a.wav --out b.wav

Runs under .venv-stems. The evaluation mirrors efficacy_harness: hosts
reference-hey and distrokid-alive-again (never in training), the aperiodic
and periodic models at 0.5 and 2.0 sones; efficacy = 1 - added(K, C) /
added(H, R); cost net of the artifact's masking; control cost on the clean
host alone.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import torch
from scipy import signal as ss

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
from model import MaskNet                    # noqa: E402
from data import N_FFT, HOP, CTX, SR, aperiodic_hash   # noqa: E402


class Remover:
    def __init__(self, path, device=None):
        ck = torch.load(path, map_location="cpu")
        self.net = MaskNet(); self.net.load_state_dict(ck["state"]); self.net.eval()
        self.dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.net.to(self.dev)
        self.band = torch.from_numpy(ck["band"].astype(np.float32)).to(self.dev)[None, None, :, None]
        self.ctx_hz = tuple(float(v) for v in ck.get("ctx_hz", np.array(CTX)))

    def __call__(self, x, sr, strength=1.0):
        assert sr == SR, "the network is trained at 48 kHz"
        f = np.fft.rfftfreq(N_FFT, 1.0 / sr)
        ctx = np.where((f >= self.ctx_hz[0]) & (f < self.ctx_hz[1]))[0]
        out = np.empty_like(x)
        for c in range(x.shape[1]):
            _, _, Z = ss.stft(x[:, c], fs=sr, nperseg=N_FFT, noverlap=N_FFT - HOP, boundary="zeros", padded=True)
            lm = np.log(np.abs(Z[ctx]) + 1e-6).astype(np.float32)
            with torch.no_grad():
                t = torch.from_numpy(lm).to(self.dev)[None, None]
                g = self.net(t - t.mean())
                g = g * self.band + (1.0 - self.band)
            g = g[0, 0].cpu().numpy()
            # Clamped, because it is not: at strength > 1 the unclamped form
            # 1 - s(1 - g) goes negative wherever g < 1 - 1/s (at s = 3, any
            # bin the network masked below 0.67), and a negative gain does not
            # attenuate — it flips the phase of that bin and writes the
            # artifact back in inverted. Every strength above 1.0 measured
            # before 2026-09-09 carried this.
            g = np.clip(1.0 - strength * (1.0 - g), 0.0, 1.0)
            G = np.ones(Z.shape, dtype=np.float32); G[ctx] = g
            _, y = ss.istft(Z * G, fs=sr, nperseg=N_FFT, noverlap=N_FFT - HOP, input_onesided=True, boundary=True)
            out[:, c] = y[:x.shape[0]]
        return out.astype(np.float32)


def evaluate(model_path):
    from shimmer import artifacts as A
    from shimmer.perceptual import measure_damage
    import efficacy_harness as E
    rem = Remover(model_path)
    hs = E.hosts(["reference-hey", "distrokid-alive-again"])
    rng = np.random.default_rng(7)
    print(f"{'model / host':30s} {'level':>5s} {'eff':>6s} {'cost':>6s} {'tilt':>6s} {'ctrl':>6s}")
    for hname, H, sr, _ in hs:
        if sr != SR:
            from math import gcd
            g = gcd(sr, SR); H = ss.resample_poly(H, SR // g, sr // g, axis=0).astype(np.float32); sr = SR
        K = rem(H, sr); dk = measure_damage(H, K, sr)
        for mname, raw in (("aperiodic", aperiodic_hash(H.shape[0], sr, rng, 4500.0, 12000.0, 12.0)),
                           ("periodic", A.make("hash", H.shape[0], sr, host=H)),
                           ("wide 1.5-16k", A.make("hash_wide", H.shape[0], sr, host=H))):
            for L in (0.5, 2.0):
                art, d_in = E.match_level(H, raw, sr, L)
                R = (H + art).astype(np.float32)
                C = rem(R, sr)
                eff = 1 - measure_damage(K, C, sr).added / d_in.added
                dc = measure_damage(H, C, sr)
                print(f"{mname + ' / ' + hname[:16]:30s} {L:5.1f} {eff:6.2f} {max(0, dc.missing - d_in.missing):6.3f} "
                      f"{max(0, dc.lin_dist - d_in.lin_dist):6.2f} {dk.missing:6.3f}", flush=True)


def main(argv):
    def opt(k, d=None):
        return argv[argv.index(k) + 1] if k in argv else d
    model = opt("--model", os.path.join(HERE, "masknet.pt"))
    if "--eval" in argv:
        evaluate(model); return 0
    from shimmer.audio_io import load_audio, save_audio
    x, sr = load_audio(opt("--in"))
    if sr != SR:
        from math import gcd
        g = gcd(sr, SR); x = ss.resample_poly(x, SR // g, sr // g, axis=0).astype(np.float32); sr = SR
    y = Remover(model)(x, sr, float(opt("--strength", 1.0)))
    save_audio(opt("--out"), y, sr, subtype="PCM_24")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
