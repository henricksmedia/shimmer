"""make_promo.py — the promo assets for one song, in one command.

    python scripts/make_promo.py --song "C:/music/song.wav"

It runs three steps, in order (docs/PROMO-ASSETS.md):

  screens  scripts/promo/capture.mjs, twice: every shot, then the cards
           close-up in a taller window. Needs Shimmer running.
  audio    scripts/promo/audio.py: before and after clips at matched
           loudness, and the Removed track turned up.
  videos   scripts/promo/videos.py: three vertical clips from the two above.

Everything lands in the --out folder (default promo-assets, which git
ignores). The audio and videos hold your music, so keep them out of the
repo.

Options:
  --song PATH      the song to feature (required)
  --out FOLDER     where to write (default: promo-assets)
  --port PORT      the port Shimmer is on (default: 7860)
  --steps LIST     which steps to run (default: screens,audio,videos)
  --browser PATH   Edge or Chrome, if it is somewhere unusual
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS = ("screens", "audio", "videos")


def run(cmd):
    print("\n$", " ".join(str(c) for c in cmd), flush=True)
    if subprocess.run(cmd, cwd=ROOT).returncode != 0:
        raise SystemExit(f"step failed: {' '.join(str(c) for c in cmd[:2])}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--song", required=True)
    p.add_argument("--out", default="promo-assets")
    p.add_argument("--port", default="7860")
    p.add_argument("--steps", default=",".join(STEPS))
    p.add_argument("--browser")
    args = p.parse_args(argv)

    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        raise SystemExit(f"unknown step(s): {', '.join(unknown)}; pick from {', '.join(STEPS)}")
    if not os.path.isfile(args.song):
        raise SystemExit(f"no such song: {args.song}")
    if shutil.which("ffmpeg") is None and ({"audio", "videos"} & set(steps)):
        raise SystemExit("ffmpeg is not on your PATH, and the audio and videos need it")
    if "screens" in steps and shutil.which("node") is None:
        raise SystemExit("node is not on your PATH, and the screenshots need it")

    if "screens" in steps:
        base = ["node", os.path.join("scripts", "promo", "capture.mjs"),
                "--song", args.song, "--out", args.out, "--port", args.port]
        if args.browser:
            base += ["--browser", args.browser]
        print(f"Shimmer must be running on port {args.port}.")
        run(base)
        run(base + ["--mode", "cards"])
    if "audio" in steps:
        run([sys.executable, os.path.join("scripts", "promo", "audio.py"),
             "--song", args.song, "--out", args.out])
    if "videos" in steps:
        run([sys.executable, os.path.join("scripts", "promo", "videos.py"), "--out", args.out])

    out = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    print("\nwritten to", out)
    for folder in ("screens", "audio", "video"):
        here = os.path.join(out, folder)
        if os.path.isdir(here):
            files = [f for f in os.listdir(here) if os.path.isfile(os.path.join(here, f))]
            print(f"  {folder}: {len(files)} files")
    print("\nWhat to check before posting: docs/PROMO-ASSETS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
