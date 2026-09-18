"""promo/videos.py — three vertical promo clips for Shimmer.

    python scripts/promo/videos.py [--out promo-assets]

Built from the screenshots (<out>/screens) and the engine's audio
(<out>/audio), following the video scripts on the marketing kit's posts
page:

  A  "This is what I removed"       the Shimmer card and the Removed track
  B  "Tell it what you hear"        the Sibilance card
  C  "Quiet next to released songs" loudness and the release check

Each segment is one still frame (caption, screenshot, footer) with its own
piece of audio, 1080x1920, about 20 s a clip. Run capture.mjs and audio.py
first. Needs ffmpeg on PATH. docs/PROMO-ASSETS.md.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
BG = (11, 13, 16)          # the app's --bg-0
FG = (233, 237, 243)       # the app's --fg-0
AMBER = (245, 165, 36)     # the README's amber
MUTED = (140, 148, 160)
EDGE = (40, 46, 56)
FOOTER = "Shimmer  \u00b7  free  \u00b7  runs on your computer"
BOOST = "volume=9dB,alimiter=limit=0.95:level=disabled"
# Windows ships these; any bold and semibold TrueType face works.
BOLD = "C:/Windows/Fonts/segoeuib.ttf"
SEMI = "C:/Windows/Fonts/seguisb.ttf"

CLIPS = {
    "A-this-is-what-I-removed": [
        ("That hiss isn't in your song.", "Sound on.", "master-original.png",
         "A-original.wav", 0, 3.0, False),
        ("I told Shimmer what I hear.", "Fizzy, flickering hiss up top", "cards.png",
         "A-original.wav", 3.0, 4.0, False),
        ("This is everything it took out.", "The Removed track, turned up", "master-removed.png",
         "A-removed-turned-up.wav", 0, 7.0, True),
        ("The same part, cleaned.", "Same loudness as the original", "master-processed.png",
         "A-cleaned.wav", 0, 7.0, False),
    ],
    "B-tell-it-what-you-hear": [
        ("You don't need to know what a de-esser is.", "Sound on.", "cards.png",
         "B-original.wav", 0, 4.0, False),
        ("Pick what you hear.", "Harsh, spitty \u201cs\u201d and \u201csh\u201d", "cards.png",
         "B-original.wav", 4.0, 4.0, False),
        ("Just the \u201cs\u201d sounds it turned down.", "The Removed track, turned up",
         "master-removed.png", "B-removed-turned-up.wav", 0, 7.0, True),
        ("Cleaned. Same loudness.", "Say what you hear. Hear it fixed.", "master-processed.png",
         "B-cleaned.wav", 0, 7.0, False),
    ],
    "C-quiet-next-to-released-songs": [
        ("Quiet next to released songs?", "Sound on.", "master-original.png",
         "C-original.wav", 0, 4.0, False),
        ("Commercial: \u22129 LUFS by default.", "One gain move, then a true-peak limiter",
         "master-processed.png", "C-mastered.wav", 0, 6.0, False),
        ("Checked before you upload.", "The release check", "release-check.png",
         "C-mastered.wav", 6.0, 6.0, False),
        ("Free. Runs on your computer.", "Shimmer", "master-after-run.png",
         "C-mastered.wav", 12.0, 5.0, False),
    ],
}


def wrap(draw, text, font, width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def frame(paths, name, title, sub, shot):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    f_title = ImageFont.truetype(BOLD, 86)
    f_sub = ImageFont.truetype(SEMI, 48)
    f_foot = ImageFont.truetype(SEMI, 36)
    y = 210
    for line in wrap(d, title, f_title, W - 140):
        d.text((70, y), line, font=f_title, fill=FG)
        y += 104
    if sub:
        y += 18
        for line in wrap(d, sub, f_sub, W - 140):
            d.text((70, y), line, font=f_sub, fill=AMBER)
            y += 62
    path = os.path.join(paths["screens"], shot)
    if not os.path.exists(path):
        raise SystemExit(f"missing screenshot: {path} (run capture.mjs first)")
    pic = Image.open(path).convert("RGB")
    if os.path.basename(path).startswith("master-"):
        # Keep the cards, the waveform and the Monitor bar; drop the side rail
        # and the right-hand column, so the part the caption talks about is
        # larger on a phone.
        w0, h0 = pic.size
        pic = pic.crop((round(w0 * 0.145), round(h0 * 0.13), round(w0 * 0.775), h0))
    target_w = W - 60
    pic = pic.resize((target_w, round(pic.height * target_w / pic.width)), Image.LANCZOS)
    max_h = H - 360 - max(y + 70, 700)
    if pic.height > max_h:
        pic = pic.resize((round(pic.width * max_h / pic.height), max_h), Image.LANCZOS)
    top = max(y + 70, 700)
    left = (W - pic.width) // 2
    d.rectangle([left - 3, top - 3, left + pic.width + 2, top + pic.height + 2], outline=EDGE, width=3)
    im.paste(pic, (left, top))
    d.text((70, H - 200), FOOTER, font=f_foot, fill=MUTED)
    out = os.path.join(paths["frames"], name + ".png")
    im.save(out)
    return out


def segment(paths, name, title, sub, shot, audio, start, dur, boost):
    png = frame(paths, name, title, sub, shot)
    wav = os.path.join(paths["audio"], audio)
    if not os.path.exists(wav):
        raise SystemExit(f"missing audio: {wav} (run audio.py first)")
    fade = f"afade=t=in:d=0.08,afade=t=out:st={dur - 0.15:.2f}:d=0.15"
    af = f"{BOOST},{fade}" if boost else fade
    out = os.path.join(paths["frames"], name + ".mp4")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", "30", "-t", f"{dur}", "-i", png,
        "-ss", f"{start}", "-t", f"{dur}", "-i", wav,
        "-af", af, "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-shortest", out,
    ], check=True)
    return out


def clip(paths, name, parts):
    segs = [segment(paths, f"{name}-{i + 1}", *p) for i, p in enumerate(parts)]
    listing = os.path.join(paths["frames"], name + ".txt")
    with open(listing, "w", encoding="utf-8", newline="\n") as f:
        for s in segs:
            f.write(f"file '{s}'\n")
    out = os.path.join(paths["video"], name + ".mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", listing, "-c", "copy", "-movflags", "+faststart", out], check=True)
    print("wrote", out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default="promo-assets",
                   help="where the assets live (default: promo-assets)")
    args = p.parse_args(argv)
    paths = {
        "screens": os.path.join(args.out, "screens"),
        "audio": os.path.join(args.out, "audio"),
        "video": os.path.join(args.out, "video"),
        "frames": os.path.join(args.out, "video", "frames"),
    }
    os.makedirs(paths["frames"], exist_ok=True)
    for name, parts in CLIPS.items():
        clip(paths, name, parts)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
