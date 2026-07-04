"""
presets.py - Artifact-shape processing profiles.

Each preset is named for the artifact it targets, not the model version
that produced it. The auto-detect feature (see probe.py) listens to the
file and picks the artifact whose signature it hears; the preset then
runs the DSP combination known to fix that signature.

Catalog (visible in the UI):

  Generic            - safe defaults
  Cymbal Sheen       - constant tonal high tone that never decays
  Laser Whistle      - thin, intermittent narrow-band tonal chirp
  Brittle Air        - top end (>12 kHz) glassy while mids stay clean
  Sibilance Rattle   - harsh "sss"/"tss" bursts on vocals
  Cymbal Chatter     - repetitive "ta-ta-ta" on hi-hats / percussion
  Broadband Fizz     - constant fuzzy haze across the brilliance band
  Checkerboard Grid  - faint comb / ringing texture
  Reverb Flutter     - reverb tails grain instead of smoothing
  Vocal Glaze        - shimmery glaze coating vocal harmonics (2-8 kHz)
  Vocal Glaze + Top  - Vocal Glaze + Suno Hash combined in one pass (2-12 kHz)
  Echo Sheen         - signal-correlated shimmer/hiss shadowing content
  Presence Haze      - smooth noise-like haze in the 3-8 kHz presence band
  Phantom Cymbal     - washy metallic cymbal wash in the 4-10 kHz band
  Harsh Veil         - gritty texture across the upper-mids (4-12 kHz)
  Deep Scrub         - maximum-strength wide-band cleanup (3-18 kHz)

Legacy version-named keys (suno_v3 .. suno_v5.5, suno_cymbal) remain as
hidden aliases so existing CLI calls, saved settings, and external scripts
keep working. They do NOT appear in dropdowns. See PRESET_ALIASES below
for the mapping.

Most legacy presets target the brilliance band (8+ kHz). The newer
presence-band presets (Presence Haze, Phantom Cymbal, Harsh Veil) extend
coverage down to 3-4 kHz for artifacts that live in the vocal/drum
presence zone.
"""

from __future__ import annotations

from typing import Dict, Callable

from params import Params


# ---------------------------------------------------------------------------
# Preset factories
# ---------------------------------------------------------------------------

def generic() -> Params:
    """Conservative all-round preset. Safe for unknown sources.

    Includes a moderate narrow-tone killer at 3.5-20 kHz to chase the
    persistent fixed-frequency Suno whistles (e.g. 16 kHz, 17.8 kHz)
    that survive every other stage. Strength 0.4 keeps it safely
    inaudible on real music while still attenuating obvious tones by
    several dB.
    """
    return Params(tone_kill=0.4)


def cymbal_sheen() -> Params:
    """
    Constant cymbal-like tone that never fades.

    A sustained, tonal, high-frequency tone riding above the music --
    a hi-hat or ride that never decays, or a narrow "sheen" sitting
    around 8-12 kHz.

    Strategy:
      - Primary tool is the **narrow-tone killer**, which tracks
        per-bin long-term excess vs a wide spectral envelope and
        notches bins that sit persistently above their neighbours
        (e.g. fixed 16 kHz Suno whistle). The de-resonator is also
        kept on as a secondary defence, but its per-frame density
        gate fails on dense brilliance bands so the tone killer is
        what actually catches the steady tones.
      - Flatness gate is opened up so the shimmer stage still helps a
        bit on the surrounding wash.
      - No de-harsh, no de-checkerboard -- those target different
        artifacts.
    """
    return Params(
        start_hz=8000.0,
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

        denoise=0.25,
        dn_start_hz=8000.0,
        dn_end_hz=16000.0,
        dn_floor_db=-16.0,

        # Secondary: de-resonator across the cymbal band. Density-hi is
        # raised to 0.50 so it still fires on dense brilliance content
        # rather than treating every busy frame as a "musical event".
        deres=0.7,
        deq_start_hz=8000.0,
        deq_end_hz=14000.0,
        deq_thr_db=4.0,
        deq_slope=0.8,
        deq_max_att_db=12.0,
        deq_persist_ms=1000.0,
        deq_persist_thr_db=2.0,
        deq_tonal_boost_db=1.0,
        deq_density_hi=0.50,

        # Primary: narrow-tone killer. Strong (0.9) and widened to cover
        # the 16-18 kHz Suno whistle region that the de-resonator misses.
        tone_kill=0.9,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        subsonic_hz=25.0,
    )


def laser_whistle() -> Params:
    """
    Thin, intermittent narrow-band tonal chirp ("laser" digital noise).

    Lives in 9-15 kHz. Tonal but not always sustained -- a chirpy
    digital whistle that comes and goes. Strategy: the narrow-tone
    killer is the primary tool (its long-term EMA still locks on even
    when the tone is intermittent). De-resonator and noise resynth
    provide secondary cleanup of the surrounding wash.
    """
    return Params(
        start_hz=9000.0,
        end_hz=15000.0,
        edge_hz=300.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=9,

        flat_start=0.10,
        flat_end=0.50,

        thr_db=7.0,
        slope=0.6,
        density_lo=0.02,
        density_hi=0.10,
        noise_resynth=0.10,

        deres=0.30,
        deq_start_hz=9000.0,
        deq_end_hz=15000.0,
        deq_thr_db=4.5,
        deq_slope=0.7,
        deq_max_att_db=8.0,
        deq_persist_ms=300.0,
        deq_tonal_boost_db=2.0,
        deq_density_hi=0.50,

        # Primary: narrow-tone killer covering the full whistle range.
        tone_kill=0.85,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        subsonic_hz=25.0,
    )


def air_brittle() -> Params:
    """
    Brittle, glassy top end (>12 kHz) while mids stay clean.

    The artifact is concentrated above 12 kHz and the rest of the mix
    is fine. Surgical: shimmer suppression in 12-18 kHz only, gentle
    denoise in the same band, and a small high shelf to tame the
    glassy edge. No de-harsh, no de-checkerboard, no aggressive
    notches -- the goal is to leave everything below 12 kHz untouched.
    """
    return Params(
        start_hz=12000.0,
        end_hz=18000.0,
        edge_hz=400.0,
        freq_med_bins=9,
        thr_db=7.0,
        slope=0.55,
        density_lo=0.02,
        density_hi=0.18,
        noise_resynth=0.12,

        denoise=0.20,
        dn_start_hz=12000.0,
        dn_end_hz=20000.0,
        dn_floor_db=-20.0,

        # Tone killer focused on the brittle top end where Suno
        # whistles tend to live (15-18 kHz).
        tone_kill=0.6,
        tk_start_hz=10000.0,
        tk_end_hz=20000.0,

        high_shelf_hz=15000.0,
        high_shelf_db=-1.5,
        subsonic_hz=25.0,
    )


def sibilance_rattle() -> Params:
    """
    Harsh "sss" / "tss" bursts on vocals.

    Energy spikes in 6-10 kHz that ride on top of vocal frames. Less
    "shimmer in the air" and more "the singer's consonants are
    razor-edged." Strategy: de-harsh is the primary stage, with mid
    noise resynth to soften the rough texture. Band stays low (6-10
    kHz) because that's where sibilance lives, not in the brilliance
    band.
    """
    return Params(
        start_hz=6000.0,
        end_hz=10000.0,
        edge_hz=300.0,
        freq_med_bins=9,
        thr_db=6.5,
        slope=0.6,
        density_lo=0.02,
        density_hi=0.16,
        noise_resynth=0.15,

        deharsh=0.65,
        dh_start_hz=5500.0,
        dh_end_hz=10500.0,
        dh_thr_db=5.0,
        dh_slope=0.6,
        dh_max_att_db=7.0,

        # Mild tone killer above the main vocal-formant range. Real
        # vocal formants are wide (~250 Hz) and won't stand out above
        # a 600 Hz local envelope, so this is safe for vocals.
        tone_kill=0.4,
        tk_start_hz=6000.0,
        tk_end_hz=20000.0,

        subsonic_hz=25.0,
    )


def cymbal_chatter() -> Params:
    """
    Repetitive "ta-ta-ta" rattle on hi-hats and percussion.

    Time-periodic chatter in the brilliance band (8-16 kHz), often
    paired with a faint comb pattern. The full toolset applies:
    shimmer suppression, brilliance-band denoise, de-harsh for the
    sibilance edge, de-checkerboard for the comb, and strong
    random-phase resynth to address the ms-scale phase wobble that
    makes the texture sound "crystalline."
    """
    return Params(
        start_hz=8000.0,
        end_hz=16000.0,
        edge_hz=300.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=11,
        thr_db=6.0,
        slope=0.75,
        density_lo=0.02,
        density_hi=0.20,
        noise_resynth=0.22,

        denoise=0.40,
        dn_start_hz=8000.0,
        dn_end_hz=18000.0,
        dn_floor_db=-15.0,

        deharsh=0.40,
        dh_start_hz=8000.0,
        dh_end_hz=12000.0,
        dh_thr_db=5.5,
        dh_slope=0.55,
        dh_max_att_db=5.0,

        decheck=0.35,
        cb_start_hz=8000.0,
        cb_end_hz=16000.0,
        cb_peak_thr_db=4.0,
        cb_max_att_db=8.0,

        # Tone killer to chase whistles that often hide behind chatter.
        tone_kill=0.6,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        subsonic_hz=25.0,
    )


def broadband_fizz() -> Params:
    """
    Constant fuzzy haze across the brilliance band.

    Noise-like, broadband, persistent -- not periodic, not tonal, not
    comb-shaped. Just a layer of fizz over the top end. Strategy:
    strong shimmer suppression and denoise across 8-18 kHz with heavy
    noise resynth, and no notches (notches would dig holes in
    perfectly natural broadband content). A small high shelf trims
    whatever fizz survives the spectral stages.
    """
    return Params(
        start_hz=8000.0,
        end_hz=18000.0,
        edge_hz=400.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=11,
        thr_db=6.0,
        slope=0.7,
        density_lo=0.02,
        density_hi=0.25,
        noise_resynth=0.25,

        denoise=0.50,
        dn_start_hz=8000.0,
        dn_end_hz=18000.0,
        dn_floor_db=-14.0,

        # Once the broadband fizz is gone, persistent tones become
        # MORE audible -- so we kill them too.
        tone_kill=0.5,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        high_shelf_hz=14000.0,
        high_shelf_db=-2.0,
        subsonic_hz=25.0,
    )


def checkerboard_grid() -> Params:
    """
    Faint comb / ringing texture across the high band.

    The deconv-grid signature: a regularly-spaced ringing in the
    spectrum (80-600 Hz spacing) that adds a subtle metallic comb to
    the top end. Often hard to identify by ear in isolation but very
    obvious as soon as it's removed. Strategy: de-checkerboard is the
    primary stage, with shimmer suppression and de-harsh as support.
    """
    return Params(
        start_hz=8000.0,
        end_hz=16000.0,
        edge_hz=300.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=11,
        thr_db=6.5,
        slope=0.7,
        density_lo=0.02,
        density_hi=0.18,
        noise_resynth=0.18,

        denoise=0.30,
        dn_start_hz=8000.0,
        dn_end_hz=18000.0,
        dn_floor_db=-16.0,

        deharsh=0.35,
        dh_start_hz=8000.0,
        dh_end_hz=12000.0,
        dh_thr_db=5.5,
        dh_slope=0.55,
        dh_max_att_db=5.0,

        decheck=0.50,
        cb_start_hz=6000.0,
        cb_end_hz=16000.0,
        cb_peak_thr_db=3.5,
        cb_max_att_db=10.0,
        cb_persist_ms=400.0,

        # Tones often coexist with the comb pattern.
        tone_kill=0.5,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        subsonic_hz=25.0,
    )


def suno_hash() -> Params:
    """
    Suno diffusion residual: narrowband AM-modulated hiss in 5-12 kHz.

    Architecture: FlickerTamer-led, broadband-attackers gentle.

    The crucial insight is that **FlickerTamer is the only stage that
    can distinguish Suno hash from real cymbals / vocal air / hi-hats**:
    it specifically targets the 10-50 Hz amplitude modulation that
    defines the artifact, and leaves sustained broadband content alone.
    Every other stage (denoise / deharsh / deres) is broadband-blind
    and will happily eat real musical brilliance if cranked too hard.

    So this preset:
      1. Runs **FlickerTamer at full strength** across 4.5-12 kHz with
         6 sub-bands and a long (250 ms) slow-EMA reference, capped at
         18 dB per sub-band -- this does the actual surgical work.
      2. Runs **Denoise / DeHarsh / DeRes at modest levels** with
         tight ceilings, just enough to mop up the steady-state noise
         floor that survives AM compression. NOT enough to dull real
         music.
      3. Uses **steady_state_mode** + **density_floor=0.7** so the
         broadband stages stay active on vocal frames where the hash
         actually rides (otherwise w_nontrans / density gating would
         silently disable them).

    Iterations=1: a single pass with surgical FlickerTamer is enough
    on real material; iter=2 was compounding the broadband attenuation.
    Crank `preset_strength` past 1.0 if you have an unusually hashy
    track and want more aggressive cleanup.
    """
    return Params(
        start_hz=4500.0,
        end_hz=12000.0,
        edge_hz=400.0,
        n_fft=4096,
        hop=1024,

        steady_state_mode=True,
        density_floor=0.70,
        deq_density_floor=0.6,

        thr_db=6.0,
        slope=0.6,
        flat_start=0.20,
        flat_end=0.65,
        density_lo=0.02,
        density_hi=0.30,

        # Modest broadband cleanup: just the noise floor, not the music.
        denoise=0.35,
        dn_start_hz=4500.0,
        dn_end_hz=12000.0,
        dn_floor_db=-18.0,

        # Gentle de-harsh: tight ceiling so it can't broadband-duck
        # cymbal hits / bright vocal phrases.
        deharsh=0.45,
        dh_start_hz=5000.0,
        dh_end_hz=9000.0,
        dh_max_att_db=8.0,
        dh_thr_db=5.0,
        dh_slope=0.55,

        # Surgical de-resonator: notches resonant peaks only, not
        # broadband content. Tight ceiling.
        deres=0.4,
        deq_start_hz=4500.0,
        deq_end_hz=12000.0,
        deq_thr_db=4.5,
        deq_slope=0.7,
        deq_max_att_db=12.0,
        deq_persist_ms=800.0,
        deq_density_hi=0.45,

        # PRIMARY TOOL: AM compressor across the full hash range. Only
        # cuts when 10-50 Hz modulation is detected, so cymbals and
        # sustained brilliance pass through untouched.
        flicker_tame=1.0,
        ft_start_hz=4500.0,
        ft_end_hz=12000.0,
        ft_n_bands=6,
        ft_attack_ms=3.0,
        ft_release_ms=250.0,
        ft_thr_db=1.5,
        ft_slope=0.85,
        ft_max_att_db=18.0,

        tone_kill=0.4,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        noise_resynth=0.15,
        iterations=1,
        subsonic_hz=25.0,
    )


def presence_haze() -> Params:
    """
    Smooth, airy noise-like haze in the 3-8 kHz presence band.

    Appears when the music is playing (vocals, drums) and vanishes in
    silence -- like someone left a high-pass-filtered white noise layer
    underneath every musical event.

    Why existing presets miss it: Denoise's minimum-statistics tracker
    estimates the noise floor from quiet frames, where this artifact is
    absent. ShimmerStage looks for narrow peaks; this is broadband.

    Strategy: denoise-led with a short minimum-statistics window and
    fast upward drift so the noise floor estimate tracks the
    content-gated wash. steady_state_mode + density_floor keep all
    stages active during busy frames. A small presence shelf cut
    handles whatever spectral processing can't reach.
    """
    return Params(
        start_hz=3000.0,
        end_hz=8000.0,
        edge_hz=300.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=9,
        thr_db=6.0,
        slope=0.6,

        flat_start=0.15,
        flat_end=0.55,

        steady_state_mode=True,
        density_floor=0.60,
        density_lo=0.02,
        density_hi=0.30,

        denoise=0.55,
        dn_start_hz=3000.0,
        dn_end_hz=8000.0,
        dn_edge_hz=250.0,
        dn_floor_db=-16.0,
        dn_minwin_ms=200.0,
        dn_up_db_per_s=8.0,
        dn_attack_ms=4.0,
        dn_release_ms=80.0,

        noise_resynth=0.18,

        tone_kill=0.3,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        presence_hz=6000.0,
        presence_db=-1.5,
        subsonic_hz=25.0,
    )


def phantom_cymbal() -> Params:
    """
    Washy, metallic cymbal-sustain-like "shhhhh" in 4-10 kHz.

    Sounds like a ride cymbal bleeding into every section -- a wash
    with audible ring / shimmer under the hiss. Rides on vocals and
    drums, not present in silence.

    Why existing presets miss it: Sibilance Rattle targets bursts
    ("sss"/"tss"), not sustained wash. Cymbal Sheen starts at 8 kHz.
    The metallic character means there ARE peaks hiding inside the
    broadband wash, but the density gate backs off during busy frames
    where the wash is loudest.

    Strategy: DeResonator + DeHarsh led, targeting the metallic peaks
    that hide inside the broadband wash. Denoise and ShimmerStage
    provide broadband support. steady_state_mode + density_floor keep
    processing engaged during the busy frames where the wash is worst.
    """
    return Params(
        start_hz=4000.0,
        end_hz=10000.0,
        edge_hz=300.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=11,
        thr_db=6.0,
        slope=0.65,

        flat_start=0.15,
        flat_end=0.55,

        steady_state_mode=True,
        density_floor=0.50,
        deq_density_floor=0.50,
        density_lo=0.02,
        density_hi=0.25,

        deres=0.65,
        deq_start_hz=4000.0,
        deq_end_hz=10000.0,
        deq_edge_hz=200.0,
        deq_thr_db=4.0,
        deq_slope=0.75,
        deq_max_att_db=10.0,
        deq_persist_ms=700.0,
        deq_persist_thr_db=2.0,
        deq_tonal_boost_db=2.0,
        deq_density_hi=0.45,

        deharsh=0.55,
        dh_start_hz=4000.0,
        dh_end_hz=8000.0,
        dh_thr_db=4.5,
        dh_slope=0.55,
        dh_max_att_db=7.0,
        dh_release_ms=180.0,

        denoise=0.35,
        dn_start_hz=4000.0,
        dn_end_hz=10000.0,
        dn_floor_db=-16.0,
        dn_minwin_ms=250.0,
        dn_up_db_per_s=6.0,

        noise_resynth=0.15,

        tone_kill=0.4,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        subsonic_hz=25.0,
    )


def harsh_veil() -> Params:
    """
    Harsh, gritty texture riding on the upper-mids (4-12 kHz).

    Makes the mix sound like it's behind a layer of sandpaper. Not
    sibilance bursts, not a cymbal wash, just persistent grit spread
    across the presence and low-brilliance bands. Often accompanies
    vocal phrases and drum hits but stays through sustained passages.

    Why existing presets miss it: DeHarsh only fires when the
    band-vs-reference ratio spikes. If the grit is always present
    the ratio stays flat and never crosses threshold. Denoise fails
    for the same content-gating reason.

    Strategy: DeHarsh + Denoise led across 4-12 kHz with lowered
    thresholds. Wider band than Sibilance Rattle, less metallic than
    Phantom Cymbal. High-shelf cut at 10 kHz to tame the edge that
    survives spectral processing.
    """
    return Params(
        start_hz=4000.0,
        end_hz=12000.0,
        edge_hz=400.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=11,
        thr_db=5.5,
        slope=0.65,

        flat_start=0.18,
        flat_end=0.60,

        steady_state_mode=True,
        density_floor=0.50,
        deq_density_floor=0.40,
        density_lo=0.02,
        density_hi=0.25,

        deharsh=0.60,
        dh_start_hz=4000.0,
        dh_end_hz=12000.0,
        dh_edge_hz=350.0,
        dh_thr_db=3.0,
        dh_slope=0.55,
        dh_max_att_db=8.0,
        dh_release_ms=160.0,

        denoise=0.45,
        dn_start_hz=4000.0,
        dn_end_hz=12000.0,
        dn_floor_db=-16.0,
        dn_minwin_ms=250.0,
        dn_up_db_per_s=6.0,
        dn_attack_ms=4.0,
        dn_release_ms=90.0,

        deres=0.30,
        deq_start_hz=4000.0,
        deq_end_hz=12000.0,
        deq_thr_db=5.0,
        deq_max_att_db=6.0,
        deq_persist_ms=500.0,
        deq_density_hi=0.40,

        noise_resynth=0.12,

        tone_kill=0.4,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        high_shelf_hz=10000.0,
        high_shelf_db=-2.0,
        subsonic_hz=25.0,
    )


def deep_scrub() -> Params:
    """
    Maximum-strength wide-band cleanup across 3-18 kHz.

    "I've tried every preset and I still hear it." Trades some
    high-frequency fidelity for maximum artifact removal. Every
    processing stage is active at high strength with two iterations so
    the second pass catches what the first pass revealed. Use when
    subtlety isn't working and you need the artifact gone.

    Strategy: all stages active simultaneously. Two iterations, wide
    bands, high density floor, steady-state mode. Pre-analyze for
    full-file two-pass detection. High-shelf and presence-shelf cuts
    as a final safety net. Expect noticeable high-frequency dulling --
    that's the trade-off.
    """
    return Params(
        start_hz=3000.0,
        end_hz=18000.0,
        edge_hz=500.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=11,
        thr_db=5.5,
        slope=0.7,

        flat_start=0.15,
        flat_end=0.55,

        steady_state_mode=True,
        density_floor=0.70,
        deq_density_floor=0.60,
        density_lo=0.02,
        density_hi=0.30,

        denoise=0.60,
        dn_start_hz=3000.0,
        dn_end_hz=18000.0,
        dn_floor_db=-18.0,
        dn_minwin_ms=200.0,
        dn_up_db_per_s=8.0,
        dn_attack_ms=3.0,
        dn_release_ms=80.0,

        deres=0.55,
        deq_start_hz=3000.0,
        deq_end_hz=14000.0,
        deq_thr_db=4.0,
        deq_slope=0.75,
        deq_max_att_db=12.0,
        deq_persist_ms=600.0,
        deq_persist_thr_db=2.0,
        deq_density_hi=0.50,

        deharsh=0.60,
        dh_start_hz=4000.0,
        dh_end_hz=12000.0,
        dh_thr_db=3.5,
        dh_slope=0.6,
        dh_max_att_db=8.0,
        dh_release_ms=140.0,

        flicker_tame=0.70,
        ft_start_hz=4000.0,
        ft_end_hz=12000.0,
        ft_n_bands=6,
        ft_attack_ms=3.0,
        ft_release_ms=250.0,
        ft_thr_db=1.5,
        ft_slope=0.80,
        ft_max_att_db=16.0,

        decheck=0.40,
        cb_start_hz=4000.0,
        cb_end_hz=16000.0,
        cb_peak_thr_db=3.5,
        cb_max_att_db=10.0,

        tone_kill=0.7,
        tk_start_hz=3500.0,
        tk_end_hz=20000.0,

        noise_resynth=0.25,
        iterations=2,

        pre_analyze=True,
        pa_start_hz=3000.0,
        pa_end_hz=18000.0,

        high_shelf_hz=12000.0,
        high_shelf_db=-2.5,
        presence_hz=6000.0,
        presence_db=-1.5,
        subsonic_hz=25.0,
    )


def vocal_glaze() -> Params:
    """
    Shimmery glaze coating vocal harmonics in 2-8 kHz.

    A shiny, airy shimmer that sits directly on top of vocals — not
    after them, not in the gaps, but co-temporal with the voice
    itself. As if the AI model generates vocal overtones (formants
    F2-F5 in the 2-8 kHz range) with an unnatural, glassy shimmer
    quality. Drops the instant the vocal stops.

    Why existing presets miss it: the shimmer IS the vocal harmonics
    (just unnaturally bright), so it can't be separated by denoise
    (which targets energy independent of the signal) or by shimmer
    suppression (which looks for narrow peaks above a median — the
    vocal harmonics ARE the median). DeHarsh with a 1-4 kHz reference
    misses it because 1-4 kHz itself contains shimmer.

    Strategy: **DeHarsh anchored to vocal fundamentals** (300-1500 Hz)
    as the primary tool. This is the only preset that moves the
    DeHarsh reference band below 1 kHz, comparing the "clean" vocal
    fundamental (which the AI renders well) against the shimmer-prone
    2-8 kHz overtone range. When the overtones are disproportionately
    bright vs the fundamental, it attenuates — a vocal-aware shimmer
    compressor. Supported by gentle denoise in 2-8 kHz and moderate
    noise resynth to smooth what remains.

    Band starts at 2 kHz — lower than any other preset. This is
    necessary because vocal shimmer lives where vocal formants live,
    not in the brilliance band.
    """
    return Params(
        start_hz=2000.0,
        end_hz=8000.0,
        edge_hz=300.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=9,
        thr_db=6.0,
        slope=0.55,

        flat_start=0.10,
        flat_end=0.45,

        steady_state_mode=True,
        density_floor=0.55,
        density_lo=0.02,
        density_hi=0.25,

        # PRIMARY: DeHarsh anchored to vocal fundamentals.
        # Reference band 300-1500 Hz captures the clean vocal
        # fundamental; target band 2000-8000 Hz covers the
        # shimmer-prone overtone region. Low threshold (3 dB)
        # because the excess is subtle but persistent.
        deharsh=0.65,
        dh_start_hz=2000.0,
        dh_end_hz=8000.0,
        dh_edge_hz=200.0,
        dh_ref_start_hz=300.0,
        dh_ref_end_hz=1500.0,
        dh_thr_db=3.0,
        dh_slope=0.50,
        dh_max_att_db=7.0,
        dh_attack_ms=4.0,
        dh_release_ms=200.0,

        denoise=0.40,
        dn_start_hz=2000.0,
        dn_end_hz=8000.0,
        dn_edge_hz=200.0,
        dn_floor_db=-16.0,
        dn_psd_smooth_ms=80.0,
        dn_minwin_ms=250.0,
        dn_up_db_per_s=6.0,
        dn_attack_ms=4.0,
        dn_release_ms=100.0,
        dn_freq_smooth_bins=5,

        deres=0.25,
        deq_start_hz=2000.0,
        deq_end_hz=8000.0,
        deq_thr_db=5.0,
        deq_slope=0.6,
        deq_max_att_db=6.0,
        deq_persist_ms=600.0,
        deq_density_floor=0.35,
        deq_density_hi=0.40,

        noise_resynth=0.15,

        tone_kill=0.3,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        subsonic_hz=25.0,
    )


def vocal_glaze_plus() -> Params:
    """
    Vocal Glaze + Suno Hash in one pass (2-12 kHz).

    Targets the two most-complained-about Suno artifacts at the same
    time:

      1. Vocal Glaze (2-8 kHz) -- shimmery glaze sitting ON TOP of
         vocal harmonics. The shimmer IS the vocal overtones rendered
         too brightly, so it cannot be separated by broadband denoise
         or peak-based shimmer suppression.

      2. Suno Hash (5-12 kHz) -- the diffusion-model residual that
         every Suno track carries: narrowband AM-modulated hiss in
         the brilliance band that sounds like cymbal sizzle / wash
         which never quite goes away.

    Running Vocal Glaze alone misses the brilliance-band hash;
    running Suno Hash alone misses the vocal-anchored glaze. This
    preset wires both primary tools into a single pass:

      * **DeHarsh anchored to vocal fundamentals (300-1500 Hz)** as
        the vocal-glaze tool, comparing the clean vocal fundamental
        against the shimmer-prone 2-8 kHz overtone band. Same config
        as the Vocal Glaze preset.
      * **FlickerTamer at full strength across 4.5-12 kHz** with 6
        sub-bands as the Suno-hash tool. FlickerTamer is the only
        stage that distinguishes Suno hash from real cymbals / vocal
        air -- it specifically targets the 10-50 Hz amplitude
        modulation that defines the artifact and leaves sustained
        broadband content alone.

    Supporting stages (denoise, deres, noise resynth, tone kill) are
    intentionally kept MODEST and span the full 2-12 kHz band: just
    enough to mop up the steady-state floor that survives the two
    surgical primaries. Cranking them harder would dull real music
    because they are broadband-blind. Single iteration -- per the
    Suno Hash design note, compounding broadband attenuation hurts
    when FlickerTamer is doing the surgical work.

    Use the standalone Vocal Glaze if the brilliance band is already
    clean, or standalone Suno Hash if vocals sound natural and only
    the top-end sizzle bothers you. This preset is for tracks with
    both signatures present.
    """
    return Params(
        # Wide band spans Vocal Glaze (2-8) and Suno Hash (4.5-12).
        start_hz=2000.0,
        end_hz=12000.0,
        edge_hz=400.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=11,
        thr_db=6.0,
        slope=0.55,

        flat_start=0.15,
        flat_end=0.55,

        # Both primary presets use steady_state_mode + density_floor
        # so broadband stages stay active on dense vocal/drum frames
        # where the artifacts actually live.
        steady_state_mode=True,
        density_floor=0.65,
        deq_density_floor=0.55,
        density_lo=0.02,
        density_hi=0.28,

        # PRIMARY 1: vocal-anchored DeHarsh (Vocal Glaze tool).
        # Reference 300-1500 Hz captures the clean vocal fundamental;
        # target 2-8 kHz covers the shimmer-prone overtone region.
        deharsh=0.65,
        dh_start_hz=2000.0,
        dh_end_hz=8000.0,
        dh_edge_hz=200.0,
        dh_ref_start_hz=300.0,
        dh_ref_end_hz=1500.0,
        dh_thr_db=3.0,
        dh_slope=0.50,
        dh_max_att_db=7.0,
        dh_attack_ms=4.0,
        dh_release_ms=200.0,

        # PRIMARY 2: FlickerTamer (Suno Hash tool). Full strength,
        # 6 sub-bands across 4.5-12 kHz, capped at 18 dB per band.
        # This is the only surgical attack on the AM-modulated hash;
        # cymbals / vocal air pass through untouched.
        flicker_tame=1.0,
        ft_start_hz=4500.0,
        ft_end_hz=12000.0,
        ft_n_bands=6,
        ft_attack_ms=3.0,
        ft_release_ms=250.0,
        ft_thr_db=1.5,
        ft_slope=0.85,
        ft_max_att_db=18.0,

        # Modest broadband mop-up: just the noise floor that survives
        # the two primaries. Tight ceilings, NOT enough to dull music.
        denoise=0.35,
        dn_start_hz=2000.0,
        dn_end_hz=12000.0,
        dn_edge_hz=300.0,
        dn_floor_db=-17.0,
        dn_minwin_ms=250.0,
        dn_up_db_per_s=6.0,
        dn_attack_ms=4.0,
        dn_release_ms=90.0,
        dn_freq_smooth_bins=5,

        # Surgical de-resonator: notches resonant peaks only across
        # the wide band. Tight ceiling so it cannot broadband-duck
        # vocal phrases or cymbal hits.
        deres=0.35,
        deq_start_hz=2000.0,
        deq_end_hz=12000.0,
        deq_thr_db=4.5,
        deq_slope=0.7,
        deq_max_att_db=10.0,
        deq_persist_ms=700.0,
        deq_density_hi=0.45,

        noise_resynth=0.15,

        # Tone killer: catches sustained whistles (Suno's 16 kHz hash,
        # narrow tonal residues) above the FlickerTamer band.
        tone_kill=0.45,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        # Single pass per Suno Hash design: FlickerTamer is surgical,
        # iter=2 was found to compound broadband attenuation.
        iterations=1,

        # Gentle brilliance polish.
        high_shelf_hz=10000.0,
        high_shelf_db=-1.5,
        subsonic_hz=25.0,
    )


def echo_sheen() -> Params:
    """
    Signal-correlated shimmer/hiss that shadows musical content.

    A shimmery, hissy, shiny "shhhhh" that only exists when vocals or
    instruments are playing and vanishes when the music drops. Sounds
    like an echo or halo of shimmer around every note. Not constant
    (so it evades minimum-statistics denoise), not periodic (so it
    evades FlickerTamer), and not bursty (so it evades de-harsh /
    sibilance detection). It IS the music's own spectral shadow,
    amplitude-modulated by the signal envelope itself.

    Strategy: the only preset that enables the **downward expander**,
    which pushes down 3-10 kHz energy whenever it falls below a
    threshold — catching the shimmery tail that lingers at the edges
    of musical events. Combined with ultra-fast denoise tracking
    (150 ms minwin, 12 dB/s drift, 2 ms attack) so the noise floor
    estimate rises and falls with the content-gated artifact instead
    of only seeing silence. Two iterations: the first pass strips the
    loudest shimmer, the second catches the residual revealed
    underneath.
    """
    return Params(
        start_hz=3000.0,
        end_hz=10000.0,
        edge_hz=400.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=9,
        thr_db=5.5,
        slope=0.65,

        flat_start=0.12,
        flat_end=0.50,

        steady_state_mode=True,
        density_floor=0.60,
        density_lo=0.02,
        density_hi=0.30,

        # Ultra-fast denoise: tracks the content-gated artifact
        # in near-real-time instead of waiting for quiet frames.
        denoise=0.60,
        dn_start_hz=3000.0,
        dn_end_hz=10000.0,
        dn_edge_hz=300.0,
        dn_floor_db=-20.0,
        dn_minwin_ms=150.0,
        dn_up_db_per_s=12.0,
        dn_attack_ms=2.0,
        dn_release_ms=50.0,
        dn_freq_smooth_bins=5,

        # Downward expander: pushes down the shimmery residual in
        # the presence band whenever the music drops below threshold.
        # No other preset enables this.
        expander=True,
        exp_start_hz=3000.0,
        exp_end_hz=10000.0,
        exp_threshold_db=-40.0,
        exp_ratio=2.5,
        exp_attack_ms=8.0,
        exp_release_ms=120.0,

        deharsh=0.45,
        dh_start_hz=4000.0,
        dh_end_hz=10000.0,
        dh_thr_db=4.0,
        dh_slope=0.55,
        dh_max_att_db=7.0,
        dh_release_ms=140.0,

        deres=0.35,
        deq_start_hz=3000.0,
        deq_end_hz=10000.0,
        deq_thr_db=4.5,
        deq_slope=0.65,
        deq_max_att_db=8.0,
        deq_persist_ms=500.0,
        deq_density_floor=0.40,
        deq_density_hi=0.40,

        noise_resynth=0.20,

        tone_kill=0.4,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        iterations=2,

        high_shelf_hz=10000.0,
        high_shelf_db=-1.5,
        subsonic_hz=25.0,
    )


def reverb_flutter() -> Params:
    """
    Reverb tails grain instead of smoothing out.

    The artifact lives in the *decay* regions of the music: when the
    drums or vocal stop, the tail flutters with a granular wobble
    instead of dying away cleanly. Strategy: maximum random-phase
    noise resynth (this is exactly the de-crystallizer the one-pager
    calls for), strong brilliance-band denoise, and a moderate
    de-resonator. The downward expander is intentionally OFF -- it
    would pump the very tails we are trying to preserve.
    """
    return Params(
        start_hz=8000.0,
        end_hz=16000.0,
        edge_hz=400.0,
        n_fft=4096,
        hop=1024,
        freq_med_bins=13,
        thr_db=5.5,
        slope=0.75,
        flat_start=0.25,
        flat_end=0.65,
        density_lo=0.02,
        density_hi=0.22,
        flux_thr_db=7.0,
        flux_range_db=6.0,
        noise_resynth=0.30,

        denoise=0.45,
        dn_start_hz=8000.0,
        dn_end_hz=18000.0,
        dn_floor_db=-14.0,
        dn_release_ms=70.0,

        deres=0.35,
        deq_start_hz=8000.0,
        deq_end_hz=15000.0,
        deq_thr_db=4.5,
        deq_max_att_db=8.0,
        deq_persist_ms=400.0,
        deq_density_hi=0.40,

        # Strong tone killer: tails reveal whistles that the broadband
        # noise was masking, and they get audibly emphasised when the
        # rest of the tail decays cleanly.
        tone_kill=0.7,
        tk_start_hz=4000.0,
        tk_end_hz=20000.0,

        # Expander OFF: would pump the very tails this preset preserves.
        expander=False,

        high_shelf_hz=14000.0,
        high_shelf_db=-2.0,
        subsonic_hz=25.0,
        presence_hz=10500.0,
        presence_db=1.0,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Visible presets: shown in the UI dropdown and ranked by auto-detect.
PRESETS: Dict[str, Callable[[], Params]] = {
    "generic":           generic,
    "suno_hash":         suno_hash,
    "cymbal_sheen":      cymbal_sheen,
    "laser_whistle":     laser_whistle,
    "air_brittle":       air_brittle,
    "sibilance_rattle":  sibilance_rattle,
    "cymbal_chatter":    cymbal_chatter,
    "broadband_fizz":    broadband_fizz,
    "checkerboard_grid": checkerboard_grid,
    "reverb_flutter":    reverb_flutter,
    "vocal_glaze":       vocal_glaze,
    "vocal_glaze_plus":  vocal_glaze_plus,
    "echo_sheen":        echo_sheen,
    "presence_haze":     presence_haze,
    "phantom_cymbal":    phantom_cymbal,
    "harsh_veil":        harsh_veil,
    "deep_scrub":        deep_scrub,
}

VISIBLE_PRESETS = list(PRESETS.keys())

# Legacy version-named keys -> new artifact key.
# Kept callable so CLI / saved-settings / external scripts keep working.
# Hidden from the UI dropdown (filtered by `visible: false` in the API).
PRESET_ALIASES: Dict[str, str] = {
    "suno_v3":     "laser_whistle",
    "suno_v3.5":   "laser_whistle",
    "suno_v4":     "cymbal_chatter",
    "suno_v4.5":   "broadband_fizz",
    "suno_v5":     "checkerboard_grid",
    "suno_v5_pro": "air_brittle",
    "suno_v5.5":   "reverb_flutter",
    "suno_cymbal": "cymbal_sheen",
}

# Friendly UI labels for the visible presets. Aliases fall back to
# the label of their target via label_for().
PRESET_LABELS: Dict[str, str] = {
    "generic":           "Generic",
    "suno_hash":         "Suno Hash (5-12 kHz Flicker)",
    "cymbal_sheen":      "Cymbal Sheen",
    "laser_whistle":     "Laser Whistle",
    "air_brittle":       "Brittle Air",
    "sibilance_rattle":  "Sibilance Rattle",
    "cymbal_chatter":    "Cymbal Chatter",
    "broadband_fizz":    "Broadband Fizz",
    "checkerboard_grid": "Checkerboard Grid",
    "reverb_flutter":    "Reverb Flutter",
    "vocal_glaze":       "Vocal Glaze",
    "vocal_glaze_plus":  "Vocal Glaze + Top End",
    "echo_sheen":        "Echo Sheen",
    "presence_haze":     "Presence Haze",
    "phantom_cymbal":    "Phantom Cymbal",
    "harsh_veil":        "Harsh Veil",
    "deep_scrub":        "Deep Scrub",
}

# All resolvable preset keys (visible + aliases). The /api/presets endpoint
# emits one entry per name, with `visible: true` only for VISIBLE_PRESETS.
PRESET_NAMES = list(PRESETS.keys()) + list(PRESET_ALIASES.keys())


def _normalize(name: str) -> str:
    return name.lower().replace(" ", "_").replace("-", "_")


def _resolve(name: str) -> str:
    """Return the canonical visible-preset key, resolving any alias."""
    key = _normalize(name)
    return PRESET_ALIASES.get(key, key)


def get_preset(name: str) -> Params:
    """Look up a preset by name or alias. Raises KeyError if unknown."""
    key = _resolve(name)
    if key not in PRESETS:
        available = ", ".join(VISIBLE_PRESETS)
        raise KeyError(f"Unknown preset '{name}'. Available: {available}")
    return PRESETS[key]()


def label_for(name: str) -> str:
    """Return the friendly UI label for a preset key (resolves aliases)."""
    key = _normalize(name)
    if key in PRESET_LABELS:
        return PRESET_LABELS[key]
    if key in PRESET_ALIASES:
        return PRESET_LABELS.get(PRESET_ALIASES[key], name)
    return name


def is_visible(name: str) -> bool:
    """True if `name` is a visible (non-alias) preset key."""
    return _normalize(name) in PRESETS


def describe_preset(name: str) -> str:
    """Return the preset factory's docstring (resolves aliases)."""
    key = _resolve(name)
    fn = PRESETS.get(key)
    if fn is None:
        return "Unknown preset."
    return (fn.__doc__ or "").strip()


def list_presets() -> Dict[str, str]:
    """Return {name: description} for all VISIBLE presets."""
    return {name: describe_preset(name) for name in VISIBLE_PRESETS}
