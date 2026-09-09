"""
hash_learn/data.py — Training pairs for a learned hash remover.

Each pair is (mixture, clean): a random excerpt of a clean finished master
(docs/host-census.json, `usable` rows minus the held-out hosts), plus the
aperiodic hash model (the one the author accepted in listening round 5) at
a random level. Level is set as band SNR — hash energy in 4.5-12 kHz
relative to the host's energy in the same band, in dB — because that is
cheap to set exactly; the hearing-model level is reported on the evaluation
side, not here.

The model varies per pair: gate cut-off 5-20 Hz, band edges jittered, seed.
Each excerpt is scanned on the fine grid (1024/256) into log-magnitude
spectrograms; the network sees the mixture and learns a per-bin gain in the
hash band that recovers the clean magnitude.

Run under .venv-stems (torch). Writes shards to <out>/shard_*.npz.

Usage: python scripts/hash_learn/data.py --out D:/MusicVault/Tools/Shimmer/hash_data
           [--pairs 4000] [--excerpt 4.0] [--holdout reference-hey,distrokid-alive-again]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
from scipy import signal as ss

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from shimmer.audio_io import load_audio     # noqa: E402
from shimmer import artifacts as A          # noqa: E402

N_FFT, HOP = 1024, 256
BAND = (4500.0, 12000.0)     # what the hash occupies
CTX = (2000.0, 16000.0)      # what the network sees
SR = 48000


def aperiodic_hash(n, sr, rng, lo, hi, cutoff_hz):
    nz = A._band_noise(n, sr, lo, hi, rng)
    env_sr = 200.0
    m = int(n / sr * env_sr) + 2
    e = ss.sosfilt(ss.butter(2, cutoff_hz, fs=env_sr, output="sos"), rng.standard_normal(m))
    e = (e - e.min()) / (e.max() - e.min() + 1e-9)
    env = np.interp(np.arange(n) / sr, np.arange(m) / env_sr, e)
    return (nz * env[:, None] ** 2).astype(np.float32)


def band_energy(x, sr, lo, hi):
    sos = ss.butter(4, [lo, min(hi, 0.49 * sr)], btype="bandpass", fs=sr, output="sos")
    y = ss.sosfilt(sos, x.mean(axis=1))
    return float(np.mean(y ** 2)) + 1e-18


def spec(x, sr):
    """Log-magnitude STFT of the mono mix, [bins, frames], plus the complex STFT."""
    _, _, Z = ss.stft(x.mean(axis=1), fs=sr, nperseg=N_FFT, noverlap=N_FFT - HOP,
                      boundary="zeros", padded=True)
    return np.log(np.abs(Z) + 1e-6).astype(np.float32), Z


def bins(sr):
    f = np.fft.rfftfreq(N_FFT, 1.0 / sr)
    ctx = np.where((f >= CTX[0]) & (f < CTX[1]))[0]
    band = np.where((f >= BAND[0]) & (f < BAND[1]))[0]
    return f, ctx, band


def make_pairs(hosts, n_pairs, excerpt_s, rng, sr=SR):
    f, ctx, band = bins(sr)
    band_in_ctx = np.isin(ctx, band)
    X, Y, M = [], [], []
    per_host = max(1, n_pairs // len(hosts))
    for h in hosts:
        x, hsr = load_audio(h["path"])
        if hsr != sr:
            from math import gcd
            g = gcd(hsr, sr)
            x = ss.resample_poly(x, sr // g, hsr // g, axis=0).astype(np.float32)
        n = int(excerpt_s * sr)
        if x.shape[0] < n * 2:
            continue
        for _ in range(per_host):
            s = int(rng.integers(0, x.shape[0] - n))
            clip = np.ascontiguousarray(x[s:s + n]).astype(np.float32)
            if band_energy(clip, sr, *BAND) < 1e-9:
                continue
            lo = BAND[0] * float(rng.uniform(0.85, 1.15))
            hi = BAND[1] * float(rng.uniform(0.85, 1.15))
            # Both models, so the network is not blind to a modulation it
            # never saw (the first model failed on the periodic hash at high
            # level): 70 % aperiodic (the accepted model), 30 % periodic
            # gated at 8-40 Hz.
            if rng.uniform() < 0.7:
                art = aperiodic_hash(n, sr, rng, lo, hi, float(rng.uniform(5.0, 20.0)))
            else:
                art = A.hash_flicker(n, sr, seed=int(rng.integers(1 << 30)), lo=lo, hi=hi,
                                     rate_hz=float(rng.uniform(8.0, 40.0)))
            snr_db = float(rng.uniform(-25.0, -1.0))          # hash below host, band SNR
            g = np.sqrt(band_energy(clip, sr, *BAND) / band_energy(art, sr, *BAND)
                        * 10 ** (snr_db / 10.0))
            mix = (clip + g * art).astype(np.float32)
            lm, _ = spec(mix, sr)
            lc, _ = spec(clip, sr)
            X.append(lm[ctx]); Y.append(lc[ctx]); M.append(snr_db)
    # float16 on disk: 1500 pairs of 3 s at 299 x 563 is ~1 GB for X and Y
    # together, against 4 GB in float32.
    return (np.stack(X).astype(np.float16), np.stack(Y).astype(np.float16),
            np.array(M, dtype=np.float32), band_in_ctx)


def main(argv):
    def opt(k, d=None):
        return argv[argv.index(k) + 1] if k in argv else d
    out = opt("--out", os.path.join(ROOT, "hash_data"))
    n_pairs = int(opt("--pairs", 2500))
    excerpt_s = float(opt("--excerpt", 3.0))
    holdout = set((opt("--holdout", "reference-hey,distrokid-alive-again")).split(","))
    census = json.load(open(os.path.join(ROOT, "docs", "host-census.json"), encoding="utf-8"))["rows"]
    hosts = [r for r in census if r["usable"]]
    # hold out by song stem so the evaluation hosts never appear in training
    def stem(r):
        return os.path.splitext(os.path.basename(r["path"]))[0].lower()
    hosts = [r for r in hosts if not any(h.split("-", 1)[-1].replace("-", " ") in r["song"].lower().replace("-", " ")
                                          for h in holdout)]
    os.makedirs(out, exist_ok=True)
    rng = np.random.default_rng(20260908)
    print(f"{len(hosts)} hosts after holdout; {n_pairs} pairs of {excerpt_s} s")
    X, Y, S, band_mask = make_pairs(hosts, n_pairs, excerpt_s, rng)
    np.savez_compressed(os.path.join(out, "shard_0.npz"), X=X, Y=Y, snr=S, band=band_mask)
    print(f"wrote {X.shape[0]} pairs, spec {X.shape[1]}x{X.shape[2]} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
