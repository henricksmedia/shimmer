#!/usr/bin/env python3
"""
shimmer.py — CLI entry point for the Shimmer de-artifact pipeline.

Orchestrates: presets -> params -> engine -> I/O.
This module owns argparse and user-facing output. No DSP math lives here.
"""

from __future__ import annotations

import _winfix  # noqa: F401  # must precede scipy/numpy import on Windows

import argparse
import json
import sys
import time

from dsp import band_from_center
from params import Params, MasterParams, LOUDNESS_TARGETS
from presets import get_preset, list_presets, PRESET_NAMES
from audio_io import process_file


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="shimmer",
        description=(
            "Remove AI shimmer artifacts from audio files.\n\n"
            "Targets narrowband flickering high-frequency artifacts (5.1-7.2 kHz default)\n"
            "produced by diffusion models, VAE/neural vocoders, and phase reconstruction errors.\n"
            "Ships with artifact-shape presets (cymbal_chatter, broadband_fizz, etc.)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  shimmer input.wav output.wav\n"
            "  shimmer input.wav output.wav --preset cymbal_chatter\n"
            "  shimmer input.wav output.wav --preset air_brittle --debug\n"
            "  shimmer input.wav output.wav --start-hz 4500 --end-hz 8000 --slope 0.8\n"
            "  shimmer --list-presets\n"
            "  # legacy version-named aliases (suno_v3 .. suno_v5.5) still work\n"
        ),
    )

    ap.add_argument("input", nargs="?",
                    help="Input audio file (WAV/MP3/FLAC/OGG/M4A)")
    ap.add_argument("output", nargs="?",
                    help="Output audio file (format inferred from extension)")

    # --- Preset ---
    preset_group = ap.add_argument_group("preset selection")
    preset_group.add_argument(
        "--preset", type=str, default=None,
        choices=PRESET_NAMES,
        help="Suno version preset (overridden by explicit flags)")
    preset_group.add_argument(
        "--list-presets", action="store_true",
        help="List available presets and exit")
    preset_group.add_argument(
        "--suggest", type=str, default=None, metavar="INPUT",
        help="Analyse INPUT and print the recommended preset, then exit")

    # --- Shimmer band ---
    band = ap.add_argument_group("shimmer band")
    band.add_argument("--start-hz", type=float, default=None)
    band.add_argument("--end-hz", type=float, default=None)
    band.add_argument("--center-hz", type=float, default=None,
                      help="Alternative: center frequency")
    band.add_argument("--width-cents", type=float, default=None,
                      help="Alternative: bandwidth in cents")
    band.add_argument("--edge-hz", type=float, default=None)

    # --- STFT ---
    stft = ap.add_argument_group("STFT")
    stft.add_argument("--n-fft", type=int, default=None)
    stft.add_argument("--hop", type=int, default=None)

    # --- Shimmer detection ---
    detect = ap.add_argument_group("shimmer detection")
    detect.add_argument("--freq-med-bins", type=int, default=None)
    detect.add_argument("--thr-db", type=float, default=None)
    detect.add_argument("--slope", type=float, default=None)
    detect.add_argument("--density-lo", type=float, default=None)
    detect.add_argument("--density-hi", type=float, default=None)

    # --- Gates ---
    gates = ap.add_argument_group("gating")
    gates.add_argument("--flat-start", type=float, default=None)
    gates.add_argument("--flat-end", type=float, default=None)
    gates.add_argument("--flux-thr-db", type=float, default=None)
    gates.add_argument("--flux-range-db", type=float, default=None)

    # --- Creative ---
    creative = ap.add_argument_group("creative controls")
    creative.add_argument("--noise-resynth", type=float, default=None,
                          help="0..1 random-phase blend (de-crystallize)")
    creative.add_argument("--mix", type=float, default=None,
                          help="0..1 wet/dry (1.0 = full processing)")

    # --- Denoise ---
    dn = ap.add_argument_group("spectral denoise")
    dn.add_argument("--denoise", type=float, default=None,
                    help="0..1 spectral noise floor reduction")
    dn.add_argument("--dn-start-hz", type=float, default=None)
    dn.add_argument("--dn-end-hz", type=float, default=None)
    dn.add_argument("--dn-edge-hz", type=float, default=None)
    dn.add_argument("--dn-floor-db", type=float, default=None)
    dn.add_argument("--dn-psd-smooth-ms", type=float, default=None)
    dn.add_argument("--dn-minwin-ms", type=float, default=None)
    dn.add_argument("--dn-up-db-per-s", type=float, default=None)
    dn.add_argument("--dn-attack-ms", type=float, default=None)
    dn.add_argument("--dn-release-ms", type=float, default=None)
    dn.add_argument("--dn-freq-smooth-bins", type=int, default=None)

    # --- De-harsh (dynamic 5-9 kHz tamer) ---
    dh = ap.add_argument_group("de-harsh (5-9 kHz fizz tamer)")
    dh.add_argument("--deharsh", type=float, default=None,
                    help="0..1 de-harsh strength (default 0 = off)")
    dh.add_argument("--dh-start-hz", type=float, default=None)
    dh.add_argument("--dh-end-hz", type=float, default=None)
    dh.add_argument("--dh-edge-hz", type=float, default=None)
    dh.add_argument("--dh-ref-start-hz", type=float, default=None)
    dh.add_argument("--dh-ref-end-hz", type=float, default=None)
    dh.add_argument("--dh-thr-db", type=float, default=None)
    dh.add_argument("--dh-slope", type=float, default=None)
    dh.add_argument("--dh-max-att-db", type=float, default=None)
    dh.add_argument("--dh-attack-ms", type=float, default=None)
    dh.add_argument("--dh-release-ms", type=float, default=None)

    # --- De-checkerboard (periodic deconv-grid suppressor) ---
    cb = ap.add_argument_group("de-checkerboard (deconv-grid suppressor)")
    cb.add_argument("--decheck", type=float, default=None,
                    help="0..1 de-checkerboard strength (default 0 = off)")
    cb.add_argument("--cb-start-hz", type=float, default=None)
    cb.add_argument("--cb-end-hz", type=float, default=None)
    cb.add_argument("--cb-min-spacing-hz", type=float, default=None)
    cb.add_argument("--cb-max-spacing-hz", type=float, default=None)
    cb.add_argument("--cb-peak-thr-db", type=float, default=None)
    cb.add_argument("--cb-max-att-db", type=float, default=None)
    cb.add_argument("--cb-persist-ms", type=float, default=None)

    # --- De-resonator ---
    deq = ap.add_argument_group("de-resonator")
    deq.add_argument("--deres", type=float, default=None,
                     help="0..1 de-resonator strength")
    deq.add_argument("--deq-start-hz", type=float, default=None)
    deq.add_argument("--deq-end-hz", type=float, default=None)
    deq.add_argument("--deq-edge-hz", type=float, default=None)
    deq.add_argument("--deq-freq-med-bins", type=int, default=None)
    deq.add_argument("--deq-thr-db", type=float, default=None)
    deq.add_argument("--deq-slope", type=float, default=None)
    deq.add_argument("--deq-max-att-db", type=float, default=None)
    deq.add_argument("--deq-density-lo", type=float, default=None)
    deq.add_argument("--deq-density-hi", type=float, default=None)
    deq.add_argument("--deq-persist-ms", type=float, default=None)
    deq.add_argument("--deq-persist-thr-db", type=float, default=None)
    deq.add_argument("--deq-freq-smooth-bins", type=int, default=None)
    deq.add_argument("--deq-tonal-boost-db", type=float, default=None)

    # --- Expander ---
    exp = ap.add_argument_group("downward expander")
    exp.add_argument("--expander", action="store_true", default=None)
    exp.add_argument("--exp-start-hz", type=float, default=None)
    exp.add_argument("--exp-end-hz", type=float, default=None)
    exp.add_argument("--exp-threshold-db", type=float, default=None)
    exp.add_argument("--exp-ratio", type=float, default=None)
    exp.add_argument("--exp-attack-ms", type=float, default=None)
    exp.add_argument("--exp-release-ms", type=float, default=None)

    # --- Post filters ---
    post = ap.add_argument_group("post-STFT filters")
    post.add_argument("--high-shelf-hz", type=float, default=None)
    post.add_argument("--high-shelf-db", type=float, default=None)
    post.add_argument("--subsonic-hz", type=float, default=None)
    post.add_argument("--presence-hz", type=float, default=None)
    post.add_argument("--presence-db", type=float, default=None)

    # --- Mastering ---
    mst = ap.add_argument_group("mastering")
    mst.add_argument("--master", action="store_true",
                     help="Enable true mastering (LUFS target + limiter + EQ)")
    mst.add_argument("--no-master", action="store_true",
                     help="Disable mastering when using defaults")
    mst.add_argument("--target", type=str, default=None,
                     choices=list(LOUDNESS_TARGETS.keys()),
                     help="Loudness target preset: streaming (-14), loud (-11), cd (-9)")
    mst.add_argument("--target-lufs", type=float, default=None,
                     help="Custom integrated LUFS target")
    mst.add_argument("--ceiling", type=float, default=None,
                     help="True-peak ceiling in dBTP (default -1.0)")
    mst.add_argument("--master-intensity", type=str, default=None,
                     choices=["low", "med", "high"],
                     help="Mastering EQ intensity")

    # --- Output ---
    out = ap.add_argument_group("output")
    out.add_argument("--no-pad", action="store_true")
    out.add_argument("--fade-ms", type=float, default=None)
    out.add_argument("--no-preserve-volume", action="store_true",
                     help="Don't match output peak to input peak")
    out.add_argument("--subtype", type=str, default="PCM_24",
                     help="SoundFile subtype: PCM_16, PCM_24, FLOAT")
    out.add_argument("--write-diff", type=str, default=None,
                     help="Write the removed signal to this file")

    # --- Misc ---
    misc = ap.add_argument_group("misc")
    misc.add_argument("--seed", type=int, default=None)
    misc.add_argument("--debug", action="store_true")

    return ap


def _resolve_params(args) -> Params:
    """Build Params from preset + CLI overrides."""
    if args.preset:
        p = get_preset(args.preset)
    else:
        p = Params()

    # Handle center/width -> start/end conversion
    if args.center_hz is not None and args.width_cents is not None:
        lo, hi = band_from_center(args.center_hz, args.width_cents)
        p.start_hz = lo
        p.end_hz = hi

    # Map CLI arg names (with hyphens) to Params field names (with underscores)
    _OVERRIDES = {
        "start_hz": "start_hz",
        "end_hz": "end_hz",
        "edge_hz": "edge_hz",
        "n_fft": "n_fft",
        "hop": "hop",
        "flat_start": "flat_start",
        "flat_end": "flat_end",
        "freq_med_bins": "freq_med_bins",
        "thr_db": "thr_db",
        "slope": "slope",
        "density_lo": "density_lo",
        "density_hi": "density_hi",
        "flux_thr_db": "flux_thr_db",
        "flux_range_db": "flux_range_db",
        "noise_resynth": "noise_resynth",
        "mix": "mix",
        "fade_ms": "fade_ms",
        "denoise": "denoise",
        "dn_start_hz": "dn_start_hz",
        "dn_end_hz": "dn_end_hz",
        "dn_edge_hz": "dn_edge_hz",
        "dn_floor_db": "dn_floor_db",
        "dn_psd_smooth_ms": "dn_psd_smooth_ms",
        "dn_minwin_ms": "dn_minwin_ms",
        "dn_up_db_per_s": "dn_up_db_per_s",
        "dn_attack_ms": "dn_attack_ms",
        "dn_release_ms": "dn_release_ms",
        "dn_freq_smooth_bins": "dn_freq_smooth_bins",
        "deres": "deres",
        "deq_start_hz": "deq_start_hz",
        "deq_end_hz": "deq_end_hz",
        "deq_edge_hz": "deq_edge_hz",
        "deq_freq_med_bins": "deq_freq_med_bins",
        "deq_thr_db": "deq_thr_db",
        "deq_slope": "deq_slope",
        "deq_max_att_db": "deq_max_att_db",
        "deq_density_lo": "deq_density_lo",
        "deq_density_hi": "deq_density_hi",
        "deq_persist_ms": "deq_persist_ms",
        "deq_persist_thr_db": "deq_persist_thr_db",
        "deq_freq_smooth_bins": "deq_freq_smooth_bins",
        "deq_tonal_boost_db": "deq_tonal_boost_db",
        "deharsh": "deharsh",
        "dh_start_hz": "dh_start_hz",
        "dh_end_hz": "dh_end_hz",
        "dh_edge_hz": "dh_edge_hz",
        "dh_ref_start_hz": "dh_ref_start_hz",
        "dh_ref_end_hz": "dh_ref_end_hz",
        "dh_thr_db": "dh_thr_db",
        "dh_slope": "dh_slope",
        "dh_max_att_db": "dh_max_att_db",
        "dh_attack_ms": "dh_attack_ms",
        "dh_release_ms": "dh_release_ms",
        "decheck": "decheck",
        "cb_start_hz": "cb_start_hz",
        "cb_end_hz": "cb_end_hz",
        "cb_min_spacing_hz": "cb_min_spacing_hz",
        "cb_max_spacing_hz": "cb_max_spacing_hz",
        "cb_peak_thr_db": "cb_peak_thr_db",
        "cb_max_att_db": "cb_max_att_db",
        "cb_persist_ms": "cb_persist_ms",
        "expander": "expander",
        "exp_start_hz": "exp_start_hz",
        "exp_end_hz": "exp_end_hz",
        "exp_threshold_db": "exp_threshold_db",
        "exp_ratio": "exp_ratio",
        "exp_attack_ms": "exp_attack_ms",
        "exp_release_ms": "exp_release_ms",
        "high_shelf_hz": "high_shelf_hz",
        "high_shelf_db": "high_shelf_db",
        "subsonic_hz": "subsonic_hz",
        "presence_hz": "presence_hz",
        "presence_db": "presence_db",
        "seed": "seed",
    }

    for arg_name, param_name in _OVERRIDES.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            setattr(p, param_name, val)

    if args.no_pad:
        p.pad = False
    if args.debug:
        p.debug = True

    return p


def _resolve_master_params(args) -> MasterParams | None:
    """Build MasterParams from CLI flags. None = mastering off."""
    if args.no_master:
        return None
    if not args.master and args.target is None and args.target_lufs is None:
        return None
    mp = MasterParams(enabled=True)
    if args.target:
        mp.target_lufs = LOUDNESS_TARGETS[args.target]
    if args.target_lufs is not None:
        mp.target_lufs = float(args.target_lufs)
    if args.ceiling is not None:
        mp.ceiling_dbtp = float(args.ceiling)
    if args.master_intensity:
        mp.intensity = args.master_intensity
    return mp


def _progress_bar(fraction: float):
    """Simple inline progress bar."""
    width = 40
    filled = int(width * fraction)
    bar = "█" * filled + "░" * (width - filled)
    pct = fraction * 100
    print(f"\r  [{bar}] {pct:5.1f}%", end="", flush=True)
    if fraction >= 1.0:
        print()


def main() -> int:
    ap = _build_parser()
    args = ap.parse_args()

    if args.list_presets:
        presets = list_presets()
        print("Available presets:\n")
        for name, desc in presets.items():
            lines = desc.split("\n")
            header = lines[0] if lines else name
            detail = " ".join(l.strip() for l in lines[1:] if l.strip())
            print(f"  {name:16s}  {header}")
            if detail:
                print(f"  {'':<16s}  {detail}")
            print()
        return 0

    if args.suggest:
        from probe import suggest_preset
        result = suggest_preset(args.suggest)
        print(f"Suggested preset: {result['preset']}\n")
        print("Shimmer-density scores per candidate band:")
        for name, score in sorted(
                result["scores"].items(), key=lambda kv: -kv[1]):
            print(f"  {name:14s} {score:.4f}")
        print(f"\nCheckerboard score: {result['checkerboard_score']:.4f}")
        print(f"Analyzed:           {result['metrics']['analyzed_seconds']:.1f} s "
              f"@ {result['metrics']['sample_rate']} Hz")
        return 0

    if not args.input or not args.output:
        ap.error("input and output are required (use --list-presets to see presets)")
        return 1

    params = _resolve_params(args)
    master_params = _resolve_master_params(args)

    preset_label = args.preset or "generic"
    print(f"Shimmer removal: {args.input}")
    print(f"  Preset:  {preset_label}")
    print(f"  Band:    {params.start_hz:.0f} – {params.end_hz:.0f} Hz")
    if master_params and master_params.enabled:
        print(f"  Master:  {master_params.target_lufs:.1f} LUFS, "
              f"ceiling {master_params.ceiling_dbtp:.1f} dBTP")

    if params.denoise > 0:
        print(f"  Denoise: {params.denoise:.0%}")
    if params.deres > 0:
        print(f"  De-res:  {params.deres:.0%}")
    if params.deharsh > 0:
        print(f"  De-harsh:{params.deharsh:.0%} ({params.dh_start_hz:.0f}-{params.dh_end_hz:.0f} Hz)")
    if params.decheck > 0:
        print(f"  De-check:{params.decheck:.0%} ({params.cb_start_hz:.0f}-{params.cb_end_hz:.0f} Hz)")
    if params.high_shelf_db != 0 and params.high_shelf_hz > 0:
        print(f"  HShelf:  {params.high_shelf_db:+.1f} dB @ {params.high_shelf_hz:.0f} Hz")
    if params.subsonic_hz > 0:
        print(f"  HP:      {params.subsonic_hz:.0f} Hz")
    if params.presence_db != 0 and params.presence_hz > 0:
        print(f"  Presence: {params.presence_db:+.1f} dB @ {params.presence_hz:.0f} Hz")

    print()

    t_start = time.time()

    result = process_file(
        input_path=args.input,
        output_path=args.output,
        params=params,
        write_diff=args.write_diff,
        do_preserve_volume=not args.no_preserve_volume,
        subtype=args.subtype,
        progress_callback=_progress_bar,
        master_params=master_params,
    )

    elapsed = time.time() - t_start

    print(f"\n  Duration:  {result['duration_s']:.1f}s @ {result['sr']} Hz, {result['channels']}ch")
    print(f"  Input:     peak {result['input']['peak_dbfs']:.1f} dBFS, rms {result['input']['rms_dbfs']:.1f} dBFS")
    print(f"  Output:    peak {result['output']['peak_dbfs']:.1f} dBFS, rms {result['output']['rms_dbfs']:.1f} dBFS")
    if result.get("mastering", {}).get("enabled"):
        m = result["mastering"]
        b, a = m.get("before", {}), m.get("after", {})
        print(f"  LUFS:      {b.get('lufs_i', '?'):.1f} -> {a.get('lufs_i', '?'):.1f} "
              f"(target {m.get('target_lufs', '?'):.1f})")
        print(f"  True peak: {b.get('true_peak_dbtp', '?'):.1f} -> {a.get('true_peak_dbtp', '?'):.1f} dBTP")
    print(f"  Processed in {elapsed:.1f}s")
    print(f"  Written:   {args.output}")

    if args.write_diff:
        print(f"  Diff:      {args.write_diff}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
