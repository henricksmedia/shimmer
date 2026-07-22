"""
trim_silence.py — Clip silence from the start and end of audio files.

Uses Shimmer's audio_io for format support (WAV/FLAC/OGG/AIFF natively,
MP3/M4A via ffmpeg). Detection is a short windowed-RMS scan so low-level
noise floors don't fool it.

Usage:
    python trim_silence.py song.flac                 # -> song_trimmed.flac
    python trim_silence.py *.wav -o trimmed/         # batch into a folder
    python trim_silence.py song.mp3 --dry-run        # just report, no write
    python trim_silence.py song.wav --threshold -50  # stricter threshold
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

from .audio_io import load_audio, save_audio, AudioIOError
from .dsp import trim_silence as trim


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Clip silence from the start/end of audio files.")
    ap.add_argument("inputs", nargs="+", help="Audio file(s) or glob patterns")
    ap.add_argument("-o", "--output-dir", default=None,
                    help="Write results here with original names "
                         "(default: alongside input with _trimmed suffix)")
    ap.add_argument("--threshold", type=float, default=-60.0,
                    help="Silence threshold in dBFS (default: -60)")
    ap.add_argument("--head-pad", type=float, default=50.0,
                    help="Milliseconds of silence to keep before audio (default: 50)")
    ap.add_argument("--tail-pad", type=float, default=250.0,
                    help="Milliseconds of silence to keep after audio (default: 250)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would be cut without writing files")
    args = ap.parse_args()

    paths = []
    for pattern in args.inputs:
        matches = glob.glob(pattern)
        paths.extend(matches if matches else [pattern])

    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    failures = 0
    for path in paths:
        try:
            x, sr = load_audio(path)
        except (AudioIOError, OSError) as e:
            print(f"SKIP  {path}: {e}")
            failures += 1
            continue

        y, cut_head, cut_tail = trim(
            x, sr, args.threshold, args.head_pad, args.tail_pad)

        if cut_head == 0.0 and cut_tail == 0.0:
            print(f"OK    {path}: nothing to trim")
            continue

        base, ext = os.path.splitext(os.path.basename(path))
        if args.output_dir:
            out_path = os.path.join(args.output_dir, base + ext)
        else:
            out_path = os.path.join(
                os.path.dirname(path) or ".", f"{base}_trimmed{ext}")

        label = "WOULD" if args.dry_run else "TRIM "
        print(f"{label} {path}: -{cut_head:.2f}s head, -{cut_tail:.2f}s tail "
              f"({x.shape[0]/sr:.1f}s -> {y.shape[0]/sr:.1f}s)"
              + ("" if args.dry_run else f" -> {out_path}"))

        if not args.dry_run:
            try:
                save_audio(out_path, y, sr)
            except (AudioIOError, OSError) as e:
                print(f"FAIL  {out_path}: {e}")
                failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
