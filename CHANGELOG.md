# Changelog

All notable changes to Shimmer are recorded here.
Versions follow [Semantic Versioning](https://semver.org/).

## [1.1.0] — 2026-07-23

### Added

- **Progress window for Clean & Master.** A pop-up shows a percent bar and
  the current step — cleaning, mastering, then finalizing — and closes on its
  own when your file is ready.
- **Live preview now explains itself.** A short note sits next to the toggle,
  and the first time you change a setting with it off, a one-time hint points
  you to it.

### Changed

- **Loading a track now plays the whole song by default.** Live preview — the
  short looping section for hearing edits quickly — is now something you turn
  on when you want it, instead of starting on its own.
- **Longer preview loops.** Loop lengths are now 10, 20, and 30 seconds
  (previously 5–20) and default to 20, so you hear more of the song.
- **Clean & Master moved to the top of the right panel,** next to the
  mastering settings. This frees space in the bottom bar so buttons no longer
  overlap on smaller or resized windows.
- **Preset strength moved above the preset list,** so it is visible without
  scrolling.
- The Monitor and Preview loop sections now match in width and line up.

### Fixed

- Playback could get stuck looping a short window even after Live preview was
  turned off. It now returns to full-song playback every time.
- After Analyze, matching levels could cut playback volume by more than half.
  The match is now capped so it can never make a track too quiet. This only
  changed what you heard in the app — your exported file was never affected.
- The waveform now recolors correctly — gray for Original, amber for
  Processed, red for Removed — when you switch tracks while Live preview is on.
- Cleaned up alignment and spacing in the file bar and the bottom transport
  bar across window sizes.

## [1.0.2] — 2026-07-22

### Fixed

- Corrected the About text and README credits.
- The app's internal version number now matches the release.

## [1.0.1] — 2026-07-22

### Fixed

- The Windows launcher reported *"could not install the audio libraries"*
  after a **successful** first-time install, then quit. If v1.0.0 told you
  the install failed, it almost certainly didn't — this release just reads
  the result correctly.
- Both launchers now verify the install by importing the libraries, target
  the app's own Python environment explicitly, and show the real error
  output when something genuinely goes wrong.

## [1.0.0] — 2026-07-21

First public release.

### Cleaning

- **19 artifact presets**, each targeting a specific kind of AI noise —
  Suno hash, cymbal sheen, laser whistle, vocal glaze, broadband fizz,
  checkerboard grid, and more — grouped by what you actually hear.
- **Analyze** listens to your track, scores all 19 presets against it,
  picks the best match, explains why, and anchors the preview loop on the
  worst-affected part of the song.
- **Preset strength** from 0–200% to dial any preset up or down.
- **Nine-stage cleaning engine** running in the frequency domain, with a
  spectral-flatness gate and 70 ms transient hold so drum hits keep their
  snap.
- **Your low end is never touched.** A linear-phase crossover at 4.5 kHz
  sends kick, bass, and vocal body around the cleaning entirely.
- **Mid/Side processing** above the crossover: the centre of your mix is
  cleaned gently, the sides fully.
- **Advanced controls** — 10 sliders for band, detection, and per-stage
  amounts when a preset gets you close but not all the way.

### Mastering

- Loudness targets: **Streaming (−14 LUFS)**, **Loud (−11)**, and
  **CD / Club (−9)**.
- Tone match against a neutral reference curve, plus a warm–bright tilt.
- **4× oversampled true-peak limiter**, with format-aware ceilings
  (−1.0 dBTP lossless, −1.5 dBTP lossy).
- Loudness is set with a single static gain — no multiband compression, so
  your dynamics survive.

### Listening

- **Three-way A/B**: Original, Processed, and **Removed** — the last one
  plays only what was stripped out, boosted so you can hear it. If you hear
  music in there, you cut too hard.
- **Loudness-matched A/B** on by default, so you judge tone instead of
  volume.
- **Live preview** loops a section and re-renders in about a second, so
  changing presets is instantly audible.
- Waveform, spectrogram, and overlay views, plus a live spectrum analyser
  and LUFS meter with a target marker.

### Remix

- Four-stem separation (vocals, drums, bass, other), GPU-accelerated where
  available and cached per track.
- Per-stem formant shift, saturation, doubler, and reverb, with mute, solo,
  and gain.
- Optional artifact cleanup and mastering on the final render.

### Other

- **12-band parametric EQ**, zero-phase, applied after cleaning and before
  mastering, with 7 starting presets.
- **Batch mode** — process a whole folder with one preset or auto-detect
  each file.
- **Signal Chain** view showing every processing stage in plain language.
- **Command line** interface for scripted use (`python -m shimmer`).
- Formats: WAV, FLAC, OGG natively; MP3, M4A, AAC via ffmpeg.
- Runs entirely offline. No account, no uploads, no telemetry.

### Known limitations

- Stem separation uses the CPU on Apple Silicon; GPU acceleration is
  NVIDIA-only for now.
- Windows is the most-tested platform. macOS and Linux are supported via
  `start.sh` but have had less real-world use — bug reports welcome.
- The Batch tab's folder picker needs Tk; without it, type the path
  manually.

[1.1.0]: https://github.com/henricksmedia/shimmer/releases/tag/v1.1.0
[1.0.2]: https://github.com/henricksmedia/shimmer/releases/tag/v1.0.2
[1.0.1]: https://github.com/henricksmedia/shimmer/releases/tag/v1.0.1
[1.0.0]: https://github.com/henricksmedia/shimmer/releases/tag/v1.0.0
