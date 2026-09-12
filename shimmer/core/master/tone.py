"""The tone curve: how far to move each band toward a tone target.

tone_curve() is the engine's rule: the target is an input, never a constant.
The old one changed four times on belief (docs/ARCHITECTURE.md §3); Step 5
decides where targets come from (reference tracks, genre targets) and passes
them in.

Below it, ported unchanged from shimmer/mastering.py (1.1.1) so it could be
nulled first (ARCHITECTURE §19.1 item 1): the 1.1.1 tone target, the
warm/bright tilt, compute_tone_curve and apply_tone_curve. The target
(REF_SHAPE_DB) is the curve that won the 2026-09-09 blind round on 7 of 8
songs; mastering.py's comment block tells its history.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
from scipy.ndimage import gaussian_filter1d

from ..analyze.track import REF_FREQS, analyze_spectrum, relative_band_levels


def tone_curve(measured_db, target_db, freqs_hz, strength: float = 1.0,
               max_boost_db: float = 2.0, max_cut_db: float = 3.0,
               cutoff_hz: Optional[float] = None, deadband_db: float = 0.0) -> np.ndarray:
    """Per-band correction in dB, applied as EQ.

    measured_db   the song's level in each band, relative
    target_db     the target's level in each band, on the same scale
    freqs_hz      each band's centre
    strength      0 = flat, 1 = the full move (within the limits)
    max_boost_db  no band is raised more than this
    max_cut_db    no band is lowered more than this
    cutoff_hz     the song's bandwidth cutoff: nothing at or above 90 % of
                  it is boosted, because there is nothing there but noise
    deadband_db   differences smaller than this are left alone
    """
    measured = np.asarray(measured_db, dtype=np.float64)
    target = np.asarray(target_db, dtype=np.float64)
    freqs = np.asarray(freqs_hz, dtype=np.float64)
    diff = target - measured
    if deadband_db > 0.0:
        diff = np.sign(diff) * np.maximum(0.0, np.abs(diff) - deadband_db)
    curve = np.clip(float(strength) * diff, -abs(max_cut_db), abs(max_boost_db))
    if cutoff_hz:
        above = freqs >= 0.9 * float(cutoff_hz)
        curve[above] = np.minimum(curve[above], 0.0)
    return curve


# ── 1.1.1's tone target and tone curve, ported unchanged ────────────────

# 1/3-octave band power of a finished master, in dB, on REF_FREQS. Restored
# 2026-09-09 by listening (won 7 of 8 blind, 1 tie); see mastering.py.
REF_SHAPE_DB = np.array([
    -3.7, 4.3, 8.3, 8.8, 7.9, 7.4, 7.4,
    6.3, 4.5, 2.1, 0.3, -0.7, 0.0, 0.5,
    -1.5, -1.5, -1.4, -0.7, 0.0, 0.6, 0.7,
    1.1, -0.1, -1.0, -0.4, -1.5, -5.8, -13.1,
    -25.4,
], dtype=np.float64)
# How far a real master may sit from the target and still be normal, per
# band (derived by scripts/derive_tone_target.py). Not used by
# compute_tone_curve in 1.1.1, which has no deadband; Step 5 decides.
REF_TOL_DB = np.array([
    7.0, 7.0, 5.9, 3.6, 4.0, 3.9, 4.9,
    2.8, 2.9, 3.4, 1.8, 3.4, 1.8, 1.5,
    1.5, 2.5, 2.2, 2.4, 2.9, 3.0, 3.0,
    4.0, 3.2, 4.0, 4.2, 4.3, 5.4, 5.5,
    7.3,
], dtype=np.float64)
_MID_BANDS = (REF_FREQS >= 200.0) & (REF_FREQS <= 2000.0)
REF_DB = REF_SHAPE_DB - np.median(REF_SHAPE_DB[_MID_BANDS])

_MAX_EQ_BOOST_DB = 2.0    # static tone curve max boost
_MAX_EQ_CUT_DB = 3.0      # static tone curve max cut
_HARSH_LO_HZ = 5000.0     # the band AI fizz lives in
_HARSH_HI_HZ = 12000.0
_HARSH_MAX_BOOST_DB = 2.0

# Stylistic warm<->bright tilt (5-position tone control): the tilt amplitude
# in dB at the frequency extremes; positive = bright, negative = warm.
TILT_POSITIONS: Dict[str, float] = {
    "warmer": -2.0, "warm": -1.0, "neutral": 0.0, "bright": 1.0, "brightest": 2.0,
}

# Mastering "intensity": how much of the corrective move to make.
INTENSITY_STRENGTH: Dict[str, float] = {"low": 0.25, "med": 0.55, "high": 0.85}


def intensity_to_strength(intensity: str) -> float:
    return INTENSITY_STRENGTH.get(str(intensity).lower(), 0.55)


def tilt_offsets_db(tilt: str) -> np.ndarray:
    """Per-band dB offsets for a warm<->bright tilt position.

    Smooth tanh ramp in log-frequency space centered at 1 kHz, reaching
    ~90% of the tilt amplitude at the spectrum extremes. Unknown or
    'neutral' positions return all zeros.
    """
    amount = TILT_POSITIONS.get(str(tilt or "neutral").lower(), 0.0)
    if abs(amount) < 1e-9:
        return np.zeros(REF_FREQS.size, dtype=np.float64)
    ramp = np.tanh(np.log2(REF_FREQS / 1000.0) / 3.0)
    return amount * ramp


def compute_tone_curve(x_raw: np.ndarray, sr: int, strength: float = 1.0,
                       raw_spectrum: Optional[Dict[str, Any]] = None,
                       tilt: str = "neutral",
                       cutoff_hz: Optional[float] = None) -> List[float]:
    """Compute the bounded static tone curve from the RAW input analysis.

    Must be called on the unprocessed input, before any artifact cleaning:
    the curve is calculated once and never recomputed after cleaning (a
    post-clean tone match would boost back the harsh peaks the cleaner
    removed).

    `tilt` adds a stylistic warm<->bright offset on top of the corrective
    match. It is independent of `strength`, but shares all safety bounds
    with the correction.

    Bounds: boost <= +2.0 dB, cut <= -3.0 dB, 1/3-octave smoothing, no
    boost above the source's bandwidth cutoff.

    Returns per-band correction in dB aligned with REF_FREQS.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    tilt_delta = tilt_offsets_db(tilt)
    has_tilt = float(np.max(np.abs(tilt_delta))) > 1e-9
    if strength < 1e-4 and not has_tilt:
        return [0.0] * len(REF_FREQS)

    if strength < 1e-4:
        delta = tilt_delta.copy()
    else:
        spec = raw_spectrum if raw_spectrum is not None else analyze_spectrum(x_raw, sr)
        if "rel_db" in spec:
            measured = np.array(spec["rel_db"], dtype=np.float64)
        else:
            # Older callers: band power derived from the per-bin levels.
            bw = REF_FREQS * (2 ** (1 / 6) - 2 ** (-1 / 6))
            measured = relative_band_levels(
                np.array(spec["band_db"], dtype=np.float64) + 10.0 * np.log10(bw))
        # Shape against shape: positive correction = boost where the track
        # sits under the reference, negative = cut where it sits over.
        delta = (REF_DB - measured) * strength + tilt_delta
    delta = np.clip(delta, -_MAX_EQ_CUT_DB, _MAX_EQ_BOOST_DB)
    delta = gaussian_filter1d(delta, sigma=1.0)  # ~1/3-octave smoothing

    # Harshness guard: the 5-12 kHz band where AI fizz lives.
    harsh = (REF_FREQS >= _HARSH_LO_HZ) & (REF_FREQS <= _HARSH_HI_HZ)
    delta[harsh] = np.minimum(delta[harsh], _HARSH_MAX_BOOST_DB)
    # Bandwidth guard: never boost above the source's cutoff. There is
    # nothing there to match a reference against, only residue.
    if cutoff_hz is not None and cutoff_hz > 0:
        above = REF_FREQS >= 0.9 * float(cutoff_hz)
        delta[above] = np.minimum(delta[above], 0.0)
    # Re-clip after smoothing so bounds are hard guarantees.
    delta = np.clip(delta, -_MAX_EQ_CUT_DB, _MAX_EQ_BOOST_DB)
    return delta.tolist()


def _interp_correction(freqs_hz: np.ndarray, correction_db: np.ndarray,
                       n_fft: int, sr: int) -> np.ndarray:
    """Interpolate per-band correction to linear FFT bins."""
    fft_freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    return np.interp(
        fft_freqs, freqs_hz.astype(np.float64),
        correction_db.astype(np.float64),
        left=correction_db[0], right=correction_db[-1],
    ).astype(np.float64)


def apply_tone_curve(x: np.ndarray, sr: int, correction_db: List[float]) -> np.ndarray:
    """Apply a precomputed static tone curve (zero-phase STFT domain)."""
    delta = np.asarray(correction_db, dtype=np.float64)
    if delta.size != REF_FREQS.size:
        raise ValueError("correction_db length mismatch with REF_FREQS")
    a = np.asarray(x, dtype=np.float32)
    x2 = a[:, None] if a.ndim == 1 else a
    if float(np.max(np.abs(delta))) < 1e-3:
        return x2

    n_fft = 4096
    hop = n_fft // 4
    x2 = np.asarray(x2, dtype=np.float64)
    n_samples, n_ch = x2.shape
    corr_lin = 10.0 ** (_interp_correction(REF_FREQS, delta, n_fft, sr) / 20.0)
    window = np.hanning(n_fft).astype(np.float64)
    out = np.zeros_like(x2)

    # Zero-pad both ends so every real sample gets full overlapping window
    # coverage — otherwise the wsum normalisation divides by near-zero at
    # the edges and creates massive spikes.
    pad = n_fft
    n_padded = n_samples + 2 * pad

    for ch in range(n_ch):
        xp = np.zeros(n_padded, dtype=np.float64)
        xp[pad:pad + n_samples] = x2[:, ch]
        y = np.zeros(n_padded, dtype=np.float64)
        wsum = np.zeros(n_padded, dtype=np.float64)
        for s0 in range(0, n_padded - n_fft + 1, hop):
            spec_c = np.fft.rfft(xp[s0:s0 + n_fft] * window)
            spec_c *= corr_lin[: spec_c.size]
            frame_out = np.fft.irfft(spec_c, n=n_fft)
            y[s0:s0 + n_fft] += frame_out * window
            wsum[s0:s0 + n_fft] += window ** 2
        mask = wsum > 1e-6
        y[mask] /= wsum[mask]
        out[:, ch] = y[pad:pad + n_samples]

    return out.astype(np.float32)
