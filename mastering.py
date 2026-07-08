"""
mastering.py — True mastering chain (LUFS, tone curve, true-peak limiter).

Pure NumPy/SciPy — no file I/O, no server imports.

Safe-mastering architecture:
  * The tone curve is computed from the RAW, unprocessed input only
    (compute_tone_curve) and applied BEFORE artifact cleaning
    (apply_tone_curve) — never after, so corrective EQ cannot re-boost
    the harsh peaks the cleaner just removed. Bounds: +2.0 / -3.0 dB,
    with boosts additionally limited in the 5-12 kHz harshness band.
  * master() is single-pass: HP/DC -> one static LUFS gain ->
    soft peak shaper (top ~2 dB) -> one 4x-oversampled lookahead
    true-peak limiter. No iterative gain/limit loops.
  * Export ceilings are codec-aware: WAV/FLAC -1.0 dBTP, lossy -1.5 dBTP
    (get_export_ceiling_dbtp) so MP3/AAC decoders don't clip.
"""

from __future__ import annotations

import _winfix  # noqa: F401

import math
from dataclasses import asdict
from typing import Any, Dict, List, Tuple

import numpy as np
from scipy.signal import resample_poly
from scipy.ndimage import gaussian_filter1d, maximum_filter1d

from dsp import as_2d, apply_highpass, db_to_lin, lin_to_db
from params import MasterParams, LOUDNESS_TARGETS, intensity_to_eq_strength


# Neutral long-term spectrum reference (dB relative, 1/3-octave centers).
# Gentle tilt: slightly less sub, slight air lift — not a smiley curve.
_REF_FREQS = np.array([
    31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
    800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000,
    10000, 12500, 16000, 20000,
], dtype=np.float64)
_REF_DB = np.array([
    -2, -1.5, -1, -0.5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0.5, 1, 1.5, 2,
], dtype=np.float64)

_MAX_EQ_BOOST_DB = 2.0    # static tone curve max boost
_MAX_EQ_CUT_DB = 3.0      # static tone curve max cut

# Stylistic warm<->bright tilt (5-position tone control). The value is
# the tilt amplitude in dB at the frequency extremes; positive = bright
# (boost highs / shave lows), negative = warm. Applied as an offset to
# the corrective delta BEFORE the hard clip and the 5-12 kHz harshness
# guard, so those bounds remain absolute guarantees.
TILT_POSITIONS: dict[str, float] = {
    "warmer": -2.0,
    "warm": -1.0,
    "neutral": 0.0,
    "bright": 1.0,
    "brightest": 2.0,
}
_HARSH_LO_HZ = 5000.0     # harshness band: boosts are limited here...
_HARSH_HI_HZ = 12000.0    # ...so EQ can't reintroduce AI fizz
_HARSH_MAX_BOOST_DB = 0.5
_OVERSAMPLE = 4

# Codec-aware true-peak export ceilings (dBTP). Lossy encoders overshoot
# on decode, so they get extra headroom.
_CEILING_LOSSLESS_DBTP = -1.0
_CEILING_LOSSY_DBTP = -1.5
_LOSSY_FORMATS = {"mp3", "m4a", "aac", "ogg", "opus", "mp4"}


def get_export_ceiling_dbtp(export_format: str) -> float:
    """True-peak ceiling for an export format ('wav', 'mp3', '.flac', ...)."""
    fmt = str(export_format or "").lower().lstrip(".").strip()
    return _CEILING_LOSSY_DBTP if fmt in _LOSSY_FORMATS else _CEILING_LOSSLESS_DBTP


def _mono_mix(x: np.ndarray) -> np.ndarray:
    x = as_2d(np.asarray(x, dtype=np.float64))
    if x.shape[1] == 1:
        return x[:, 0]
    return np.mean(x, axis=1)


def remove_dc(x: np.ndarray) -> np.ndarray:
    x = as_2d(np.asarray(x, dtype=np.float32))
    return (x - np.mean(x, axis=0, keepdims=True)).astype(np.float32)


def measure_true_peak_db(x: np.ndarray, sr: int, oversample: int = _OVERSAMPLE) -> float:
    """4x oversampled true peak in dBTP."""
    mono = _mono_mix(x)
    if mono.size == 0:
        return -120.0
    if oversample > 1:
        up = resample_poly(mono, oversample, 1).astype(np.float64)
    else:
        up = mono
    peak = float(np.max(np.abs(up)))
    return float(lin_to_db(peak))


def measure_loudness(x: np.ndarray, sr: int) -> Dict[str, float]:
    """Integrated LUFS, LRA, and true peak (dBTP)."""
    import pyloudnorm as pyln

    x = as_2d(np.asarray(x, dtype=np.float64))
    meter = pyln.Meter(sr)
    try:
        lufs_i = float(meter.integrated_loudness(x))
    except Exception:
        lufs_i = float("-inf")
    try:
        lra = float(meter.loudness_range(x))
    except Exception:
        lra = 0.0
    tp = measure_true_peak_db(x, sr)
    return {
        "lufs_i": lufs_i,
        "lra": lra,
        "true_peak_dbtp": tp,
    }


def analyze_spectrum(x: np.ndarray, sr: int,
                     n_fft: int = 8192) -> Dict[str, Any]:
    """Long-term magnitude spectrum on 1/3-octave centers (dB)."""
    mono = _mono_mix(np.asarray(x, dtype=np.float64))
    if mono.size < n_fft:
        n_fft = max(512, 1 << int(math.ceil(math.log2(max(mono.size, 2)))))
    hop = n_fft // 4
    window = np.hanning(n_fft).astype(np.float64)
    n_frames = max(1, 1 + (mono.size - n_fft) // hop)
    acc = np.zeros(n_fft // 2 + 1, dtype=np.float64)
    for i in range(n_frames):
        s0 = i * hop
        frame = mono[s0:s0 + n_fft]
        if frame.size < n_fft:
            break
        spec = np.abs(np.fft.rfft(frame * window)) ** 2
        acc += spec
    acc /= max(1, n_frames)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    power_db = 20.0 * np.log10(acc + 1e-12)

    band_db: List[float] = []
    for cf in _REF_FREQS:
        lo = cf / (2 ** (1 / 6))
        hi = cf * (2 ** (1 / 6))
        idx = np.where((freqs >= lo) & (freqs <= hi))[0]
        if idx.size == 0:
            band_db.append(-120.0)
        else:
            band_db.append(float(np.mean(power_db[idx])))

    return {
        "freqs_hz": _REF_FREQS.tolist(),
        "band_db": band_db,
    }


def _interp_correction(freqs_hz: np.ndarray, correction_db: np.ndarray,
                       n_fft: int, sr: int) -> np.ndarray:
    """Interpolate per-band correction to linear FFT bins."""
    fft_freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    return np.interp(
        fft_freqs, freqs_hz.astype(np.float64),
        correction_db.astype(np.float64),
        left=correction_db[0], right=correction_db[-1],
    ).astype(np.float64)


def tilt_offsets_db(tilt: str) -> np.ndarray:
    """Per-band dB offsets for a warm<->bright tilt position.

    Smooth tanh ramp in log-frequency space centered at 1 kHz, reaching
    ~90% of the tilt amplitude at the spectrum extremes. Unknown or
    'neutral' positions return all zeros.
    """
    amount = TILT_POSITIONS.get(str(tilt or "neutral").lower(), 0.0)
    if abs(amount) < 1e-9:
        return np.zeros(_REF_FREQS.size, dtype=np.float64)
    ramp = np.tanh(np.log2(_REF_FREQS / 1000.0) / 3.0)
    return amount * ramp


def compute_tone_curve(x_raw: np.ndarray, sr: int, strength: float = 1.0,
                       raw_spectrum: Dict[str, Any] | None = None,
                       tilt: str = "neutral") -> List[float]:
    """Compute the bounded static tone curve from the RAW input analysis.

    Must be called on the unprocessed input, before any artifact
    cleaning — the curve is calculated once and never recomputed after
    cleaning (a post-clean tone match would boost back the harsh peaks
    the cleaner removed).

    `tilt` adds a stylistic warm<->bright offset (see TILT_POSITIONS)
    on top of the corrective match. It is independent of `strength` —
    the user's tone choice applies in full even when correction is
    dialed down — but shares all safety bounds with the correction.

    Bounds: boost <= +2.0 dB, cut <= -3.0 dB, 1/3-octave smoothing,
    boosts additionally capped at +0.5 dB inside 5-12 kHz.

    Returns per-band correction in dB aligned with `_REF_FREQS`.
    """
    strength = float(np.clip(strength, 0.0, 1.0))
    tilt_delta = tilt_offsets_db(tilt)
    has_tilt = float(np.max(np.abs(tilt_delta))) > 1e-9
    if strength < 1e-4 and not has_tilt:
        return [0.0] * len(_REF_FREQS)

    if strength < 1e-4:
        delta = tilt_delta.copy()
    else:
        spec = raw_spectrum if raw_spectrum is not None else analyze_spectrum(x_raw, sr)
        measured = np.array(spec["band_db"], dtype=np.float64)
        # Relative to reference: positive correction = boost where track is weak.
        delta = (_REF_DB - measured) * strength + tilt_delta
    delta = np.clip(delta, -_MAX_EQ_CUT_DB, _MAX_EQ_BOOST_DB)
    delta = gaussian_filter1d(delta, sigma=1.0)  # ~1/3-octave smoothing

    # Harshness guard: never boost meaningfully in the 5-12 kHz band
    # where AI fizz/shimmer lives (cuts remain allowed).
    harsh = (_REF_FREQS >= _HARSH_LO_HZ) & (_REF_FREQS <= _HARSH_HI_HZ)
    delta[harsh] = np.minimum(delta[harsh], _HARSH_MAX_BOOST_DB)
    # Re-clip after smoothing so bounds are hard guarantees.
    delta = np.clip(delta, -_MAX_EQ_CUT_DB, _MAX_EQ_BOOST_DB)
    return delta.tolist()


def apply_tone_curve(x: np.ndarray, sr: int,
                     correction_db: List[float]) -> np.ndarray:
    """Apply a precomputed static tone curve (zero-phase STFT domain)."""
    delta = np.asarray(correction_db, dtype=np.float64)
    if delta.size != _REF_FREQS.size:
        raise ValueError("correction_db length mismatch with _REF_FREQS")
    if float(np.max(np.abs(delta))) < 1e-3:
        return as_2d(np.asarray(x, dtype=np.float32))

    n_fft = 4096
    hop = n_fft // 4
    x2 = as_2d(np.asarray(x, dtype=np.float64))
    n_samples, n_ch = x2.shape
    corr_lin = db_to_lin(_interp_correction(_REF_FREQS, delta, n_fft, sr))
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


def tone_match_eq(x: np.ndarray, sr: int, strength: float = 1.0,
                  raw_spectrum: Dict[str, Any] | None = None,
                  tilt: str = "neutral") -> Tuple[np.ndarray, List[float]]:
    """Compute the tone curve from `x` (which must be RAW audio) and apply it.

    Convenience wrapper for compute_tone_curve + apply_tone_curve.
    Returns (processed_audio, per-band correction dB applied).
    """
    delta = compute_tone_curve(x, sr, strength=strength,
                               raw_spectrum=raw_spectrum, tilt=tilt)
    return apply_tone_curve(x, sr, delta), delta


def _peak_hold_release(x: np.ndarray, coeff: float) -> np.ndarray:
    """Vectorized peak-hold with exponential decay:

        y[i] = max(x[i], y[i-1] * coeff)

    Instant attack (y snaps up to x), exponential release. Computed
    blockwise with the scaled-cummax trick so no per-sample Python loop
    is needed; block size is bounded so coeff**-block stays well inside
    float64 range.
    """
    x = np.asarray(x, dtype=np.float64)
    n = x.size
    if n == 0 or coeff <= 0.0:
        return x.copy()
    # coeff**-B <= 1e12  =>  B <= 12*ln(10) / -ln(coeff)
    block = int(min(8192.0, max(1.0, 12.0 * math.log(10.0)
                                / max(1e-12, -math.log(min(coeff, 0.9999999))))))
    out = np.empty(n, dtype=np.float64)
    state = 0.0
    for s in range(0, n, block):
        blk = x[s:s + block]
        m = blk.size
        k = np.arange(1, m + 1, dtype=np.float64)
        decay = coeff ** k
        within = np.maximum.accumulate(blk / decay) * decay
        res = np.maximum(within, state * decay)
        out[s:s + m] = res
        state = float(res[-1])
    return out


def soft_peak_shaper(x: np.ndarray, ceiling_dbtp: float = -1.0,
                     knee_db: float = 2.0) -> Tuple[np.ndarray, Dict[str, float]]:
    """Gentle waveshaper catching the top ~`knee_db` dB before the limiter.

    Below the knee the signal is bit-transparent (identity). Inside the
    knee, peaks are smoothly compressed with a cubic soft clip that
    approaches (but never quite reaches) ~1 dB above the ceiling, so the
    true-peak limiter that follows only has to shave the last fraction
    of a dB instead of doing all the work — that keeps limiter gain
    reduction (and pumping) low.
    """
    x = as_2d(np.asarray(x, dtype=np.float64))
    ceiling = float(db_to_lin(ceiling_dbtp))
    knee_start = float(ceiling * db_to_lin(-abs(knee_db)))  # e.g. -3 dBTP for -1/2
    span = max(1e-9, ceiling * 1.12 - knee_start)  # allow ~1 dB overshoot pre-limiter

    ax = np.abs(x)
    over = ax > knee_start
    if not np.any(over):
        return x.astype(np.float32), {"shaped_ratio": 0.0}

    t = np.clip((ax[over] - knee_start) / span, 0.0, None)
    # Smooth rational saturator: t / (1 + t) maps [0, inf) -> [0, 1).
    shaped = knee_start + span * (t / (1.0 + t))
    y = x.copy()
    y[over] = np.sign(x[over]) * shaped
    return y.astype(np.float32), {
        "shaped_ratio": float(np.mean(over)),
    }


def true_peak_limiter(x: np.ndarray, sr: int,
                      ceiling_dbtp: float = -1.0,
                      lookahead_ms: float = 2.0,
                      release_ms: float = 50.0) -> Tuple[np.ndarray, Dict[str, float]]:
    """Lookahead brickwall limiter with oversampled true-peak detection."""
    x = as_2d(np.asarray(x, dtype=np.float64))
    ceiling = float(db_to_lin(ceiling_dbtp))
    n_samples, n_ch = x.shape
    if n_samples == 0:
        return x.astype(np.float32), {
            "max_gain_reduction_db": 0.0,
            "ceiling_dbtp": float(ceiling_dbtp),
        }

    # True-peak envelope at audio rate: oversample each channel, rectify,
    # then take the max of each oversampled group so inter-sample peaks
    # are caught without changing the timeline length.
    if _OVERSAMPLE > 1:
        peak_env = np.zeros(n_samples, dtype=np.float64)
        for ch in range(n_ch):
            up = np.abs(resample_poly(x[:, ch], _OVERSAMPLE, 1))
            need = n_samples * _OVERSAMPLE
            if up.size < need:
                up = np.pad(up, (0, need - up.size))
            grp = up[:need].reshape(n_samples, _OVERSAMPLE).max(axis=1)
            peak_env = np.maximum(peak_env, grp)
    else:
        peak_env = np.max(np.abs(x), axis=1)

    # Forward-looking windowed max: each sample sees peaks up to
    # lookahead_n samples ahead (NOT the whole remaining file).
    lookahead_n = max(1, int(round(lookahead_ms * 0.001 * sr)))
    if lookahead_n > 1:
        # Shift the filter window right so it covers [i, i + n).
        origin = -(lookahead_n // 2)
        env = maximum_filter1d(peak_env, size=lookahead_n,
                               mode="nearest", origin=origin)
    else:
        env = peak_env

    gain = np.minimum(1.0, ceiling / np.maximum(env, 1e-12))

    # Smooth gain recovery (release); attack is instantaneous via lookahead.
    release_coeff = math.exp(-1.0 / (max(1e-4, release_ms * 0.001) * sr))
    g_smooth = 1.0 - _peak_hold_release(1.0 - gain, release_coeff)

    min_gain = float(np.min(g_smooth))
    max_gr_db = 20.0 * math.log10(max(min_gain, 1e-12)) if min_gain < 1.0 else 0.0

    y = (x * g_smooth[:, None]).astype(np.float32)
    return y, {
        "max_gain_reduction_db": float(max_gr_db),
        "ceiling_dbtp": float(ceiling_dbtp),
    }


def resolve_eq_strength(mp: MasterParams) -> float:
    """Effective tone-curve strength from MasterParams (intensity wins)."""
    if mp.intensity and mp.intensity in ("low", "med", "high"):
        return intensity_to_eq_strength(mp.intensity)
    return float(np.clip(mp.eq_strength, 0.0, 1.0))


def apply_gain_to_lufs(x: np.ndarray, sr: int, target_lufs: float) -> Tuple[np.ndarray, float]:
    """Linear gain to reach target integrated LUFS."""
    m = measure_loudness(x, sr)
    current = m["lufs_i"]
    if not math.isfinite(current) or current < -70:
        return as_2d(np.asarray(x, dtype=np.float32)), 0.0
    gain_db = float(target_lufs - current)
    gain_lin = float(db_to_lin(gain_db))
    y = (as_2d(np.asarray(x, dtype=np.float32)) * gain_lin).astype(np.float32)
    return y, gain_db


def tpdf_dither(x: np.ndarray, bits: int = 16) -> np.ndarray:
    """TPDF dither for fixed-point export."""
    x = as_2d(np.asarray(x, dtype=np.float64))
    lsb = 1.0 / (2 ** (bits - 1))
    r1 = np.random.uniform(-lsb, lsb, x.shape)
    r2 = np.random.uniform(-lsb, lsb, x.shape)
    return (x + r1 + r2).astype(np.float32)


def master(x: np.ndarray, sr: int, mp: MasterParams,
           analysis: Dict[str, Any] | None = None,
           eq_bands_db: List[float] | None = None
           ) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Run the single-pass mastering chain. Returns (audio, report dict).

    Chain: HP/DC -> one static LUFS gain -> soft peak shaper ->
    one 4x-oversampled lookahead true-peak limiter.

    No tone EQ happens here — the static tone curve must be applied
    BEFORE artifact cleaning (see compute_tone_curve / apply_tone_curve).
    Pass `eq_bands_db` (the curve applied upstream) so it lands in the
    report for the UI.
    """
    if not mp.enabled:
        return as_2d(np.asarray(x, dtype=np.float32)), {"enabled": False}

    y = as_2d(np.asarray(x, dtype=np.float32))
    before = measure_loudness(y, sr)
    before_spec = analysis.get("spectrum") if analysis else None
    if before_spec is None:
        before_spec = analyze_spectrum(y, sr)

    # HP + DC
    if mp.hp_hz > 0:
        y = remove_dc(y)
        y = apply_highpass(y, sr, mp.hp_hz)

    # One static LUFS gain — measured once, applied once. The limiter
    # may pull the final integrated value slightly below target; that
    # small shortfall is the price of not crushing the mix with
    # iterative gain/limit passes.
    target = float(mp.target_lufs)
    y, gain_db = apply_gain_to_lufs(y, sr, target)

    # Dual-stage peak control: shaper takes the top ~2 dB, limiter
    # trims true peaks to the ceiling in a single pass.
    y, shaper_stats = soft_peak_shaper(y, ceiling_dbtp=mp.ceiling_dbtp)
    y, limiter_stats = true_peak_limiter(
        y, sr, ceiling_dbtp=mp.ceiling_dbtp,
        lookahead_ms=mp.lookahead_ms,
        release_ms=mp.release_ms,
    )

    after = measure_loudness(y, sr)
    after_spec = analyze_spectrum(y, sr)

    report: Dict[str, Any] = {
        "enabled": True,
        "target_lufs": target,
        "current_lufs": before["lufs_i"],
        "gain_db": float(gain_db),
        "ceiling_dbtp": float(mp.ceiling_dbtp),
        "estimated_true_peak": after["true_peak_dbtp"],
        "limiter_gain_reduction": limiter_stats.get("max_gain_reduction_db", 0.0),
        "eq_bands_db": list(eq_bands_db) if eq_bands_db is not None else [],
        "tilt": mp.tilt,
        "before": before,
        "after": after,
        "spectrum_before": before_spec,
        "spectrum_after": after_spec,
        "total_gain_db": float(gain_db),
        "shaper": shaper_stats,
        "limiter": limiter_stats,
        "lufs_error": float(after["lufs_i"] - target) if math.isfinite(after["lufs_i"]) else None,
        "ab_match_gain_db": float(
            before["lufs_i"] - after["lufs_i"]
        ) if math.isfinite(before["lufs_i"]) and math.isfinite(after["lufs_i"]) else 0.0,
    }
    return y.astype(np.float32), report


def master_params_from_json(data: Dict[str, Any] | None) -> MasterParams:
    """Build MasterParams from API/CLI JSON fragment."""
    if not data:
        return MasterParams()
    mp = MasterParams()
    if "enabled" in data:
        mp.enabled = bool(data["enabled"])
    if "target" in data and data["target"] in LOUDNESS_TARGETS:
        mp.target_lufs = LOUDNESS_TARGETS[data["target"]]
    if "target_lufs" in data and data["target_lufs"] is not None:
        mp.target_lufs = float(data["target_lufs"])
    if "ceiling_dbtp" in data and data["ceiling_dbtp"] is not None:
        mp.ceiling_dbtp = float(data["ceiling_dbtp"])
    if "eq_strength" in data and data["eq_strength"] is not None:
        mp.eq_strength = float(data["eq_strength"])
    if "intensity" in data and data["intensity"]:
        mp.intensity = str(data["intensity"]).lower()
    if "tilt" in data and data["tilt"]:
        t = str(data["tilt"]).lower()
        if t in TILT_POSITIONS:
            mp.tilt = t
    if "hp_hz" in data and data["hp_hz"] is not None:
        mp.hp_hz = float(data["hp_hz"])
    return mp


def analyze_track(x: np.ndarray, sr: int) -> Dict[str, Any]:
    """Full analysis snapshot for /api/analyze."""
    loud = measure_loudness(x, sr)
    spec = analyze_spectrum(x, sr)
    return {
        "loudness": loud,
        "spectrum": spec,
    }
