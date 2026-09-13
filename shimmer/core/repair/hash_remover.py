"""Hash remover: the Shimmer card's candidate fix.

The learned mask network from the evidence branch (scripts/hash_learn,
model 3), run in numpy so nothing else needs installing. It looks at the
song's log-magnitude spectrum, 800 Hz-20 kHz in 1024-point frames every 256
samples at 48 kHz, and gives each bin in 1.5-16 kHz a gain from 0 to 1: how
much of it to keep. Six 5x5 convolution layers, dilated so each gain sees
about 1.5 octaves and 370 ms around it, the scale the fizz's structure
spans.

Measured before the rebuild (docs/HANDOFF-CHECKLIST.md item 15): on two
songs it never trained on, 81 % and 17 % of modelled hash removed, taking
0.064 and 0.033 sones of music; on real renders "harmless, mostly too
gentle" (listening round 6, an earlier model). Never judged blind with
this model. The rebuild measures it again through render() before its card
turns on (docs/STEP6-FIXES.md).

What changes from the training script's inference (scripts/hash_learn/
infer.py), and why:

- The network runs once over the whole song as it comes in, before the
  other fixes, in plan(). The gains are kept, so a preview window gets the
  same gains as the full render and a new Amount costs almost nothing.
  The level it sees is set by the whole song's mean log-magnitude.
- It works at 48 kHz, as trained. A song at another rate is resampled to
  48 kHz for the work, and only what the network removes is resampled back
  and subtracted, so nothing outside its band is touched.
- Amount scales how far each gain goes toward 0, clamped to 0-1 (a gain
  below 0 would flip the bin's phase and write the fizz back in).

Needs the network's weights (WEIGHTS, 0.5 MB). Without them the tool does
nothing and says so.

Speed: about 0.75 s per 6 s of audio per channel on the author's 16-thread
CPU (2026-09-13), from 7.2 s for a plain port, with the same gains (within
2e-6 of torch's). The work is one matrix multiply per layer per few rows,
run on WORKERS threads.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from math import gcd
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np
from numpy.lib.stride_tricks import as_strided
from scipy import signal as ss
from scipy.special import erf

SR = 48000
N_FFT = 1024
HOP = 256
CHUNK = 1024            # frames per pass through the network
HALO = 40               # frames either side a pass needs (the layers reach 34)
# The trained network (scripts/hash_learn, model 3, 2026-09-09), shipped next
# to this file. SHIMMER_HASH_WEIGHTS points at another to try it instead.
WEIGHTS = os.environ.get(
    "SHIMMER_HASH_WEIGHTS",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "hash_remover.npz"))

WORKERS = max(1, min(8, os.cpu_count() or 1))   # threads; more gained nothing
ROWS = 2                # frequency rows per thread job: small enough to stay in cache
# plan() runs the network over the whole song, about 50 s for a 3-minute
# song, so render() and core.prepare() say how far it has got.
SLOW_PLAN = True

_NET: Optional[Dict[str, Any]] = None
_POOL: Optional[ThreadPoolExecutor] = None


def available() -> bool:
    return os.path.exists(WEIGHTS)


def _net() -> Dict[str, Any]:
    """The weights as saved, plus "layers": per layer the weights as one
    [taps x in, out] matrix with the batch norm's scale folded in, the
    shift (bias and batch norm together), the kernel shape and dilation."""
    global _NET
    if _NET is None:
        with np.load(WEIGHTS) as z:
            net: Dict[str, Any] = {k: np.array(z[k]) for k in z.files}
        eps = float(net["bn_eps"])
        layers = []
        for i, dil in enumerate(net["dilations"]):
            w = net[f"w{i}"]
            cout, cin, kf, kt = w.shape
            s = net[f"g{i}"] / np.sqrt(net[f"v{i}"] + eps)
            wt = np.transpose(w, (2, 3, 1, 0)).reshape(kf * kt * cin, cout) * s
            shift = (net[f"b{i}"] - net[f"m{i}"]) * s + net[f"be{i}"]
            layers.append((np.ascontiguousarray(wt, dtype=np.float32),
                           shift.astype(np.float32), (kf, kt, cin, cout),
                           (int(dil[0]), int(dil[1]))))
        net["layers"] = layers
        _NET = net
    return _NET


@dataclass(frozen=True, eq=False)
class Plan:
    """What the remover needs from the whole song: each channel's mean
    log-magnitude over the bins the network sees (its level), and the
    network's gains for every frame of the song in its band ([bins,
    frames], float16). They are worked out once, so a preview window or a
    new Amount only redoes the cheap last step."""
    mean_lm: Tuple[float, ...]
    gains: Tuple[np.ndarray, ...] = ()


def _to48(x: np.ndarray, sr: int) -> np.ndarray:
    if sr == SR:
        return x
    g = gcd(int(sr), SR)
    return ss.resample_poly(x, SR // g, int(sr) // g, axis=0)


def _from48(x: np.ndarray, sr: int, n: int) -> np.ndarray:
    if sr != SR:
        g = gcd(int(sr), SR)
        x = ss.resample_poly(x, int(sr) // g, SR // g, axis=0)
    if x.shape[0] >= n:
        return x[:n]
    return np.pad(x, [(0, n - x.shape[0])] + [(0, 0)] * (x.ndim - 1))


def _ctx_bins(net: Dict[str, np.ndarray]) -> np.ndarray:
    f = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    lo, hi = (float(v) for v in net["ctx_hz"])
    return np.where((f >= lo) & (f < hi))[0]


def _stft(x: np.ndarray) -> np.ndarray:
    _, _, Z = ss.stft(x, fs=SR, nperseg=N_FFT, noverlap=N_FFT - HOP, boundary="zeros",
                      padded=True)
    return Z


def plan(audio: np.ndarray, sr: int,
         step: Optional[Callable[[float], None]] = None) -> Plan:
    """Run the network over the whole song. `step(fraction)`, when given,
    hears how far it has got (0-1) after each piece; it may raise to stop
    the work, as a cancelled render does."""
    if not available():
        return Plan(())
    net = _net()
    a = np.asarray(audio, dtype=np.float64)
    a = a[:, None] if a.ndim == 1 else a
    ctx = _ctx_bins(net)
    rows = net["band"] > 0
    x48 = _to48(a, sr)
    means, gains = [], []
    n = x48.shape[1]
    for c in range(n):
        lm = np.log(np.abs(_stft(x48[:, c])[ctx]) + 1e-6)
        mean = float(lm.mean())
        means.append(mean)
        each = None if step is None else (lambda f, c=c: step((c + f) / n))
        gains.append(_gains((lm - mean).astype(np.float32), net, each)[rows].astype(np.float16))
    return Plan(tuple(means), tuple(gains))


_R2 = np.float32(1.0 / np.sqrt(2.0))


def _gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + erf(x * _R2))


def _pool() -> ThreadPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ThreadPoolExecutor(WORKERS, thread_name_prefix="hash-remover")
    return _POOL


def _block(xp: np.ndarray, wt: np.ndarray, shift: np.ndarray, shape: Tuple[int, int, int, int],
           dil: Tuple[int, int], f0: int, f1: int, T: int, out: np.ndarray) -> None:
    """One layer on output rows f0-f1: the convolution (batch norm folded
    in), then GELU, written into out."""
    kf, kt, cin, cout = shape
    df, dt = dil
    e = xp.strides
    # Output (r, t) and tap (i, j) read xp[f0 + r + i*df, t + j*dt]. A strided
    # view lays all 25 taps of these rows side by side, so one multiply does
    # the layer and the rows stay in cache.
    v = as_strided(xp[f0:], shape=(f1 - f0, T, kf, kt, cin),
                   strides=(e[0], e[1], df * e[0], dt * e[1], e[2]), writeable=False)
    y = v.reshape(-1, kf * kt * cin) @ wt
    y += shift
    out[f0:f1] = _gelu(y).reshape(f1 - f0, T, cout)


def _mask(lm: np.ndarray, net: Dict[str, Any]) -> np.ndarray:
    """The network: [F, T] normalised log-magnitude -> [F, T] gains 0-1.

    Only the band's rows come out right, the only ones used. Each layer
    skips the rows no later layer reads, which changes nothing: the
    convolutions are zero padded at the spectrogram's edges, not at the
    skipped rows."""
    F, T = lm.shape
    layers = net["layers"]
    band = np.where(net["band"] > 0)[0]
    lo, hi = int(band[0]), int(band[-1]) + 1
    need = []
    for _, _, (kf, _, _, _), (df, _) in reversed(layers):
        need.append((max(0, lo), min(F, hi)))
        lo, hi = lo - (kf - 1) // 2 * df, hi + (kf - 1) // 2 * df
    need.reverse()
    x = lm[:, :, None].astype(np.float32)
    pool = _pool()
    for (wt, shift, shape, dil), (a, b) in zip(layers, need):
        kf, kt, cin, cout = shape
        pf, pt = (kf - 1) // 2 * dil[0], (kt - 1) // 2 * dil[1]
        xp = np.zeros((F + 2 * pf, T + 2 * pt, cin), dtype=np.float32)
        xp[pf:pf + F, pt:pt + T] = x
        out = np.zeros((F, T, cout), dtype=np.float32)
        jobs = [pool.submit(_block, xp, wt, shift, shape, dil, f0, min(b, f0 + ROWS), T, out)
                for f0 in range(a, b, ROWS)]
        for j in jobs:
            j.result()
        x = out
    y = x @ net["head_w"][0, :, 0, 0].astype(np.float32) + float(net["head_b"][0])
    return 1.0 / (1.0 + np.exp(-y))


def _gains(lm: np.ndarray, net: Dict[str, np.ndarray],
           step: Optional[Callable[[float], None]] = None) -> np.ndarray:
    """The network over a long spectrogram, CHUNK frames at a time with a
    HALO either side, so any length fits in memory. `step(fraction)` after
    each piece."""
    T = lm.shape[1]
    out = np.empty_like(lm, dtype=np.float32)
    for t0 in range(0, T, CHUNK):
        t1 = min(T, t0 + CHUNK)
        a, b = max(0, t0 - HALO), min(T, t1 + HALO)
        g = _mask(lm[:, a:b], net)
        out[:, t0:t1] = g[:, t0 - a:t0 - a + (t1 - t0)]
        if step is not None:
            step(t1 / T)
    return out


def removed(x: np.ndarray, sr: int, p: Plan, amount: float, offset: int = 0) -> np.ndarray:
    """What the remover takes out of x (same shape and rate)."""
    net = _net()
    a = np.asarray(x, dtype=np.float64)
    a = a[:, None] if a.ndim == 1 else a
    n = a.shape[0]
    x48 = _to48(a, sr)
    ctx = _ctx_bins(net)
    rows = net["band"] > 0
    out = np.zeros_like(x48)
    # Frames sit on a 256-sample grid counted from the start of the song (at
    # 48 kHz), so a window and a full render cut the same frames: frame k
    # here is frame k0 + k of the song.
    start = int(round(offset * SR / sr))
    pad = start % HOP
    k0 = (start - pad) // HOP
    for c in range(x48.shape[1]):
        seg = np.concatenate([np.zeros(pad), x48[:, c]]) if pad else x48[:, c]
        Z = _stft(seg)
        if c < len(p.gains):
            # The song's own gains; frames past its end keep everything.
            g = np.ones((int(rows.sum()), Z.shape[1]), dtype=np.float32)
            have = p.gains[c][:, k0:k0 + Z.shape[1]]
            g[:, :have.shape[1]] = have
        else:
            lm = np.log(np.abs(Z[ctx]) + 1e-6)
            mean = p.mean_lm[c] if c < len(p.mean_lm) else float(lm.mean())
            g = _gains((lm - mean).astype(np.float32), net)[rows]
        g = np.clip(1.0 - float(amount) * (1.0 - g), 0.0, 1.0)
        G = np.ones(Z.shape, dtype=np.float32)
        G[ctx[rows]] = g
        _, y = ss.istft(Z * (1.0 - G), fs=SR, nperseg=N_FFT, noverlap=N_FFT - HOP,
                        input_onesided=True, boundary=True)
        y = y[pad:pad + x48.shape[0]]
        out[:y.size, c] = y
    return _from48(out, sr, n)


def apply(x: np.ndarray, sr: int, p: Plan, amount: float, offset: int = 0) -> np.ndarray:
    """Take the fizz out of x at `amount` (0-1). Returns x itself when the
    weights are missing or Amount is 0."""
    if amount <= 0.0 or not available() or not p.mean_lm or np.asarray(x).shape[0] == 0:
        return x
    a = np.asarray(x, dtype=np.float64)
    r = removed(a, sr, p, amount, offset)
    y = (a[:, None] if a.ndim == 1 else a) - r
    return y if a.ndim == 2 else y[:, 0]


def summary(p: Plan, amount: float) -> Dict[str, Any]:
    return {"tool": "hash_remover", "model": os.path.basename(WEIGHTS),
            "available": available(), "amount": round(float(amount), 2)}
