"""
presets.py — Suno version-specific processing profiles.

Each preset returns a Params instance tuned for the artifact signature
of a specific Suno model generation. Derived from empirical analysis:

  v3      — Static, predictable shimmer in a narrow 5-7 kHz band.
  v3.5    — Similar to v3 with slightly broader artifacts.
  v4      — Prominent non-stationary shimmer; needs mid-high denoise
             + gentle 8 kHz high-shelf attenuation.
  v4.5    — Much reduced shimmer; targets 3.5-4.5 kHz harshness and
             spectral mud with a surgical notch approach.
  v5      — "Metallic" flagship. 1 kHz boxy resonance + 5-9 kHz fizz +
             16 kHz digital-air roll-off.  Uses the new de-harsh stage.
  v5 Pro  — Surgical processing above 6 kHz only; preserves excellent
             mid-range. Includes sub-sonic cleanup at 25 Hz and a
             gentle 10 kHz presence restoration.
  v5.5    — v4-style shimmer return: rattling in cymbals, hiss, risers,
             reverb tails. Higher FFT resolution (4096) to separate
             shimmer from cymbal harmonics. Raised density ceiling,
             faster transient recovery, strong denoise + de-resonator,
             de-harsh, and de-checkerboard enabled.
  cymbal  — Specialist: constant, tonal 8-12 kHz cymbal "sheen" that
             never decays.  Leans on the de-resonator (not shimmer
             suppression) because the artifact is tonal, not noise-like.
  Generic — Conservative all-round settings.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, Callable

from params import Params


def generic() -> Params:
    """Conservative all-round preset. Safe for unknown sources."""
    return Params()


def suno_v3() -> Params:
    """Suno v3: static narrowband shimmer, predictable location."""
    return Params(
        start_hz=5100.0,
        end_hz=7200.0,
        edge_hz=150.0,
        freq_med_bins=9,
        thr_db=7.0,
        slope=0.65,
        density_lo=0.02,
        density_hi=0.12,
        noise_resynth=0.05,
    )


def suno_v35() -> Params:
    """Suno v3.5: slightly broader than v3, similar character."""
    return Params(
        start_hz=4800.0,
        end_hz=7500.0,
        edge_hz=180.0,
        freq_med_bins=9,
        thr_db=7.5,
        slope=0.6,
        density_lo=0.02,
        density_hi=0.14,
        noise_resynth=0.05,
    )


def suno_v4() -> Params:
    """
    Suno v4: prominent, repetitive non-stationary shimmer.

    Applies mid-high denoising and a gentle high-shelf attenuation
    from 8 kHz to tame the characteristic v4 artifacts.
    """
    return Params(
        start_hz=4500.0,
        end_hz=8000.0,
        edge_hz=250.0,
        freq_med_bins=11,
        thr_db=6.0,
        slope=0.7,
        density_lo=0.02,
        density_hi=0.18,
        noise_resynth=0.1,

        denoise=0.4,
        dn_start_hz=2000.0,
        dn_end_hz=12000.0,
        dn_floor_db=-15.0,

        high_shelf_hz=8000.0,
        high_shelf_db=-2.5,
    )


def suno_v45() -> Params:
    """
    Suno v4.5: reduced shimmer vs v4.

    Targets 3.5-4.5 kHz harshness and spectral mud with a surgical
    notch-filter approach. Very light denoising.
    """
    return Params(
        start_hz=3500.0,
        end_hz=4500.0,
        edge_hz=120.0,
        freq_med_bins=7,
        thr_db=9.0,
        slope=0.5,
        density_lo=0.03,
        density_hi=0.12,
        noise_resynth=0.0,

        denoise=0.15,
        dn_start_hz=3000.0,
        dn_end_hz=6000.0,
        dn_floor_db=-20.0,

        deres=0.3,
        deq_start_hz=3000.0,
        deq_end_hz=5000.0,
        deq_thr_db=5.0,
        deq_max_att_db=6.0,
    )


def suno_v5() -> Params:
    """
    Suno v5: the "metallic" flagship model.

    Three-pronged attack matching current community guidance:
      - Surgical de-resonator notch at ~1 kHz for boxy metallic resonance.
      - Shimmer suppression + de-harsh across 5-9 kHz for fizz/sibilance.
      - Gentle high-shelf cut above 16 kHz for "digital air".
    Uses 4096-point FFT for finer spectral resolution.
    """
    return Params(
        start_hz=5000.0,
        end_hz=9000.0,
        edge_hz=300.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=11,
        thr_db=6.5,
        slope=0.7,
        density_lo=0.02,
        density_hi=0.18,
        noise_resynth=0.08,

        denoise=0.35,
        dn_start_hz=2500.0,
        dn_end_hz=16000.0,
        dn_floor_db=-16.0,

        deres=0.3,
        deq_start_hz=800.0,
        deq_end_hz=1400.0,
        deq_thr_db=5.0,
        deq_max_att_db=6.0,

        deharsh=0.55,
        dh_start_hz=5000.0,
        dh_end_hz=9000.0,
        dh_thr_db=5.5,
        dh_slope=0.55,
        dh_max_att_db=6.0,

        high_shelf_hz=16000.0,
        high_shelf_db=-6.0,
        subsonic_hz=25.0,
    )


def suno_v5_pro() -> Params:
    """
    Suno v5 Pro Beta: surgical processing above 6 kHz only.

    Preserves the excellent mid-range. Includes sub-sonic cleanup
    at 25 Hz and a gentle 10 kHz presence restoration.
    """
    return Params(
        start_hz=6000.0,
        end_hz=12000.0,
        edge_hz=300.0,
        freq_med_bins=9,
        thr_db=8.0,
        slope=0.55,
        density_lo=0.02,
        density_hi=0.15,
        noise_resynth=0.0,

        denoise=0.1,
        dn_start_hz=6000.0,
        dn_end_hz=16000.0,
        dn_floor_db=-22.0,

        subsonic_hz=25.0,
        presence_hz=10000.0,
        presence_db=1.5,
    )


def suno_cymbal() -> Params:
    """
    Constant high cymbal shimmer.

    A sustained, tonal, high-frequency tone that rides above the music
    but is not gritty or rattly -- think of a hi-hat or ride cymbal that
    never decays, or a narrow "sheen" sitting around 8-12 kHz.

    Strategy differs from the other presets:
      - The main tool is the de-resonator (persistent-narrow-peak notch),
        not shimmer suppression.  Shimmer suppression relies on a spectral
        flatness gate that *skips* tonal content -- exactly the wrong
        behaviour for a tonal artifact.
      - Flatness gate is opened up so the shimmer stage still helps a bit
        on the surrounding wash.
      - Persistence window is long (~1 s) so the notch locks on only to
        truly sustained tones; real cymbal hits (which decay within a
        second) pass through.
      - `deq_tonal_boost_db` is reduced so the de-resonator attacks tonal
        frames instead of protecting them.
      - No de-harsh, no de-checkerboard -- those target different
        artifacts.
    """
    return Params(
        start_hz=7000.0,
        end_hz=14000.0,
        edge_hz=400.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=11,
        thr_db=7.0,
        slope=0.5,

        # Flatness gate opened way up: this artifact is *tonal*, not noise.
        flat_start=0.10,
        flat_end=0.50,

        density_lo=0.015,
        density_hi=0.15,
        noise_resynth=0.05,

        # Gentle denoise for the broadband wash around the tonal peak.
        denoise=0.25,
        dn_start_hz=6000.0,
        dn_end_hz=16000.0,
        dn_floor_db=-16.0,

        # Primary tool: aggressive de-resonator across the cymbal band.
        deres=0.7,
        deq_start_hz=7000.0,
        deq_end_hz=14000.0,
        deq_thr_db=4.0,
        deq_slope=0.8,
        deq_max_att_db=12.0,
        deq_persist_ms=1000.0,    # ~1 s: real cymbals decay faster
        deq_persist_thr_db=2.0,
        deq_tonal_boost_db=1.0,   # don't protect tonal; artifact IS tonal
        deq_density_hi=0.12,

        subsonic_hz=25.0,
    )


def suno_v55() -> Params:
    """
    Suno v5.5: v4-era shimmer returns — rattling in cymbals, hiss,
    risers, and reverb tails. Uses higher FFT resolution to separate
    shimmer peaks from cymbal harmonics. Raised density ceiling so
    broadband shimmer isn't mistaken for musical content. Faster
    transient recovery to process cymbal/riser tails. Strong denoise
    and de-resonator for persistent ringing and hiss.  This version
    adds de-harsh (sibilance) and de-checkerboard (deconv-grid) stages.
    """
    return Params(
        start_hz=3500.0,
        end_hz=14000.0,
        edge_hz=400.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=13,
        thr_db=5.0,
        slope=0.75,
        flat_start=0.20,
        flat_end=0.60,
        density_lo=0.02,
        density_hi=0.28,
        flux_thr_db=7.0,
        flux_range_db=6.0,
        noise_resynth=0.12,

        denoise=0.55,
        dn_start_hz=2500.0,
        dn_end_hz=16000.0,
        dn_floor_db=-13.0,
        dn_release_ms=70.0,

        deres=0.6,
        deq_start_hz=3000.0,
        deq_end_hz=14000.0,
        deq_thr_db=4.0,
        deq_max_att_db=10.0,
        deq_persist_ms=400.0,

        deharsh=0.5,
        dh_start_hz=5000.0,
        dh_end_hz=9000.0,
        dh_thr_db=5.5,
        dh_slope=0.5,
        dh_max_att_db=7.0,

        decheck=0.4,
        cb_start_hz=3500.0,
        cb_end_hz=14000.0,
        cb_peak_thr_db=4.0,
        cb_max_att_db=8.0,
        cb_persist_ms=400.0,

        expander=True,
        exp_start_hz=3000.0,
        exp_end_hz=14000.0,
        exp_threshold_db=-40.0,
        exp_ratio=2.8,
        exp_release_ms=100.0,

        high_shelf_hz=8500.0,
        high_shelf_db=-2.5,
        subsonic_hz=25.0,
        presence_hz=10500.0,
        presence_db=1.5,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PRESETS: Dict[str, Callable[[], Params]] = {
    "generic":    generic,
    "suno_v3":    suno_v3,
    "suno_v3.5":  suno_v35,
    "suno_v4":    suno_v4,
    "suno_v4.5":  suno_v45,
    "suno_v5":    suno_v5,
    "suno_v5_pro": suno_v5_pro,
    "suno_v5.5":  suno_v55,
    "suno_cymbal": suno_cymbal,
}

PRESET_NAMES = list(PRESETS.keys())


def get_preset(name: str) -> Params:
    """Look up a preset by name. Raises KeyError if unknown."""
    key = name.lower().replace(" ", "_").replace("-", "_")
    if key not in PRESETS:
        available = ", ".join(PRESET_NAMES)
        raise KeyError(f"Unknown preset '{name}'. Available: {available}")
    return PRESETS[key]()


def describe_preset(name: str) -> str:
    """Return the preset factory's docstring."""
    key = name.lower().replace(" ", "_").replace("-", "_")
    fn = PRESETS.get(key)
    if fn is None:
        return "Unknown preset."
    return (fn.__doc__ or "").strip()


def list_presets() -> Dict[str, str]:
    """Return {name: description} for all presets."""
    return {name: describe_preset(name) for name in PRESET_NAMES}
