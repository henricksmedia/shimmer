#!/usr/bin/env python3
"""shimmer: the command-line tool, a thin layer over shimmer.core.

    python -m shimmer input.wav output.wav [options]

One file goes through render() and export(), the same path as the app's
Master tab (docs/ARCHITECTURE.md §18). The 1.x commands keep working:

- Mastering stays off unless --master or --target asks for it, as in 1.x.
- --preset still works: the old preset turns on its "What do you hear?"
  card (shimmer.core.migrate).
- 1.x's cleaning controls (--denoise, --start-hz and the rest) went with the
  chain they tuned. They are still accepted and ignored, and the run says
  which, so an old script still runs.
"""
from __future__ import annotations

from . import _winfix  # noqa: F401  # must precede scipy/numpy import on Windows

import argparse
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import __version__, core
from .core.settings import LEGACY_ALIASES, LEGACY_PRESETS

# 1.x controls that tuned the retired cleaning chain, or output choices the
# new formats settle (each format has its own measured ceiling and rate).
# Accepted so old scripts run; ignored, with a note.
RETIRED_VALUE_FLAGS = (
    "--start-hz", "--end-hz", "--center-hz", "--width-cents", "--edge-hz",
    "--n-fft", "--hop",
    "--freq-med-bins", "--thr-db", "--slope", "--density-lo", "--density-hi",
    "--flat-start", "--flat-end", "--flux-thr-db", "--flux-range-db",
    "--noise-resynth", "--mix", "--declick",
    "--denoise", "--dn-start-hz", "--dn-end-hz", "--dn-edge-hz", "--dn-floor-db",
    "--dn-psd-smooth-ms", "--dn-minwin-ms", "--dn-up-db-per-s", "--dn-attack-ms",
    "--dn-release-ms", "--dn-freq-smooth-bins",
    "--deharsh", "--dh-start-hz", "--dh-end-hz", "--dh-edge-hz", "--dh-ref-start-hz",
    "--dh-ref-end-hz", "--dh-thr-db", "--dh-slope", "--dh-max-att-db", "--dh-attack-ms",
    "--dh-release-ms",
    "--decheck", "--cb-start-hz", "--cb-end-hz", "--cb-min-spacing-hz", "--cb-max-spacing-hz",
    "--cb-peak-thr-db", "--cb-max-att-db", "--cb-persist-ms",
    "--deres", "--deq-start-hz", "--deq-end-hz", "--deq-edge-hz", "--deq-freq-med-bins",
    "--deq-thr-db", "--deq-slope", "--deq-max-att-db", "--deq-density-lo", "--deq-density-hi",
    "--deq-persist-ms", "--deq-persist-thr-db", "--deq-freq-smooth-bins", "--deq-tonal-boost-db",
    "--exp-start-hz", "--exp-end-hz", "--exp-threshold-db", "--exp-ratio", "--exp-attack-ms",
    "--exp-release-ms",
    "--high-shelf-hz", "--high-shelf-db", "--subsonic-hz", "--presence-hz", "--presence-db",
    "--fade-ms", "--seed", "--target-lufs", "--ceiling", "--subtype", "--sample-rate",
)
RETIRED_SWITCHES = ("--expander", "--no-pad", "--debug", "--legacy-engine")


def _dest(flag: str) -> str:
    return "retired_" + flag.lstrip("-").replace("-", "_")


def _build_parser() -> argparse.ArgumentParser:
    targets = ", ".join(f"{t.key} ({t.lufs:g} LUFS)" for t in core.catalog.LOUDNESS_TARGETS)
    ap = argparse.ArgumentParser(
        prog="shimmer",
        description=(
            "Clean and master one audio file with the Shimmer engine: the same\n"
            "render and export as the app's Master tab."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python -m shimmer input.wav output.wav\n"
            "  python -m shimmer input.wav output.wav --target cd\n"
            "  python -m shimmer input.wav output.wav --fix tones=0.5 --no-auto\n"
            "  python -m shimmer input.wav release.wav --master --release\n"
            "  python -m shimmer --suggest input.mp3\n"
            "  python -m shimmer --list\n"
        ),
    )
    ap.add_argument("input", nargs="?", help="Input audio file (WAV/MP3/FLAC/OGG/M4A)")
    ap.add_argument("output", nargs="?",
                    help="Output file; the format follows its extension "
                         "(.wav .flac .mp3 .ogg .m4a)")

    fix = ap.add_argument_group("fixes (the \"What do you hear?\" cards)")
    fix.add_argument("--fix", action="append", default=[], metavar="CARD[=AMOUNT]",
                     help="Turn on a card, at an amount from 0 to 1 (see --list). "
                          "Repeat for more than one")
    fix.add_argument("--no-auto", action="store_true",
                     help="Only the cards you name; do not also fix what the "
                          "analysis finds (Fixed tones today)")
    fix.add_argument("--no-static-repair", action="store_true",
                     help="No Fixed tones at all, found or named (1.x's name)")
    fix.add_argument("--preset", type=str, default=None,
                     help="A 1.x preset name: turns on the card it became")
    fix.add_argument("--list", "--list-presets", dest="list", action="store_true",
                     help="List the cards, loudness targets and formats, then exit")
    fix.add_argument("--suggest", type=str, default=None, metavar="INPUT",
                     help="Analyze INPUT and print what it finds, then exit")

    mst = ap.add_argument_group("mastering")
    mst.add_argument("--master", action="store_true",
                     help="Master to the default loudness target "
                          f"({core.catalog.loudness_target(core.catalog.DEFAULT_LOUDNESS).label})")
    mst.add_argument("--no-master", action="store_true", help="No mastering")
    mst.add_argument("--target", type=str, default=None,
                     choices=[t.key for t in core.catalog.LOUDNESS_TARGETS],
                     help=f"Master to this loudness target: {targets}")
    mst.add_argument("--intensity", "--master-intensity", dest="intensity", type=str,
                     default=None, choices=list(core.catalog.TONE_INTENSITIES),
                     help="How much of the tone correction to make")
    mst.add_argument("--tilt", "--master-tilt", dest="tilt", type=str, default=None,
                     choices=list(core.catalog.TONE_TILTS), help="Warm to bright")
    mst.add_argument("--reference", type=str, default=None, metavar="FILE",
                     help="Move the tone toward this reference track instead of "
                          "the built-in target (mastering only)")
    mst.add_argument("--match-amount", type=float, default=None, metavar="0-1",
                     help=f"How much of the reference's difference to take "
                          f"(default {core.catalog.MATCH_AMOUNT:g}; at most ±3 dB either way)")

    out = ap.add_argument_group("output")
    out.add_argument("--release", action="store_true",
                     help="Release copy: WAV 16-bit at 44.1 kHz with dither")
    out.add_argument("--trim-silence", action="store_true",
                     help="Cut silence from the start and end")
    out.add_argument("--no-preserve-volume", action="store_true",
                     help="With mastering off, do not put the result back at "
                          "the input's level")
    out.add_argument("--write-diff", type=str, default=None, metavar="FILE",
                     help="Also write what the fixes took out to FILE")

    for flag in RETIRED_VALUE_FLAGS:
        ap.add_argument(flag, dest=_dest(flag), default=None, help=argparse.SUPPRESS)
    for flag in RETIRED_SWITCHES:
        ap.add_argument(flag, dest=_dest(flag), action="store_true", default=None,
                        help=argparse.SUPPRESS)
    return ap


def retired_flags_given(args: argparse.Namespace) -> List[str]:
    return [f for f in RETIRED_VALUE_FLAGS + RETIRED_SWITCHES
            if getattr(args, _dest(f), None) is not None]


def output_format(path: str, release: bool) -> core.catalog.Format:
    """The format an output file's extension names."""
    ext = Path(path).suffix.lower()
    if release:
        if ext != ".wav":
            raise ValueError("--release writes WAV 16-bit 44.1 kHz: name the output .wav")
        return core.catalog.output_format("wav16")
    for f in core.catalog.FORMATS:
        if f.ext == ext and f.key != "wav16":
            return f
    raise ValueError(f"unsupported output extension {ext or '(none)'}: "
                     "use .wav, .flac, .mp3, .ogg or .m4a")


def _fixes(entries: List[str]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for e in entries:
        key, _, amount = e.partition("=")
        key = key.strip().lower()
        if key not in core.catalog.CARD_KEYS:
            raise ValueError(f"unknown card {key!r}; see --list")
        try:
            out[key] = float(amount) if amount else core.catalog.card(key).default_amount
        except ValueError:
            raise ValueError(f"--fix {e}: the amount must be a number from 0 to 1")
    return out


def settings_from_args(args: argparse.Namespace) -> core.Settings:
    """The Settings a command line asks for."""
    preset = (args.preset or "").strip().lower()
    if preset and LEGACY_ALIASES.get(preset, preset) not in LEGACY_PRESETS:
        raise ValueError(f"unknown preset {args.preset!r}; see --list")
    fmt = output_format(args.output, args.release)
    mastering = (args.master or args.target is not None) and not args.no_master
    master = {"enabled": mastering}
    if args.target:
        master["target"] = args.target
    for key in ("intensity", "tilt"):
        if getattr(args, key):
            master[key] = getattr(args, key)
    s = core.migrate({"preset": preset or None, "mastering": master, "output_format": fmt.key,
                      "trim_silence": bool(args.trim_silence),
                      "preserve_volume": not args.no_preserve_volume})
    fixes = dict(s.fixes)
    fixes.update(_fixes(args.fix))
    auto = not (args.no_auto or args.no_static_repair)
    if args.no_static_repair:
        fixes.pop("tones", None)
    changes = {"fixes": fixes, "auto": auto}
    # Lack of air and Loudness are fixed by mastering (the tone and loudness
    # targets): naming one turns mastering on, unless --no-master says no.
    by_mastering = [k for k in fixes
                    if core.catalog.card(k).tool in ("tone_target", "loudness_target")]
    if by_mastering and not args.no_master:
        changes["mastering"] = True
    if args.match_amount is not None:
        changes["match_amount"] = args.match_amount
    return s.replace(**changes)


def _print_list() -> None:
    cat = core.catalog
    print('Cards ("What do you hear?"), for --fix CARD[=AMOUNT]:\n')
    for c in cat.CARDS:
        state = ("ready" if c.tool in cat.TOOLS_READY
                 else "no fix yet" if c.tool is None else "not built yet")
        print(f"  {c.key:12s} {c.label:22s} {state}")
    print("\nLoudness targets, for --target:\n")
    for t in cat.LOUDNESS_TARGETS:
        note = "  (the default with --master)" if t.key == cat.DEFAULT_LOUDNESS else ""
        print(f"  {t.key:12s} {t.label:22s} {t.lufs:g} LUFS{note}")
    print("\nFormats, from the output's extension (--release for the 16-bit copy):\n")
    for f in cat.FORMATS:
        print(f"  {f.ext:6s} {f.label:22s} true peak at most {f.ceiling_dbtp:g} dBTP")
    print("\n1.x presets, for --preset, turn on a card:\n")
    for name, card in LEGACY_PRESETS.items():
        print(f"  {name:20s} -> {card or 'none'}")


def _print_suggest(path: str) -> int:
    src = core.Source.load(path)
    found = core.findings(src)
    labels = {c.key: c.label for c in core.catalog.CARDS}
    print(f"Analyzed: {path}\n")
    if not found:
        print("  Nothing measurable to fix. Listen, and turn on a card for what you hear.")
    for f in found:
        print(f"  {labels.get(f.card, f.card)}: {f.detail}")
    return 0


def _mastering_lines(rendered: core.Rendered, source: core.Source, exp: Dict) -> List[str]:
    m = rendered.report.get("mastering", {})
    if not m.get("enabled"):
        return []
    before = core.meters.loudness(source.at_rate(rendered.sr), rendered.sr)
    target = "a reference track" if m.get("tone_target") == "reference" else "the built-in target"
    return [f"  Loudness:  {before:.1f} -> {exp['lufs']:.1f} LUFS (target {m['target_lufs']:g})",
            f"  True peak: {exp['true_peak_dbtp']:.1f} dBTP (ceiling {m['ceiling_dbtp']:g})",
            f"  Tone:      toward {target}"]


def main(argv: Optional[List[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        # The Windows console cannot print every character a report uses.
        sys.stdout.reconfigure(errors="replace")
    ap = _build_parser()
    args = ap.parse_args(argv)

    if args.list:
        _print_list()
        return 0
    try:
        if args.suggest:
            return _print_suggest(args.suggest)
        if not args.input or not args.output:
            ap.error("input and output are required (use --list to see the cards)")
        s = settings_from_args(args)
    except ValueError as e:
        ap.error(str(e))
    except core.AudioIOError as e:
        print(f"shimmer: {e}", file=sys.stderr)
        return 1

    retired = retired_flags_given(args)
    print(f"Shimmer {__version__}: {args.input}")
    if retired:
        print(f"  Ignored (1.x controls, gone in 2.0): {', '.join(retired)}")
    on = [f"{k} {v:g}" for k, v in s.fixes.items()]
    print(f"  Fixes:     {', '.join(on) if on else 'none named'}"
          + ("; plus what the analysis finds" if s.auto else ""))
    if s.mastering:
        t = core.catalog.loudness_target(s.loudness_target)
        print(f"  Master:    {t.label}, {t.lufs:g} LUFS")
    print()

    t0 = time.time()
    try:
        src = core.Source.load(args.input)
        ref = core.Source.load(args.reference) if args.reference else None
    except core.AudioIOError as e:
        print(f"shimmer: {e}", file=sys.stderr)
        return 1
    prog = core.Progress(on_stage=lambda key, label, detail:
                         print(f"  {label}" + (f": {detail}" if detail else "")))
    rendered = core.render(src, s, progress=prog, with_removed=bool(args.write_diff),
                           reference=ref)
    y, sr = rendered.audio, rendered.sr
    trimmed = ""
    if s.trim_silence:
        y, head, tail = core.trim_silence(y, sr)
        trimmed = f"  Trimmed:   {head:.2f} s at the start, {tail:.2f} s at the end"
    print(f"  Writing the file: {core.catalog.output_format(s.format).label}")
    exp = core.export(core.Rendered(y, sr, rendered.report, s, src.path), args.output,
                      source_path=args.input)
    if args.write_diff:
        diff_fmt = output_format(args.write_diff, release=False)
        core.export(core.Rendered(rendered.removed, sr, {}, s.replace(format=diff_fmt.key), src.path),
                    args.write_diff, source_path=args.input)

    print()
    fixes = rendered.report.get("fixes", {})
    tones = fixes.get("tones")
    if isinstance(tones, dict):
        print(f"  Fixed tones: {tones['notches']} notched, deepest {tones['deepest_db']:.0f} dB")
    waiting = [k for k, v in fixes.items() if v == "not built yet"]
    if waiting:
        print(f"  Not built yet, so not applied: {', '.join(waiting)}")
    for line in _mastering_lines(rendered, src, exp):
        print(line)
    if trimmed:
        print(trimmed)
    m = rendered.report.get("mastering", {})
    if m.get("enabled"):
        fmt = core.catalog.output_format(s.format)
        rel = core.release_check(
            y, sr, x_in=src.at_rate(sr),
            mastering={"enabled": True, "target_lufs": m["target_lufs"],
                       "ceiling_dbtp": m["ceiling_dbtp"],
                       "after": {"lufs_i": exp["lufs"], "true_peak_dbtp": exp["true_peak_dbtp"]}},
            export={"format": fmt.ext.lstrip("."), "bit_depth": fmt.bits},
            correlation=core.stereo_correlation(y), duration_s=float(y.shape[0] / sr))
        flags = [c["label"] for c in rel["checks"] if c["status"] in ("warn", "fail")]
        verdict = {"pass": "ready to upload", "warn": "things to look at",
                   "fail": "not ready"}[rel["status"]]
        print(f"  Release check: {verdict}" + (f" ({', '.join(flags)})" if flags else ""))
    print(f"  Written:   {args.output} ({time.time() - t0:.1f} s)")
    if args.write_diff:
        print(f"  Removed:   {args.write_diff}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
