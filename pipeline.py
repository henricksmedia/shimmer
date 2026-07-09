"""
pipeline.py — Safe processing pipeline orchestrator.

Implements the Shimmer architecture end to end:

  raw input analysis
  -> bounded static tone curve (from RAW analysis, applied pre-clean)
  -> complementary linear-phase FIR crossover
  -> low/mid bypass
  -> high-band M/S: gentle Mid cleaning, stronger Side cleaning
     (transient hold protection lives inside the engine)
  -> Side width compensation
  -> M/S decode, low/high recombination
  -> post filters + fade
  -> mastering (single static LUFS gain, soft peak shaper,
     4x oversampled true-peak limiter, codec-aware ceiling)
  -> removed-signal audition track

The full mix never passes through the STFT artifact engine — only the
high band does, so kick, bass, vocals and leads keep their phase,
punch and body untouched.
"""

from __future__ import annotations

import _winfix  # noqa: F401

from dataclasses import replace
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from bands import (
    channels_first_to_samples,
    complementary_fir_split,
    decode_ms,
    encode_ms,
    ensure_stereo_channels_first,
    recombine_bands,
    side_width_compensation,
)
from dsp import as_2d
from engine import apply_post_filters, process
from eq import EqParams, apply_eq
from mastering import (
    apply_tone_curve,
    compute_tone_curve,
    master,
    resolve_eq_strength,
)
from params import MasterParams, Params, apply_preset_strength


def _scaled_params(p: Params, scale: float) -> Params:
    """Copy `p` with all amount-style cleaning strengths scaled by `scale`.

    Uses the same whitelist as the preset-strength slider, so band
    edges, thresholds and time constants stay untouched. Post filters
    and fades are stripped — the pipeline applies those once on the
    recombined full-range signal, not per M/S band.
    """
    q = replace(p)
    apply_preset_strength(q, float(scale))
    q.high_shelf_db = 0.0
    q.high_shelf_hz = 0.0
    q.subsonic_hz = 0.0
    q.presence_hz = 0.0
    q.presence_db = 0.0
    q.fade_ms = 0.0
    q.mix = 1.0  # wet/dry is applied by the caller on the full signal
    return q


def _clean_channel(mono: np.ndarray, sr: int, q: Params,
                   progress: Optional[Callable[[float], None]]) -> np.ndarray:
    """Run the STFT artifact engine on a single (mono) M/S channel."""
    y = process(mono[:, None].astype(np.float32), sr, q,
                progress_callback=progress)
    y = np.asarray(y, dtype=np.float32)
    if y.ndim > 1:
        y = y[:, 0]
    n = mono.shape[0]
    if y.shape[0] < n:
        y = np.pad(y, (0, n - y.shape[0]))
    return y[:n]


def clean_and_master(
    x: np.ndarray,
    sr: int,
    p: Params,
    master_params: Optional[MasterParams] = None,
    progress_callback: Optional[Callable[[float], None]] = None,
    raw_analysis: Optional[Dict[str, Any]] = None,
    eq_params: Optional[EqParams] = None,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """Run the full safe pipeline.

    Args:
        x: audio, (samples,) or (samples, channels) float32.
        sr: sample rate.
        p: artifact-engine params (preset + user strength already applied).
        master_params: None = no mastering stage (cleaning only).
        progress_callback: optional callable(0..1).
        raw_analysis: optional /api/analyze snapshot of the RAW input
            ({'spectrum': ...}); reused for the tone curve so it is
            never recomputed from processed audio.
        eq_params: optional user parametric EQ, applied post-clean and
            pre-master so the limiter catches any boosts.

    Returns:
        (processed, removed, report)
        `processed` and `removed` are (samples, channels) float32 with
        the input's channel count. `removed` is what cleaning stripped
        (unboosted — auditioning boost is a UI concern).
    """
    x_in = as_2d(np.asarray(x, dtype=np.float32))
    n_in, ch_in = x_in.shape

    def _prog(frac: float) -> None:
        if progress_callback:
            progress_callback(float(np.clip(frac, 0.0, 1.0)))

    report: Dict[str, Any] = {}

    # ── 1. Bounded static tone curve from RAW analysis, applied pre-clean ──
    tone_delta = [0.0]
    use_mastering = master_params is not None and master_params.enabled
    if use_mastering:
        eq_strength = resolve_eq_strength(master_params)
        raw_spectrum = (raw_analysis or {}).get("spectrum")
        tone_delta = compute_tone_curve(
            x_in, sr, strength=eq_strength, raw_spectrum=raw_spectrum,
            tilt=master_params.tilt)
        x_toned = apply_tone_curve(x_in, sr, tone_delta)
    else:
        x_toned = x_in
    report["tone_curve_db"] = list(tone_delta)
    _prog(0.05)

    # ── 2. Complementary FIR crossover: low/mid bypasses everything ──────
    cf = ensure_stereo_channels_first(x_toned)
    low, high = complementary_fir_split(
        cf, sr, crossover_hz=float(p.crossover_hz),
        numtaps=int(p.crossover_taps))

    # ── 3. High band to M/S; Side cleaned harder than Mid ────────────────
    mid, side = encode_ms(high)

    p_mid = _scaled_params(p, p.ms_mid_scale)
    p_side = _scaled_params(p, p.ms_side_scale)

    clean_mid = _clean_channel(
        mid, sr, p_mid, lambda f: _prog(0.05 + 0.40 * f))
    clean_side = _clean_channel(
        side, sr, p_side, lambda f: _prog(0.45 + 0.40 * f))

    # ── 4. Removed signal (pre-compensation cleaning diff) ───────────────
    removed_mid = (mid[:clean_mid.shape[0]] - clean_mid).astype(np.float32)
    removed_side = (side[:clean_side.shape[0]] - clean_side).astype(np.float32)
    removed_cf = decode_ms(removed_mid, removed_side)

    # ── 5. Side width compensation ────────────────────────────────────────
    clean_side, swc_stats = side_width_compensation(
        side, clean_side, sr,
        attenuation_threshold_db=float(p.swc_threshold_db),
        max_makeup_db=float(p.swc_max_makeup_db),
        smoothing_ms=float(p.swc_smoothing_ms),
    )
    report["side_width_compensation"] = swc_stats

    # ── 6. Decode + recombine with the untouched low band ────────────────
    high_clean = decode_ms(clean_mid, clean_side)
    out_cf = recombine_bands(low, high_clean)

    # Wet/dry mix against the toned (pre-split) signal.
    mix = float(np.clip(p.mix, 0.0, 1.0))
    if mix < 1.0:
        out_cf = (mix * out_cf + (1.0 - mix) * cf[:, :out_cf.shape[1]]).astype(np.float32)
        removed_cf = (mix * removed_cf).astype(np.float32)

    y = channels_first_to_samples(out_cf)
    removed = channels_first_to_samples(removed_cf)

    # Restore the input's channel count (mono in -> mono out).
    if ch_in == 1:
        y = y[:, :1]
        removed = removed[:, :1]
    n = min(n_in, y.shape[0])
    y, removed = y[:n, :], removed[:n, :]

    # ── 7. Post filters + fade on the full-range signal, once ────────────
    y = apply_post_filters(y, sr, p)

    fade = int(sr * (float(p.fade_ms) / 1000.0))
    if fade > 1 and y.shape[0] > 2 * fade:
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)[:, None]
        y[:fade, :] *= ramp
        y[-fade:, :] *= ramp[::-1]
    _prog(0.9)

    # ── 7b. User parametric EQ (zero-phase), pre-master ──────────────────
    if eq_params is not None and eq_params.is_active(sr):
        y = apply_eq(y, sr, eq_params)
        report["eq"] = {
            "enabled": True,
            "bands": len(eq_params.active_bands(sr)),
        }
    else:
        report["eq"] = {"enabled": False}

    # ── 8. Mastering (single-pass, true-peak safe) ───────────────────────
    if use_mastering:
        y, m_report = master(
            y, sr, master_params, analysis=raw_analysis,
            eq_bands_db=tone_delta)
        report["mastering"] = m_report
    else:
        report["mastering"] = {"enabled": False}

    _prog(1.0)
    return y.astype(np.float32), removed.astype(np.float32), report
