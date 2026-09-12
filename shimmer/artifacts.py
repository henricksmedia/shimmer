"""
artifacts.py — Models of the artifacts Shimmer's presets exist to remove.

Why this module exists
----------------------
Everything measured before this asked "what did the preset take away?" and
nothing asked "did the artifact go?", because on a real render there is no
way to tell the two apart: the artifact and the music sit in the same
cells, and the only presence measure was the detector's own prior, which is
the thing under test.

Ground truth needs a host that is known to be clean and an artifact that is
known exactly. So: take a finished master, add a modelled artifact, and now
both halves are known. Efficacy is how much of the *added* audible content
a preset removes; cost is how much of the *host* it removes. Both come from
the hearing model in perceptual.py, in the same unit, and neither involves
the detector.

These are models, not captures. Each one follows the description in
docs/PRESET_REVIEW.md §1 of what the artifact is and where it lives, and
each docstring says what the model does not reproduce. A preset that beats
the model has beaten the model; whether it beats the real thing is a
listening question. Families that have no honest model yet (phase
incoherence, cymbal chatter, formant instability) are not modelled, and
presets aimed at them are reported as "not covered", not as inert.

All generators return stereo float32 of the requested length at a nominal
level; callers set the level (scripts/efficacy_harness.py matches it to a
target audibility against the host, so "how loud" is measured, not chosen).
"""
from __future__ import annotations

from . import _winfix  # noqa: F401

from typing import Callable, Dict, Optional

import numpy as np
from scipy import signal as ss


def _band_noise(n: int, sr: int, lo: float, hi: float, rng: np.random.Generator,
                channels: int = 2, order: int = 4) -> np.ndarray:
    hi = min(hi, 0.49 * sr)
    sos = ss.butter(order, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return np.stack([ss.sosfilt(sos, rng.standard_normal(n)) for _ in range(channels)],
                    axis=1).astype(np.float32)


def hash_flicker(n: int, sr: int, seed: int = 2, lo: float = 4500.0,
                 hi: float = 12000.0, rate_hz: float = 20.0) -> np.ndarray:
    """Family B, the Suno hash: noise in 4.5-12 kHz switched on and off at a
    rate real instruments do not produce (10-50 Hz). Decorrelated between
    channels, as the residual of a stereo codec is. 20 Hz is the rate
    tests/test_detect.py uses and sits inside the range the engine's fine
    pass is built for; measured on a reference master at 0.5 sones, Suno
    Hash's efficacy was 0.07-0.22 at every rate from 8 to 40 Hz, so the
    rate is not what limits it.

    Not modelled: the way the real hash follows the music (it is louder while
    notes play). See `shadow` for that half."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    nz = _band_noise(n, sr, lo, hi, rng)
    out = np.empty_like(nz)
    for c in range(nz.shape[1]):
        am = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * rate_hz * t + 0.9 * c))
        out[:, c] = nz[:, c] * am
    return out


def line(n: int, sr: int, seed: int = 1, hz: float = 16000.0,
         duty: float = 1.0, period_s: float = 1.5) -> np.ndarray:
    """Family A, a fixed-frequency line: a steady sine at an absolute
    frequency that never moves with the music. `duty` < 1 gates it on and
    off with `period_s`, the intermittent whistle.

    Not modelled: imaging (a mirror of low content that moves with the
    music), which the review says the chirping whistle often is."""
    t = np.arange(n) / sr
    s = np.sin(2 * np.pi * hz * t)
    if duty < 1.0:
        gate = ((t % period_s) < duty * period_s).astype(np.float64)
        # 10 ms ramps so the gate itself is not a click.
        k = max(1, int(0.01 * sr))
        gate = np.convolve(gate, np.ones(k) / k, mode="same")
        s = s * gate
    return np.stack([s, 0.7 * s], axis=1).astype(np.float32)


def comb(n: int, sr: int, seed: int = 3, spacing_hz: float = 600.0,
         lo: float = 2400.0, hi: float = 18000.0) -> np.ndarray:
    """Family A, the checkerboard: evenly spaced fixed lines, the
    periodised spectrum of an upsampling layer. Random phases, level
    falling 6 dB per octave so the teeth sit in the same ratio to the host
    across the band."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    out = np.zeros((n, 2))
    k = int(np.ceil(lo / spacing_hz))
    while k * spacing_hz < min(hi, 0.49 * sr):
        f = k * spacing_hz
        w = (lo / f)
        for c in range(2):
            out[:, c] += w * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi))
        k += 1
    return (out / max(np.max(np.abs(out)), 1e-9)).astype(np.float32)


def fizz(n: int, sr: int, seed: int = 4, lo: float = 8000.0,
         hi: float = 18000.0) -> np.ndarray:
    """Family B, the steady part: a constant noise floor across 8-18 kHz
    that does not follow the music."""
    rng = np.random.default_rng(seed)
    return _band_noise(n, sr, lo, hi, rng)


def shadow(n: int, sr: int, host: np.ndarray, seed: int = 6,
           lo: float = 3000.0, hi: float = 10000.0,
           key_lo: float = 1000.0, key_hi: float = 3000.0) -> np.ndarray:
    """Family B, the part that follows the music: noise in 3-10 kHz whose
    envelope is the host's own 1-3 kHz envelope, so it exists only while
    notes play and is silent in the gaps. This is the residue a
    minimum-statistics denoiser cannot learn, because there is no quiet
    frame to learn it from."""
    rng = np.random.default_rng(seed)
    mono = host.mean(axis=1) if host.ndim > 1 else host
    sos = ss.butter(4, [key_lo, key_hi], btype="bandpass", fs=sr, output="sos")
    key = ss.sosfilt(sos, mono.astype(np.float64))
    env = np.abs(ss.hilbert(key))
    k = max(1, int(0.02 * sr))
    env = np.convolve(env, np.ones(k) / k, mode="same")
    env = env / max(float(env.max()), 1e-9)
    nz = _band_noise(n, sr, lo, hi, rng)
    return (nz * env[:n, None]).astype(np.float32)


def sibilance(n: int, sr: int, seed: int = 5, lo: float = 5000.0,
              hi: float = 9000.0, burst_s: float = 0.08,
              every_s: float = 0.4) -> np.ndarray:
    """Family D, brittle consonants: 80 ms noise bursts in 5-9 kHz every
    400 ms, the razor 'sss'. Mono (a vocal is centered), which also makes
    it the case the Mid-channel protection fights."""
    rng = np.random.default_rng(seed)
    nz = _band_noise(n, sr, lo, hi, rng, channels=1)[:, 0]
    env = np.zeros(n)
    L = int(burst_s * sr)
    for s0 in range(int(0.3 * sr), n - L, int(every_s * sr)):
        env[s0:s0 + L] = np.hanning(L)
    y = (nz * env).astype(np.float32)
    return np.stack([y, y], axis=1)


def hash_wide(n: int, sr: int, seed: int = 12, lo: float = 1500.0,
              hi: float = 16000.0, cutoff_hz: float = 12.0) -> np.ndarray:
    """Family B, the broadband form measured on `suno-leave-the-world-behind`
    (2026-09-09): flicker of 3.6-5.1 dB rms in every half-octave band from
    1 kHz to 16 kHz, aperiodic. Band noise 1.5-16 kHz gated by a random
    envelope with modulation energy spread over 0-`cutoff_hz` Hz. Same
    construction as the aperiodic hash in scripts/hash_learn, wider band."""
    rng = np.random.default_rng(seed)
    nz = _band_noise(n, sr, lo, hi, rng)
    env_sr = 200.0
    m = int(n / sr * env_sr) + 2
    e = ss.sosfilt(ss.butter(2, cutoff_hz, fs=env_sr, output="sos"), rng.standard_normal(m))
    e = (e - e.min()) / (e.max() - e.min() + 1e-9)
    env = np.interp(np.arange(n) / sr, np.arange(m) / env_sr, e)
    return (nz * env[:, None] ** 2).astype(np.float32)


def clicks(n: int, sr: int, seed: int = 7, rate_hz: float = 1.5,
           min_ms: float = 0.1, max_ms: float = 3.0,
           hp_hz: float = 200.0) -> np.ndarray:
    """Pops: isolated clicks at random times, about 1.5 a second. Each is a
    decaying noise burst 0.1-3 ms long, random polarity, levels spread over
    12 dB, broadband above 200 Hz (the high-pass only removes a DC thump).
    The same click lands in both channels, the second at 0.8, because a
    codec click sits in the mix rather than on one side.

    Deliberately NOT shaped to the de-clicker's own idea of a click
    (runs <= 2 ms, inspected only above 2 kHz): an efficacy test built from
    the definition under test would pass by construction (PITFALLS,
    "Judging efficacy by the detector's own prior is circular"). Some
    clicks here are longer than 2 ms and all carry energy below 2 kHz.

    Not modelled: no real AI click has been captured in the corpus yet, so
    this follows the complaint ("short pops, ticks") and not a measurement.
    Clicks that ride the music's transients are `crackle`."""
    rng = np.random.default_rng(seed)
    out = np.zeros((n, 2))
    tail = int(0.005 * sr)
    t = 0.05 * sr
    while True:
        t += rng.exponential(sr / rate_hz)
        i = int(t)
        if i >= n - tail:
            break
        L = max(2, int(rng.uniform(min_ms, max_ms) * 1e-3 * sr))
        burst = rng.standard_normal(L) * np.exp(-np.linspace(0.0, 4.0, L))
        burst *= rng.choice((-1.0, 1.0)) * 10.0 ** (rng.uniform(-12.0, 0.0) / 20.0)
        out[i:i + L, 0] += burst
        out[i:i + L, 1] += 0.8 * burst
    out = ss.sosfilt(ss.butter(2, hp_hz, btype="highpass", fs=sr, output="sos"), out, axis=0)
    return (out / max(float(np.max(np.abs(out))), 1e-9)).astype(np.float32)


def crackle(n: int, sr: int, host: np.ndarray, seed: int = 8,
            rate_hz: float = 80.0, min_ms: float = 0.05, max_ms: float = 0.4,
            key_lo: float = 4000.0, key_hi: float = 10000.0) -> np.ndarray:
    """Crackle: dense micro-clicks that follow the music's top end, the
    "crackle on consonants and cymbals" users report. Candidate clicks at up
    to 80 a second, each kept with a probability equal to the host's
    4-10 kHz envelope at that moment, so the crackle lives where the
    cymbals and consonants are and is silent in the gaps. 0.05-0.4 ms
    bursts, levels spread over 18 dB, each click in one channel or both at
    random.

    This is the hard case for a de-clicker: clicks this dense are rarely
    "isolated", and they sit under the transients a de-clicker must leave
    alone. Not modelled: any link to the codec frame rate."""
    rng = np.random.default_rng(seed)
    mono = host.mean(axis=1) if host.ndim > 1 else host
    key = ss.sosfilt(ss.butter(4, [key_lo, min(key_hi, 0.49 * sr)], btype="bandpass",
                               fs=sr, output="sos"), mono.astype(np.float64))
    env = np.abs(ss.hilbert(key))
    k = max(1, int(0.02 * sr))
    env = np.convolve(env, np.ones(k) / k, mode="same")
    env = env / max(float(env.max()), 1e-9)
    out = np.zeros((n, 2))
    tail = int(0.002 * sr)
    t = 0.0
    while True:
        t += rng.exponential(sr / rate_hz)
        i = int(t)
        if i >= n - tail:
            break
        if rng.uniform() > env[min(i, len(env) - 1)]:
            continue
        L = max(2, int(rng.uniform(min_ms, max_ms) * 1e-3 * sr))
        burst = rng.standard_normal(L) * np.exp(-np.linspace(0.0, 4.0, L))
        burst *= 10.0 ** (rng.uniform(-18.0, 0.0) / 20.0)
        side = rng.integers(0, 3)          # 0 = left, 1 = right, 2 = both
        if side in (0, 2):
            out[i:i + L, 0] += burst
        if side in (1, 2):
            out[i:i + L, 1] += burst
    return (out / max(float(np.max(np.abs(out))), 1e-9)).astype(np.float32)


# Name -> generator. `shadow` and `crackle` need the host; the harness passes it.
GENERATORS: Dict[str, Callable[..., np.ndarray]] = {
    "hash": hash_flicker,
    "hash_wide": hash_wide,
    "line": line,
    "whistle": lambda n, sr, seed=1: line(n, sr, seed, hz=13500.0, duty=0.4),
    "comb": comb,
    "fizz": fizz,
    "shadow": shadow,
    "sibilance": sibilance,
    "clicks": clicks,
    "crackle": crackle,
}

# Models that are built from the host's own envelope.
NEEDS_HOST: tuple = ("shadow", "crackle")

# Which presets are aimed at which model. A preset absent from every list is
# "not covered": its target has no honest model here, and its efficacy is
# unknown rather than zero.
TARGETS: Dict[str, tuple] = {
    "hash": ("suno_hash", "vocal_glaze_plus", "deep_scrub"),
    "hash_wide": ("vocal_glaze_plus", "harsh_veil", "deep_scrub"),
    "line": ("cymbal_sheen", "air_brittle", "generic"),
    "whistle": ("laser_whistle",),
    "comb": ("checkerboard_grid",),
    "fizz": ("broadband_fizz", "air_brittle", "deep_scrub"),
    "shadow": ("echo_sheen", "presence_haze", "harsh_veil", "vocal_glaze",
               "phantom_cymbal", "deep_scrub"),
    "sibilance": ("sibilance_rattle",),
    # The only preset with the de-clicker on. The harness also measures the
    # de-clicker on its own (`--declick`).
    "clicks": ("sibilance_rattle",),
    "crackle": ("sibilance_rattle",),
}
NOT_COVERED: tuple = ("reverb_flutter", "cymbal_chatter")


def make(name: str, n: int, sr: int, host: Optional[np.ndarray] = None,
         seed: Optional[int] = None) -> np.ndarray:
    gen = GENERATORS[name]
    kw = {} if seed is None else {"seed": seed}
    if name in NEEDS_HOST:
        assert host is not None, f"{name} needs the host"
        return gen(n, sr, host, **kw)
    return gen(n, sr, **kw)
