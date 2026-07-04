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
    # Floor on the density-gate weight (`w_narrow`). ShimmerStage and
    # DeResonatorStage compute `w_narrow_eff = max(w_narrow, density_floor)`
    # so density_floor=0 keeps current behavior, while density_floor=0.7
    # forces the stage to stay at least 70% active even on the densest
    # frames (essential for broadband Suno hash where dense IS the artifact).
    density_floor: float = 0.0

    # ── Transient protection (energy flux) ────────────────────────────────
    flux_thr_db: float = 6.0       # flux above this starts protecting
    flux_range_db: float = 8.0     # flux range for full protection
    # Steady-state mode: when True, Shimmer/DeHarsh/DeChecker/Denoise/
    # DeResonator stages SKIP the per-frame transient gate. The
    # `w_nontrans` factor is replaced with 1.0 in their depth equation.
    # Use this when the artifact is steady-state (Suno hash, sustained
    # cymbal sheen) and the transient gate is silently weakening
    # cleaning on every consonant / drum hit.
    steady_state_mode: bool = False

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
    deq_density_floor: float = 0.0   # mirrors density_floor (see above)
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

    # ── Narrow-tone killer (steady-state Suno "whistle" notcher) ──────────
    # Tracks the long-term per-bin magnitude vs a wide local-frequency
    # envelope; bins that sit persistently above the envelope (e.g. fixed
    # 16 kHz / 17.8 kHz / 4.25 kHz Suno digital tones that never decay)
    # get a deep, fixed notch. No per-frame density or transient gates —
    # tones are defined by their LONG-TERM excess so per-frame heuristics
    # would just defeat the detector. Strength scales the notch depth.
    tone_kill: float = 0.0          # 0..1 strength
    tk_start_hz: float = 3500.0
    tk_end_hz: float = 20000.0
    tk_long_ms: float = 2000.0      # long-term magnitude EMA time constant
    tk_freq_med_bins: int = 51      # local envelope window (~600 Hz @ n_fft=4096)
    tk_thr_db: float = 3.0          # excess above envelope before acting
    tk_slope: float = 5.0           # dB notch per dB excess past threshold
    tk_max_att_db: float = 20.0     # ceiling on notch depth
    tk_warmup_ms: float = 500.0     # ramp depth from 0->1 during warmup
    tk_freq_smooth_bins: int = 1    # 1 = pure narrow notch; >1 widens slightly

    # ── Flicker tamer (NEW) — sub-band AM compressor for Suno hash ────────
    # The "metallic flickering hiss" Suno residual is amplitude-modulated
    # narrowband noise in 5-8 kHz. Every other stage acts on the
    # instantaneous magnitude; this one explicitly compresses the AM
    # envelope inside the band, which is the perceptually defining
    # feature of the artifact. Splits [ft_start_hz, ft_end_hz] into
    # `ft_n_bands` narrow sub-bands, runs an independent fast/slow EMA
    # pair per sub-band, and applies per-sub-band gain reduction when
    # E_fast / E_slow exceeds threshold. Surgical: leaves steady spectral
    # content alone, kills only the rapid level swings that are the
    # "flicker." Crucially does NOT multiply depth by w_nontrans — flicker
    # IS the modulation; gating it off transients defeats the stage.
    flicker_tame: float = 0.0       # 0..1 strength
    ft_start_hz: float = 4500.0
    ft_end_hz: float = 12000.0      # extended into the 8-14 kHz secondary hash band
    ft_n_bands: int = 6             # number of independent sub-band compressors
    ft_edge_hz: float = 100.0       # taper between adjacent sub-bands
    ft_attack_ms: float = 3.0       # E_fast time constant
    # Slow EMA must span many modulation periods to be a stable
    # reference. At 10-50 Hz modulation a 30 ms release tracks the
    # modulation itself (so the ratio never opens up).  ~250 ms spans
    # 2-12 modulation periods and works as a true running mean.
    ft_release_ms: float = 250.0
    ft_thr_db: float = 1.5          # excess of E_fast over E_slow before acting
    ft_slope: float = 0.85          # dB att per dB excess past threshold
    ft_max_att_db: float = 18.0     # ceiling per sub-band

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

    # ── Iterations (re-run the whole pipeline N times) ────────────────────
    # Each pass starts from the previous pass's output. The second pass
    # benefits from the first pass's reduced noise floor — detectors
    # re-converge with cleaner background, long-EMA stages get more
    # samples to settle. Cheap, real, often the difference between
    # "almost gone" and "gone" on stubborn Suno hash.
    iterations: int = 1            # 1..3

    # ── Two-pass full-file analysis (pre_analyze) ─────────────────────────
    # Optional: do a cheap full-file scan first, build a per-bin
    # attenuation mask informed by long-term magnitude excess + AM depth,
    # then apply that mask as a multiplicative pre-filter in the main
    # STFT pass. Eliminates long-EMA warmup error and detection
    # misclassification on local musical content.
    pre_analyze: bool = False
    pa_start_hz: float = 4000.0
    pa_end_hz: float = 14000.0
    pa_n_fft: int = 4096
    pa_hop: int = 2048
    pa_max_seconds: float = 60.0   # only scan this many seconds (long files)
    pa_freq_med_bins: int = 51     # local envelope window for excess calc
    pa_thr_db: float = 3.0         # excess above envelope before acting
    pa_max_att_db: float = 18.0    # per-bin ceiling for the mask
    pa_am_weight: float = 1.0      # how much AM depth amplifies the mask

    # ── Diagnostic readout ────────────────────────────────────────────────
    # When True, process() computes before/after metrics on the 5-8 kHz
    # band (energy + AM depth) and a list of top surviving narrow peaks,
    # and stashes them on the engine's diagnostic_callback if any.
    diagnostic: bool = False

    # ── Misc ──────────────────────────────────────────────────────────────
    seed: int = 0
    debug: bool = False


# ---------------------------------------------------------------------------
# Preset strength scaler
# ---------------------------------------------------------------------------

# Whitelist of "amount-style" keys that scale linearly from a neutral
# baseline (Params() default) to the preset's value, optionally past
# 100% (extrapolation).  Each entry is (key, lo_clamp, hi_clamp).
#
# Structural fields (band edges, n_fft, hop, time constants, gates) are
# NOT in this list -- the preset author chose them for the artifact
# shape, not "amount of effect."  `mix` is also excluded so the existing
# dry/wet slider keeps separate semantics from "preset strength."
_STRENGTH_AMOUNT_KEYS = (
    # 0..1 amount-style strengths
    ("denoise",       0.0, 1.0),
    ("deres",         0.0, 1.0),
    ("deharsh",       0.0, 1.0),
    ("decheck",       0.0, 1.0),
    ("tone_kill",     0.0, 1.0),
    ("noise_resynth", 0.0, 1.0),
    ("flicker_tame",  0.0, 1.0),

    # dB ceilings — let strength scale them up to ~2x preset.
    ("dh_max_att_db",  0.0, 30.0),
    ("deq_max_att_db", 0.0, 30.0),
    ("tk_max_att_db",  0.0, 40.0),
    ("ft_max_att_db",  0.0, 36.0),
    ("cb_max_att_db",  0.0, 24.0),

    # Density floor — at higher strength, push dense-frame override
    # closer to fully active.
    ("density_floor",     0.0, 0.95),
    ("deq_density_floor", 0.0, 0.95),

    # High-shelf air cut: more cut at higher strength (negative dB).
    ("high_shelf_db", -12.0, 0.0),
)

# Denoise floor scales to a deeper minimum at higher strength
# (more attenuation allowed).  Treated specially because the neutral
# baseline is -18 dB but the "off" value is 0 dB.
_STRENGTH_DENOISE_FLOOR_LIMIT = -40.0


def apply_preset_strength(p: "Params", strength: float) -> None:
    """Scale a preset's amount-style fields by `strength`.

    `strength = 1.0` -> identity (preset unchanged).
    `strength = 0.0` -> all amount fields revert to neutral baseline
        (most amounts go to 0; ceilings collapse to 0).
    `strength > 1.0` -> linear extrapolation past the preset's value,
        clamped per-key to a hard safety limit so users cannot blow up
        the audio by cranking the slider.

    Whitelist is intentionally narrow: only "how much" knobs scale.
    Band edges, time constants, detection thresholds, and `mix` are
    untouched.  `iterations` scales as a rounded integer in [1, 3].
    """
    s = float(strength)
    neutral = Params()  # all defaults — neutral baseline

    for key, lo, hi in _STRENGTH_AMOUNT_KEYS:
        n = float(getattr(neutral, key))
        v = float(getattr(p, key))
        scaled = n + (v - n) * s
        if scaled < lo:
            scaled = lo
        elif scaled > hi:
            scaled = hi
        setattr(p, key, scaled)

    # Denoise floor (negative dB).  Neutral is -18, preset may be more
    # negative.  Lerp between 0 (no denoise) and the preset value, with
    # extrapolation clamped to the safety limit.
    n_floor = 0.0  # "no attenuation allowed" baseline
    v_floor = float(p.dn_floor_db)
    scaled_floor = n_floor + (v_floor - n_floor) * s
    if scaled_floor < _STRENGTH_DENOISE_FLOOR_LIMIT:
        scaled_floor = _STRENGTH_DENOISE_FLOOR_LIMIT
    elif scaled_floor > 0.0:
        scaled_floor = 0.0
    p.dn_floor_db = scaled_floor

    # Iterations: lerp between 1 (default) and preset value, clamp [1, 3].
    n_iter = 1
    v_iter = int(p.iterations)
    scaled_iter = round(n_iter + (v_iter - n_iter) * s)
    if scaled_iter < 1:
        scaled_iter = 1
    elif scaled_iter > 3:
        scaled_iter = 3
    p.iterations = scaled_iter
