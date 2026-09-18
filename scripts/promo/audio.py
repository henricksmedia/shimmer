"""promo/audio.py — promo audio for Shimmer, rendered by the engine itself.

    python scripts/promo/audio.py --song "C:/music/song.wav" [--out promo-assets]

Writes WAV (24-bit) and MP3 (320k) into <out>/audio:

  A-original / A-cleaned / A-removed-turned-up   the Shimmer card
  B-original / B-cleaned / B-removed-turned-up   the Sibilance card
  C-original / C-mastered                        true levels, for a loudness clip
  pair-before / pair-after                       both at -14 LUFS, an honest A/B

Each card's 20 seconds are the ones where that fix acts most on this song
(the same search the blind rounds use). Before-and-after files are
loudness-matched, so the listener judges the sound and not the volume. The
Removed tracks are turned up, as the app does, and say so in their names.

Needs ffmpeg on PATH for the MP3s. docs/PROMO-ASSETS.md.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from make_fix_round import _busiest  # noqa: E402  (one search, kept in one place)
from shimmer import core  # noqa: E402

CLIP_S = 20.0


def lufs(x, sr):
    return pyln.Meter(sr).integrated_loudness(np.asarray(x, np.float64))


def at(x, sr, target):
    return np.asarray(x, np.float64) * 10 ** ((target - lufs(x, sr)) / 20)


def together(*xs):
    """Scale a set of clips by one gain so none clips; keeps them matched."""
    peak = max(float(np.max(np.abs(x))) for x in xs)
    k = min(1.0, 0.98 / peak) if peak > 0 else 1.0
    return [x * k for x in xs]


def save(out_dir, name, x, sr):
    wav = os.path.join(out_dir, name + ".wav")
    sf.write(wav, np.asarray(x, np.float32), sr, subtype="PCM_24")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-b:a", "320k",
                    os.path.join(out_dir, name + ".mp3")], check=True)
    peak = 20 * np.log10(float(np.max(np.abs(x))) + 1e-12)
    print(f"wrote {name}: {lufs(x, sr):.1f} LUFS, peak {peak:.1f} dBFS")


def window(src, fixes, w, mastering=False):
    s = core.Settings(fixes=fixes, auto=False, mastering=mastering, preserve_volume=not mastering)
    r = core.render(src, s, window=w, with_removed=True)
    a, b = round(w[0] * r.sr), round(w[1] * r.sr)
    return src.at_rate(r.sr)[a:b], r.audio, r.removed, r.sr


def busiest_window(src, card):
    """The CLIP_S seconds where this card's fix acts most on this song."""
    start = _busiest(src, card, CLIP_S)
    return (start, min(src.duration_s, start + CLIP_S))


def card_clip(src, out_dir, tag, card, amount=1.0):
    w = busiest_window(src, card)
    print(f"{tag}: the {card} card acts most at {w[0]:.1f}-{w[1]:.1f} s")
    orig, clean, removed, sr = window(src, {card: amount}, w)
    # Original and cleaned at the same loudness; the Removed track turned up.
    o, c = together(at(orig, sr, -16.0), at(clean, sr, -16.0))
    (r,) = together(at(removed, sr, -20.0))
    save(out_dir, f"{tag}-original", o, sr)
    save(out_dir, f"{tag}-cleaned", c, sr)
    save(out_dir, f"{tag}-removed-turned-up", r, sr)
    return w


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--song", required=True, help="the song to use")
    p.add_argument("--out", default="promo-assets", help="where to write (default: promo-assets)")
    args = p.parse_args(argv)

    out_dir = os.path.join(args.out, "audio")
    os.makedirs(out_dir, exist_ok=True)
    src = core.Source.load(args.song)
    print(f"song: {args.song}  {src.duration_s:.0f} s at {src.sr} Hz")

    w_shimmer = card_clip(src, out_dir, "A", "shimmer")
    card_clip(src, out_dir, "B", "sibilance")

    # The loudness clip: true levels, nothing matched.
    orig, mastered, _, sr = window(src, {"shimmer": 0.5, "sibilance": 0.5}, w_shimmer, mastering=True)
    save(out_dir, "C-original", orig, sr)
    save(out_dir, "C-mastered", mastered, sr)

    # The honest before/after pair: both at -14 LUFS.
    before, after = together(at(orig, sr, -14.0), at(mastered, sr, -14.0))
    save(out_dir, "pair-before", before, sr)
    save(out_dir, "pair-after", after, sr)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
