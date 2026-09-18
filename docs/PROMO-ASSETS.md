# Promo assets, made from the app

One command makes the screenshots, audio clips and short videos the
marketing kit's posts ask for, using a song of your own and the engine
itself. Nothing is staged: every screenshot is the real app, and every clip
is rendered by `render()`.

```bash
python scripts/make_promo.py --song "C:/music/your song.wav"
```

Shimmer must be running first (the default port is 7860; pass `--port 7870`
for a second copy). The run takes about ten minutes for a four-minute song,
most of it the Shimmer card reading the song twice: once for the preview and
once for the export.

## What it makes

Everything lands in `promo-assets/`, which git ignores.

**`screens/`** — the real app, at 1.5x for sharp images:

| File | What it shows |
|---|---|
| `master-removed.png` | The Master tab, two cards on, the Removed track selected |
| `master-original.png`, `master-processed.png` | The same screen on the other two tracks |
| `cards.png` | Every "What do you hear?" card, and the Fixes on list |
| `first-read-progress.png` | The Shimmer card reading the whole song, partway through |
| `export-progress.png`, `export-done.png` | The progress window during and after Clean & Master |
| `release-check.png` | The release check on the finished file |
| `master-after-run.png` | The Master tab after the run |
| `signal-chain.png` | The Signal Chain tab: every stage, in order |
| `check-page-loaded.png` | The first shot, proof the browser drew the page |

**`audio/`** — WAV and MP3 of each:

| Files | What it is |
|---|---|
| `A-original`, `A-cleaned`, `A-removed-turned-up` | The Shimmer card, on the 20 s where it acts most |
| `B-original`, `B-cleaned`, `B-removed-turned-up` | The same for the Sibilance card |
| `C-original`, `C-mastered` | True levels: the song as it came in, and cleaned and mastered |
| `pair-before`, `pair-after` | An honest before and after: both at −14 LUFS |

**`video/`** — three vertical clips, about 20 s each, for short-video apps.
They follow the scripts on the kit's posts page, and each has a caption to
use with it:

| File | Caption |
|---|---|
| `A-this-is-what-I-removed.mp4` | Post 06 |
| `B-tell-it-what-you-hear.mp4` | Post 05 |
| `C-quiet-next-to-released-songs.mp4` | Post 08 |

## The honesty rules it keeps

- **Before and after are loudness-matched.** The card clips sit at −16 LUFS
  and the posting pair at −14 LUFS, so nobody mistakes louder for better.
  Say that you matched them.
- **The Removed track is turned up, and says so** in its file name, because
  the app turns it up for monitoring too.
- **The busiest 20 seconds are measured, not chosen.** Each card's window is
  where that fix acts most on your song, from the same search the blind
  rounds use (`scripts/make_fix_round.py`).
- **No claim is added anywhere.** The captions come from the marketing kit,
  where every line is checked against the app (`static/marketing/`).

## What to check before posting

1. **Play the Removed clips.** They should be hiss, grit or "s" sounds. If
   you hear a melody or a snare, the fix cut too hard: lower that card's
   Amount and run again.
2. **Look at the screenshots** for anything you would rather not show: a file
   name, a folder, another tool's name. Rename the song file and run again if
   you need to.
3. **Watch a video on a phone.** The captions should be readable at arm's
   length.
4. **Read the release check shot.** It says "Ready to upload" only when the
   tags are filled in; the capture fills the title and album from the file
   name, and leaves the artist to you.

## Steps on their own

```bash
python scripts/make_promo.py --song "song.wav" --steps screens
python scripts/make_promo.py --song "song.wav" --steps audio,videos
node scripts/promo/capture.mjs --song "song.wav" --out promo-assets --mode cards
```

The screenshots step runs twice on purpose: once for every shot, then once
more in a taller window for the cards close-up, which does not fit a normal
window.

## If the screenshots fail

- **"did not answer in 45 s"**: the headless browser stopped drawing. The
  script already passes the flags that prevent it (`--disable-gpu` and the
  occluded-window flags). Each run takes its own debugging port and browser
  profile, so two runs cannot reach into each other's browser; pass
  `--cdp-port` to pin one.
- **"timed out waiting for the upload"**: Shimmer is not on that port, or the
  song is a format it cannot read.
- **"No Edge or Chrome found"**: pass one with `--browser`.
- A failed run writes `screens/failure-state.png`, which usually shows why.

## What it cannot make

- **A walkthrough with your voice.** Use the
  [getting-started guide](GETTING-STARTED.md) as the script.
- **A Remix clip.** Stem separation needs the side environment and a graphics
  card to be quick, so record that one by hand.

## Your music stays out of git

`promo-assets/` is ignored. The audio and videos hold your song, and this
repo is public. Only a screenshot belongs in the repo, and there is one:
`assets/screenshots/shimmer-home.png`, the image at the top of the README.
