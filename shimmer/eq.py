"""
eq.py — User-facing parametric EQ (band list -> zero-phase biquad cascade).

Unlike the corrective tone curve in mastering.py (bounded, automatic,
computed from analysis), this is the user's creative filter bank: an
ordered list of EQ bands (bell, shelves, high/low-pass, notch) applied
as a single second-order-section cascade.

Filters run zero-phase via sosfiltfilt (forward + backward), which the
offline pipeline can afford and which keeps transients smear-free. The
two passes square the magnitude response, so gain-style bands (bell,
shelves) are DESIGNED AT HALF GAIN and come out exactly at the user's
dB after both passes. Gain-less bands (high/low-pass, notch) simply get
their designed response doubled in dB — a 12 dB/oct biquad highpass is
effectively 24 dB/oct. The frontend curve renderer mirrors this rule
(2x the designed response), so what you see is what is applied.

Applied in pipeline.clean_and_master AFTER artifact cleaning and post
filters, BEFORE mastering — so the limiter always catches user boosts.
"""

from __future__ import annotations

from . import _winfix  # noqa: F401  # must precede scipy import on Windows

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
from scipy.signal import sosfiltfilt

# Hard safety clamps (mirrored in static/js/eq.js).
MAX_BANDS = 12
FREQ_MIN_HZ = 20.0
FREQ_MAX_HZ = 20000.0
GAIN_LIMIT_DB = 18.0
Q_MIN = 0.1
Q_MAX = 18.0

FILTER_TYPES = (
    "bell", "low_shelf", "high_shelf", "highpass", "lowpass", "notch",
)
_GAIN_TYPES = {"bell", "low_shelf", "high_shelf"}


@dataclass
class EqBand:
    """One EQ band. `gain_db` is the EFFECTIVE (post zero-phase) gain."""

    type: str = "bell"
    freq_hz: float = 1000.0
    gain_db: float = 0.0
    q: float = 1.0
    enabled: bool = True


@dataclass
class EqParams:
    """The user's EQ: master enable + ordered band list."""

    enabled: bool = False
    bands: List[EqBand] = field(default_factory=list)

    def active_bands(self, sr: int) -> List[EqBand]:
        """Bands that would actually change the audio at this sample rate."""
        out = []
        for b in self.bands:
            if not b.enabled:
                continue
            if b.type not in FILTER_TYPES:
                continue
            if b.freq_hz <= 0 or b.freq_hz >= 0.49 * sr:
                continue
            if b.type in _GAIN_TYPES and abs(b.gain_db) < 0.05:
                continue
            out.append(b)
        return out

    def is_active(self, sr: int = 44100) -> bool:
        return self.enabled and len(self.active_bands(sr)) > 0


def eq_params_from_json(data: Optional[Dict[str, Any]]) -> EqParams:
    """Parse the client's `eq` payload; clamp everything to safe ranges.

    Expected shape:
        {"enabled": true,
         "bands": [{"type": "bell", "freq_hz": 350, "gain_db": -2.5,
                    "q": 1.4, "enabled": true}, ...]}
    """
    data = data or {}
    eq = EqParams(enabled=bool(data.get("enabled", False)))
    for raw in (data.get("bands") or [])[:MAX_BANDS]:
        if not isinstance(raw, dict):
            continue
        btype = str(raw.get("type", "bell")).lower()
        if btype not in FILTER_TYPES:
            continue
        try:
            freq = float(raw.get("freq_hz", 1000.0))
            gain = float(raw.get("gain_db", 0.0))
            q = float(raw.get("q", 1.0))
        except (TypeError, ValueError):
            continue
        eq.bands.append(EqBand(
            type=btype,
            freq_hz=float(np.clip(freq, FREQ_MIN_HZ, FREQ_MAX_HZ)),
            gain_db=float(np.clip(gain, -GAIN_LIMIT_DB, GAIN_LIMIT_DB)),
            q=float(np.clip(q, Q_MIN, Q_MAX)),
            enabled=bool(raw.get("enabled", True)),
        ))
    return eq


def _rbj_coeffs(btype: str, f0: float, sr: int,
                gain_db: float, q: float) -> np.ndarray:
    """RBJ Audio-EQ-Cookbook biquad as a 1x6 SOS row.

    `gain_db` here is the DESIGN gain (already halved by the caller for
    the zero-phase double pass).
    """
    A = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * np.pi * f0 / sr
    cos_w0 = np.cos(w0)
    sin_w0 = np.sin(w0)
    q = max(Q_MIN, float(q))
    alpha = sin_w0 / (2.0 * q)

    if btype == "bell":
        b0 = 1 + alpha * A
        b1 = -2 * cos_w0
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cos_w0
        a2 = 1 - alpha / A
    elif btype == "low_shelf":
        two_sqrtA_alpha = 2.0 * np.sqrt(A) * alpha
        b0 = A * ((A + 1) - (A - 1) * cos_w0 + two_sqrtA_alpha)
        b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
        b2 = A * ((A + 1) - (A - 1) * cos_w0 - two_sqrtA_alpha)
        a0 = (A + 1) + (A - 1) * cos_w0 + two_sqrtA_alpha
        a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
        a2 = (A + 1) + (A - 1) * cos_w0 - two_sqrtA_alpha
    elif btype == "high_shelf":
        two_sqrtA_alpha = 2.0 * np.sqrt(A) * alpha
        b0 = A * ((A + 1) + (A - 1) * cos_w0 + two_sqrtA_alpha)
        b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
        b2 = A * ((A + 1) + (A - 1) * cos_w0 - two_sqrtA_alpha)
        a0 = (A + 1) - (A - 1) * cos_w0 + two_sqrtA_alpha
        a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
        a2 = (A + 1) - (A - 1) * cos_w0 - two_sqrtA_alpha
    elif btype == "highpass":
        b0 = (1 + cos_w0) / 2
        b1 = -(1 + cos_w0)
        b2 = (1 + cos_w0) / 2
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha
    elif btype == "lowpass":
        b0 = (1 - cos_w0) / 2
        b1 = 1 - cos_w0
        b2 = (1 - cos_w0) / 2
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha
    elif btype == "notch":
        b0 = 1.0
        b1 = -2 * cos_w0
        b2 = 1.0
        a0 = 1 + alpha
        a1 = -2 * cos_w0
        a2 = 1 - alpha
    else:
        raise ValueError(f"Unknown filter type: {btype}")

    return np.array(
        [[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]],
        dtype=np.float64)


def band_sos(band: EqBand, sr: int) -> np.ndarray:
    """Design SOS row for one band. Gain bands design at half gain so the
    zero-phase double pass lands exactly on `gain_db`."""
    design_gain = band.gain_db / 2.0 if band.type in _GAIN_TYPES else 0.0
    return _rbj_coeffs(band.type, float(band.freq_hz), sr,
                       design_gain, float(band.q))


def compile_sos(eq: EqParams, sr: int) -> Optional[np.ndarray]:
    """Stack all active bands into one (n, 6) SOS cascade, or None."""
    bands = eq.active_bands(sr)
    if not bands:
        return None
    return np.vstack([band_sos(b, sr) for b in bands])


def apply_eq(x: np.ndarray, sr: int, eq: EqParams) -> np.ndarray:
    """Apply the EQ cascade zero-phase over (samples, channels) audio."""
    if not eq.enabled:
        return x
    sos = compile_sos(eq, sr)
    if sos is None:
        return x
    return sosfiltfilt(sos, x, axis=0).astype(np.float32)


def response_db(eq: EqParams, freqs_hz: np.ndarray, sr: int) -> np.ndarray:
    """Effective (post zero-phase) combined response in dB at `freqs_hz`.

    Used by tests and the metrics report; the browser computes the same
    curve in JS for the interactive display.
    """
    from scipy.signal import sosfreqz

    freqs_hz = np.asarray(freqs_hz, dtype=np.float64)
    out = np.zeros_like(freqs_hz)
    sos = compile_sos(eq, sr) if eq.enabled else None
    if sos is None:
        return out
    w = 2.0 * np.pi * freqs_hz / sr
    _, h = sosfreqz(sos, worN=w)
    # Doubled: sosfiltfilt applies the cascade forward and backward.
    return 2.0 * 20.0 * np.log10(np.abs(h) + 1e-12)
