"""
stem_effects.py — Per-stem character effects for the Remix tab.

Pure numpy/scipy DSP (no torch — these run in the app venv). Each effect
takes (samples, channels) float32 and returns the same shape. The rack
order is fixed: formant -> saturation -> doubler -> reverb -> gain.

Settings shape (one per stem, parsed by stem_settings_from_json):

    {"gain_db": 0.0, "mute": false,
     "effects": {
        "formant":    {"enabled": false, "ratio": 0.88},
        "saturation": {"enabled": false, "drive_db": 8.0},
        "doubler":    {"enabled": false, "mix": 0.45, "detune_cents": 12.0},
        "reverb":     {"enabled": false, "mix": 0.25, "size": 0.5}
     }}
"""

from __future__ import annotations

from . import _winfix  # noqa: F401

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np

from .dsp import as_2d

STEM_NAMES = ("vocals", "drums", "bass", "other")


@dataclass
class StemSettings:
    gain_db: float = 0.0
    mute: bool = False
    formant_enabled: bool = False
    formant_ratio: float = 0.88          # <1 deeper, >1 thinner (0.7..1.4)
    saturation_enabled: bool = False
    saturation_drive_db: float = 8.0     # 0..24
    doubler_enabled: bool = False
    doubler_mix: float = 0.45            # 0..1
    doubler_detune_cents: float = 12.0   # 2..40
    reverb_enabled: bool = False
    reverb_mix: float = 0.25             # 0..1
    reverb_size: float = 0.5             # 0..1 (room -> hall)

    def is_identity(self) -> bool:
        return (not self.mute and abs(self.gain_db) < 0.05 and
                not self.formant_enabled and not self.saturation_enabled and
                not self.doubler_enabled and not self.reverb_enabled)


def stem_settings_from_json(data: Optional[Dict[str, Any]]) -> StemSettings:
    data = data or {}
    fx = data.get("effects") or {}

    def _f(group: str, key: str, default: float,
           lo: float, hi: float) -> float:
        try:
            v = float((fx.get(group) or {}).get(key, default))
        except (TypeError, ValueError):
            return default
        return float(np.clip(v, lo, hi))

    def _on(group: str) -> bool:
        return bool((fx.get(group) or {}).get("enabled", False))

    try:
        gain = float(np.clip(float(data.get("gain_db", 0.0)), -24.0, 12.0))
    except (TypeError, ValueError):
        gain = 0.0

    return StemSettings(
        gain_db=gain,
        mute=bool(data.get("mute", False)),
        formant_enabled=_on("formant"),
        formant_ratio=_f("formant", "ratio", 0.88, 0.7, 1.4),
        saturation_enabled=_on("saturation"),
        saturation_drive_db=_f("saturation", "drive_db", 8.0, 0.0, 24.0),
        doubler_enabled=_on("doubler"),
        doubler_mix=_f("doubler", "mix", 0.45, 0.0, 1.0),
        doubler_detune_cents=_f("doubler", "detune_cents", 12.0, 2.0, 40.0),
        reverb_enabled=_on("reverb"),
        reverb_mix=_f("reverb", "mix", 0.25, 0.0, 1.0),
        reverb_size=_f("reverb", "size", 0.5, 0.0, 1.0),
    )


def remix_settings_from_json(
        data: Optional[Dict[str, Any]]) -> Dict[str, StemSettings]:
    """Parse the full per-stem settings map; missing stems get defaults."""
    data = data or {}
    return {name: stem_settings_from_json(data.get(name))
            for name in STEM_NAMES}


# ── Effects ──────────────────────────────────────────────────────────────

def saturate(x: np.ndarray, drive_db: float) -> np.ndarray:
    """Soft tanh saturation, RMS-compensated so mix balance survives."""
    if drive_db <= 0.05:
        return x
    g = 10.0 ** (drive_db / 20.0)
    y = np.tanh(x * g)
    rin = float(np.sqrt(np.mean(x ** 2)) + 1e-12)
    rout = float(np.sqrt(np.mean(y ** 2)) + 1e-12)
    return (y * (rin / rout)).astype(np.float32)


def doubler(x: np.ndarray, sr: int, mix: float,
            detune_cents: float) -> np.ndarray:
    """Two detuned, delayed copies under the dry signal (double-track)."""
    if mix <= 0.005:
        return x
    n = x.shape[0]
    out = x.astype(np.float32).copy()
    for i, sign in enumerate((+1, -1)):
        ratio = 2.0 ** (sign * detune_cents / 1200.0)
        idx = np.clip(np.arange(n) * ratio, 0, n - 1)
        lo = idx.astype(np.int64)
        hi = np.minimum(lo + 1, n - 1)
        frac = (idx - lo)[:, None].astype(np.float32)
        shifted = x[lo] * (1 - frac) + x[hi] * frac
        d = int(sr * 0.018) * (i + 1)   # 18 / 36 ms pre-delays
        delayed = np.zeros_like(shifted)
        if d < n:
            delayed[d:] = shifted[:n - d]
        out += (mix / 2.0) * delayed
    return out


def formant_shift(x: np.ndarray, sr: int, ratio: float,
                  n_fft: int = 2048) -> np.ndarray:
    """Spectral-envelope shift: move the formants, keep the pitch.

    STFT analysis; per frame the log-magnitude envelope (cepstrally
    smoothed) is rescaled along the frequency axis while the fine
    structure (harmonics) stays put. ratio < 1 sounds deeper/darker,
    ratio > 1 thinner/brighter.
    """
    if abs(ratio - 1.0) < 1e-3:
        return x
    from numpy.fft import irfft, rfft

    x = as_2d(x)
    hop = n_fft // 4
    win = np.hanning(n_fft).astype(np.float32)
    n = x.shape[0]
    out = np.zeros_like(x)
    norm = np.zeros(n, dtype=np.float32)
    n_bins = n_fft // 2 + 1
    src_idx = np.clip(np.arange(n_bins) / ratio, 0, n_bins - 1)
    # Cepstral lifter: keep only the low quefrency part of log|X| as the
    # envelope. 40 coefficients ~ formant-scale smoothness at 44.1/48 kHz.
    lifter = np.zeros(n_bins)
    lifter[:40] = 1.0
    lifter[1:40] *= np.linspace(1.0, 0.0, 39) ** 0.5

    starts = range(0, max(1, n - n_fft), hop)
    for ch in range(x.shape[1]):
        for s in starts:
            frame = x[s:s + n_fft, ch]
            if frame.shape[0] < n_fft:
                break
            spec = rfft(frame * win)
            mag = np.abs(spec)
            logm = np.log(mag + 1e-9)
            ceps = rfft(np.concatenate([logm, logm[-2:0:-1]]))
            env = irfft(ceps[:n_bins] * lifter,
                        n=2 * (n_bins - 1))[:n_bins].real
            fine = logm - env
            env_shifted = np.interp(src_idx, np.arange(n_bins), env)
            new_mag = np.exp(env_shifted + fine)
            spec = new_mag * np.exp(1j * np.angle(spec))
            y = irfft(spec, n=n_fft).astype(np.float32) * win
            out[s:s + n_fft, ch] += y
            if ch == 0:
                norm[s:s + n_fft] += win ** 2
    norm = np.maximum(norm, 1e-6)
    return (out / norm[:, None]).astype(np.float32)


# Schroeder reverb tuning (seconds). Slightly different left/right comb
# lengths decorrelate the channels for stereo width.
_COMB_S = (0.0297, 0.0371, 0.0411, 0.0437)
_ALLPASS_S = (0.005, 0.0017)


def _comb(x: np.ndarray, d: int, fb: float) -> np.ndarray:
    """Feedback comb y[n] = x[n] + fb*y[n-d], vectorized blockwise: each
    d-sized block depends only on the previous block, so the recursion
    runs over n/d blocks instead of n samples."""
    y = x.astype(np.float32).copy()
    n = y.shape[0]
    for s in range(d, n, d):
        e = min(s + d, n)
        y[s:e] += fb * y[s - d:s - d + (e - s)]
    return y


def _allpass(x: np.ndarray, d: int, g: float) -> np.ndarray:
    """Schroeder allpass y[n] = -g*x[n] + x[n-d] + g*y[n-d], blockwise."""
    n = x.shape[0]
    y = (-g * x).astype(np.float32)
    for s in range(d, n, d):
        e = min(s + d, n)
        y[s:e] += x[s - d:s - d + (e - s)] + g * y[s - d:s - d + (e - s)]
    return y


def reverb(x: np.ndarray, sr: int, mix: float, size: float) -> np.ndarray:
    """Simple stereo Schroeder reverb (4 combs + 2 allpasses per channel)."""
    if mix <= 0.005:
        return x
    x = as_2d(x)
    fb = 0.72 + 0.2 * float(np.clip(size, 0.0, 1.0))   # decay
    stretch = 1.0 + 1.2 * float(np.clip(size, 0.0, 1.0))
    wet = np.zeros_like(x)
    for ch in range(x.shape[1]):
        acc = np.zeros(x.shape[0], dtype=np.float32)
        for i, base in enumerate(_COMB_S):
            d = max(1, int(sr * base * stretch * (1.0 + 0.011 * ch * (i + 1))))
            acc += _comb(x[:, ch], d, fb)
        y = acc / len(_COMB_S)
        for base in _ALLPASS_S:
            y = _allpass(y, max(1, int(sr * base)), 0.7)
        wet[:, ch] = y
    mix = float(np.clip(mix, 0.0, 1.0))
    return ((1.0 - 0.5 * mix) * x + mix * wet).astype(np.float32)


def fx_signature(s: StemSettings) -> str:
    """Stable key for the EFFECTS portion of the settings (gain and mute
    excluded — those are cheap and applied after the cached fx render)."""
    return "|".join(str(v) for v in (
        s.formant_enabled, round(s.formant_ratio, 4),
        s.saturation_enabled, round(s.saturation_drive_db, 2),
        s.doubler_enabled, round(s.doubler_mix, 3),
        round(s.doubler_detune_cents, 2),
        s.reverb_enabled, round(s.reverb_mix, 3), round(s.reverb_size, 3),
    ))


def apply_fx_only(x: np.ndarray, sr: int, s: StemSettings) -> np.ndarray:
    """The effects rack without gain/mute — the expensive, cacheable part."""
    x = as_2d(np.asarray(x, dtype=np.float32))
    if s.formant_enabled:
        x = formant_shift(x, sr, s.formant_ratio)
    if s.saturation_enabled:
        x = saturate(x, s.saturation_drive_db)
    if s.doubler_enabled:
        x = doubler(x, sr, s.doubler_mix, s.doubler_detune_cents)
    if s.reverb_enabled:
        x = reverb(x, sr, s.reverb_mix, s.reverb_size)
    return x


def apply_gain_mute(x: np.ndarray, s: StemSettings) -> np.ndarray:
    if s.mute:
        return np.zeros_like(x)
    if abs(s.gain_db) >= 0.05:
        return (x * (10.0 ** (s.gain_db / 20.0))).astype(np.float32)
    return x


def apply_stem_effects(x: np.ndarray, sr: int,
                       s: StemSettings) -> np.ndarray:
    """Full rack for one stem. Muted stems return silence."""
    x = as_2d(np.asarray(x, dtype=np.float32))
    if s.mute:
        return np.zeros_like(x)
    return apply_gain_mute(apply_fx_only(x, sr, s), s)


def render_remix(stems: Dict[str, np.ndarray], sr: int,
                 settings: Dict[str, StemSettings]) -> np.ndarray:
    """Apply each stem's rack and sum. Peak-protects the sum."""
    n = min(v.shape[0] for v in stems.values())
    out = None
    for name in STEM_NAMES:
        if name not in stems:
            continue
        y = apply_stem_effects(stems[name][:n], sr,
                               settings.get(name, StemSettings()))
        out = y if out is None else out + y
    if out is None:
        raise ValueError("No stems to mix")
    peak = float(np.max(np.abs(out)))
    if peak > 0.999:
        out = out / peak * 0.999
    return out.astype(np.float32)
