"""
params.py — Single source of truth for all processing knobs.

Every tunable value in the pipeline lives here. The engine reads from this;
presets create instances of it; the CLI populates it from argparse.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Params:
    """All processing parameters. Defaults target typical Suno shimmer."""

    # ── Shimmer suppression band ──────────────────────────────────────────
    start_hz: float = 5100.0       # low edge of target band
    end_hz: float = 7200.0         # high edge of target band
    edge_hz: float = 200.0         # cosine taper width at band edges

    # ── STFT settings ─────────────────────────────────────────────────────
    n_fft: int = 2048
    hop: int = 512

    # ── Noise-likeness gate (spectral flatness window) ────────────────────
    flat_start: float = 0.25       # flatness below this = tonal, skip
    flat_end: float = 0.70         # flatness above this = full processing

    # ── Shimmer outlier detection ─────────────────────────────────────────
    freq_med_bins: int = 9         # median filter width (freq axis)
    thr_db: float = 8.0            # dB above local median to flag outlier
    slope: float = 0.6             # soft-knee attenuation slope

    # ── Broadband protection (density gate) ───────────────────────────────
    density_lo: float = 0.02       # below = narrow artifact
    density_hi: float = 0.15       # above = broadband musical event

    # ── Transient protection (energy flux) ────────────────────────────────
    flux_thr_db: float = 6.0       # flux above this starts protecting
    flux_range_db: float = 8.0     # flux range for full protection

    # ── Random-phase noise resynth (de-crystallize texture) ───────────────
    noise_resynth: float = 0.0     # 0..1, amount of phase randomization

    # ── Wet/dry mix ───────────────────────────────────────────────────────
    mix: float = 1.0               # 1.0 = full processing, 0.0 = bypass

    # ── Padding & fade ────────────────────────────────────────────────────
    pad: bool = True
    fade_ms: float = 5.0

    # ── Spectral denoise (Wiener-like, minimum-statistics noise PSD) ─────
    # dn_start_hz defaults to 1500 Hz: below that is musical body (kick,
    # bass, vocal fundamentals) that should never be touched by denoise.
    denoise: float = 0.0           # 0..1 strength
    dn_start_hz: float = 1500.0
    dn_end_hz: float = 16000.0
    dn_edge_hz: float = 200.0
    dn_floor_db: float = -18.0     # gain floor (prevents total silence)
    dn_psd_smooth_ms: float = 50.0
    dn_minwin_ms: float = 400.0    # noise PSD minimum-statistics window
    dn_up_db_per_s: float = 3.0    # allowed noise floor rise rate
    dn_attack_ms: float = 5.0      # gain reduction speed
    dn_release_ms: float = 120.0   # gain recovery speed
    dn_freq_smooth_bins: int = 3   # smoothing to reduce musical noise

    # ── De-resonator (dynamic notch EQ on persistent narrow peaks) ────────
    # deq_start_hz defaults to 300 Hz to keep the dynamic notch out of
    # kick/bass fundamentals.  Individual presets override this when they
    # specifically target a low-mid resonance (e.g. v5's 1 kHz band).
    deres: float = 0.0             # 0..1 strength
    deq_start_hz: float = 300.0
    deq_end_hz: float = 12000.0
    deq_edge_hz: float = 150.0
    deq_freq_med_bins: int = 31    # wider median for broader context
    deq_thr_db: float = 6.0
    deq_slope: float = 0.7
    deq_max_att_db: float = 8.0    # ceiling on notch depth
    deq_density_lo: float = 0.03
    deq_density_hi: float = 0.20
    deq_persist_ms: float = 600.0  # EMA for persistence tracking
    deq_persist_thr_db: float = 2.5
    deq_freq_smooth_bins: int = 5
    deq_tonal_boost_db: float = 6.0  # raise threshold in tonal frames

    # ── De-harsh / de-ess (dynamic tamer for v5 "metallic fizz") ──────────
    deharsh: float = 0.0           # 0..1 strength
    dh_start_hz: float = 5000.0
    dh_end_hz: float = 9000.0
    dh_edge_hz: float = 250.0
    dh_ref_start_hz: float = 1000.0  # mid-band reference for ratio
    dh_ref_end_hz: float = 4000.0
    dh_thr_db: float = 6.0         # band-vs-ref excess before acting
    dh_slope: float = 0.5          # dB attenuation per dB excess
    dh_max_att_db: float = 6.0
    dh_attack_ms: float = 5.0
    dh_release_ms: float = 120.0

    # ── De-checkerboard (periodic deconv-grid suppressor) ─────────────────
    decheck: float = 0.0           # 0..1 strength
    cb_start_hz: float = 3000.0
    cb_end_hz: float = 16000.0
    cb_min_spacing_hz: float = 80.0
    cb_max_spacing_hz: float = 600.0
    cb_peak_thr_db: float = 4.0    # dB above local median to count as peak
    cb_max_att_db: float = 8.0
    cb_persist_ms: float = 400.0

    # ── Downward expander (push quiet tails further down) ─────────────────
    expander: bool = False
    exp_start_hz: float = 3000.0
    exp_end_hz: float = 8000.0
    exp_threshold_db: float = -45.0
    exp_ratio: float = 2.0
    exp_attack_ms: float = 10.0
    exp_release_ms: float = 150.0

    # ── Post-STFT time-domain filters ─────────────────────────────────────
    high_shelf_hz: float = 0.0     # high-shelf cutoff (0 = disabled)
    high_shelf_db: float = 0.0     # high-shelf gain (negative = cut)
    subsonic_hz: float = 0.0       # highpass cutoff (0 = disabled)
    presence_hz: float = 0.0       # presence shelf cutoff (0 = disabled)
    presence_db: float = 0.0       # presence shelf gain (positive = boost)

    # ── Misc ──────────────────────────────────────────────────────────────
    seed: int = 0
    debug: bool = False
