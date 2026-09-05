# Changelog

All notable changes to Shimmer are recorded here.
Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- The fixed-tones list under the analysis had lost its row layout (the
  frequency, depth and kind ran together) when the results styles were
  rewritten; its styles are back.

- **The dock no longer shows a stale preset, and no longer uses a button
  to show state.** After Analyze the dock button read "Analysis ready ·
  Sibilance Rattle 125%" and kept saying so after you applied a
  different match. A button names an action, so it now reads "View
  analysis" (it opens the workspace), and the state moved to a plain
  line under the two buttons that reads the live controls: "Vocal Glaze
  + Top End · 100% · master to Streaming (−14 LUFS)" or "· cleaning
  only". It updates on every change, including Apply. The Analysis card
  pill follows the applied match too.

- **Stage 3 is named by what it will do.** With mastering off, the big
  button and the stepper's third step said "Clean & Master" while the run
  only cleaned. Both now read "Clean" when mastering is off and "Clean &
  Master" when it is on, and switch as you toggle mastering.

- **"Preserve volume" could not be found.** Tips and the second-pass
  callout told you to keep Preserve volume on, but the option was labeled
  "Match loudness when mastering is off", sat inside the collapsed Output
  section, and was hidden entirely whenever mastering was on, which is
  when the tip appears. It is now called Preserve volume everywhere
  (Master and Batch), with a one-line note under it, and it stays in view
  while mastering is on, greyed and locked with the note saying the
  loudness target sets the level meanwhile. The tip now says where it is.

- **The suggested head cut no longer leaves a blip behind.** The cut
  used to land a hair past the tick, on its decay, and the "detected"
  box in the Trim view ended there too. The tick now ends where its slope
  has reached the floor (the middle of the noise band), the box shows
  that, and the suggested IN point sits 10 ms past it. The quiet floor
  between the tick and the song is left alone: that is the job of "Trim
  leading/trailing silence on export", which the Trim card now mirrors
  so the two sit together. Smaller ticks after the main click, or a
  faint one before it, count as part of the artifact, and the Trim
  notice says "plus 2 smaller ticks" when it found them. Tails work the
  same way, mirrored.
- **The player no longer piles up on narrow windows.** The transport bar
  was a flex row whose Monitor and Preview-loop zones could shrink to
  nothing, so the pills spilled over the loop controls and "Set from
  playhead" ran off the edge. It is now one grid with named zones that
  re-flows against the bar's own width: side by side on desktop, the loop
  controls on a second row below about 940 px, and every zone on its own
  row below about 580 px, where the pills and loop controls wrap. The bar
  keeps its 104 px height on desktop and only grows when it stacks. The
  top bar is now hidden on purpose below 1100 px instead of by accident.
- **Processed monitor no longer drops by half in Live preview.** Mastering
  normalised each loop slice on its own, so a quiet section previewed at
  the full target level even though the full run leaves it quiet. The
  Original-vs-Processed delta ballooned, and Loudness-matched A/B turned
  the Processed tab down by up to 6 dB with nothing on screen to say so.
  Preview slices now receive the same static mastering gain the whole
  file gets (Remix preview included), and the transport bar shows what the
  match is doing, e.g. "Processed −2.2 dB". The export was never affected.
- The progress window said "Cleaning & mastering" even with mastering off.
  It now says "Cleaning" when that is all the run does.
- **Trim missed the click at the start of most AI renders.** The scan
  looked for a gap of near-silence (below −75 dBFS) between the click
  and the music. AI renders rarely start from silence; the head sits at
  −60 to −70 dBFS, so the click and the song read as one piece and the
  card said "edges clean". The scan now also measures the head's own
  quiet level and looks for a short burst standing well above it, with
  the music starting later. Verified on a track whose 15 ms click at
  −41 dBFS was missed before and is now found, with the cut placed
  inside the quiet run before the music.
- **"Download WAV" could save a JSON file.** Results live in the server's
  memory. If the server had restarted since the run, the link answered
  with an error message and the browser saved that message as the
  "WAV". The button now checks the result first and shows the error in
  the metrics strip instead ("The server was restarted since this run.
  Run Clean & Master again.").

### Changed

- **A real transport.** The bridge had a play button and a clock. It now
  has back-to-start, back 5 s, play/pause, forward 5 s, the clock, and a
  scrubber that stretches between the two halves of the clock on the
  same line: click or drag to seek, the cyan fill is the playhead, and
  the amber band is the Live loop window. It works wherever the waveform
  is scrolled away and on a phone. The zone now has the same skeleton as
  Monitor and Preview loop (a small label, the main row, a sub line with
  the key shortcuts). The bar's three zones now split the width in
  proportion (transport 1.15, the others 1 each) instead of capping the
  other two at 460 px and handing every leftover pixel to the transport,
  and the monitor pills stretch across their zone. Buttons are 34 px and up for touch; when the bar
  stacks on narrow screens the buttons centre and the scrubber spans the
  full width, and the bar stacks below about 720 px so the transport and
  the monitor pills never collide.

- **The workflow stepper fills its row and names the stage you are in.**
  The three steps were small chips in a corner. They are now three equal
  segments across the page: the current stage has an amber underline and
  a filled amber number at 15 px, stages already done turn green, and the
  ones still to come stay grey. Same three elements, more room.
- **Stage numbers on every stage button, one colour per stage.** Choose
  file carries 1, Analyze carries 2 in the card and in the dock, and Clean
  & Master carries 3, so the buttons match the stepper. Each stage has
  one colour everywhere it appears: 1 teal, 2 cyan, 3 amber. The stepper
  shows state by fill and underline rather than hue (filled badge for the
  current stage, outlined for done, grey for what is still to come), and
  each stage button takes its stage's colour. The number stays while a
  button reads "Analyzing…" or "Processing…". The compact dropzone's
  Change button now spans the card, with the file name under it.

- **Analyze results read as a verdict, not a list.** Six identical cards
  gave no sense of what mattered, card 1 stayed highlighted by position
  even after applying another match, and the second pass was a paragraph.
  The applied match is now a hero block: the name at 18 px, the strength
  as a big number, a solid amber Applied pill, the match bar and the
  reason in full. It is whichever match is applied, so it moves when you
  click Apply on another; the other five sit in a quiet ranked table
  (rank, name, match bar, strength, Apply; the reason on hover). The
  second pass is a "Next step" callout with an amber rule: the two
  settings the pass needs shown as state rows ("Mastering off for this
  pass: On/Off", "Preserve volume on: On/Off", amber until right, green
  with a check once right) and one button. "Set up second pass" flips
  both; it then reads "Run this pass: Clean" and starts the run, with a
  line saying to upload the result and run the suggested preset next.
  Notes are a small Details list. In the workspace, four tiles run across the top: Applied, Second
  pass, Fixed tones, Top end. Amber now marks exactly two things: the
  applied choice and the next action.

- **The player gives its height to the view that earns it.** The waveform
  is a navigation strip (seek, loop window, dynamics), so in Waveform view
  it is now 150 px instead of 300. Spectrogram and Both keep the full
  height, where vertical resolution shows hash as streaks in the shaded
  band.
- **The live analyzer is now a measuring tool.** It grew from 64 px to
  170 px and gained a dB grid every 12 dB, labels at 100, 500, 1k, 2k,
  5k, 10k and 20k, and a 4.5 dB per octave display tilt around 1 kHz, so
  a normal mix reads close to flat and the top end, where the artifacts
  live, is no longer crushed into the corner. The scale is calibrated so
  a full-scale sine reads 0 dB. While Processed plays, the Original's
  smoothed spectrum shows behind it as a dashed line (and the other way
  round), so the difference is visible without flipping.
- **The loudness strip now measures loudness.** It looks the same, but
  the fill was plain RMS while its white marker was a LUFS target, two
  different scales. It now fills with momentary loudness (ITU-R BS.1770
  K-weighting, 400 ms) from the audio you are hearing, so the marker
  means what it says. A 1 kHz sine at -20 dBFS reads -20.0 LUFS. Hover
  the strip for the number.
- **Analyze's noise timeline is readable and clickable.** The caption no
  longer runs through the bars: "Noise over time" sits above the strip
  with a colour key, and a time axis sits below. Clicking the strip jumps
  there: with Live on it moves the loop window, otherwise it seeks the
  player.
- **The stat readout is grouped.** Chips now sit in three labeled rows:
  Loudness (LUFS in to out against target, true peak, LRA, limiter gain
  reduction, peak, RMS), Cleaning (5 to 8 kHz energy, flicker depth as a
  percentage, narrow peaks left, clicks fixed, fixed tones notched, top-end
  cutoff) and Job (trim, EQ, length as m:ss, rate, channels). "Limiter
  0.0 dB max GR" now reads "Limiter: no gain reduction".
- **The three frames now read apart.** The left rail, the page and the
  transport bar all sat on nearly the same near-black. The page stays the
  recessed work area; the rail is lifted one step above it and the
  transport bar two steps, both with a cool tint, with a hairline top edge
  and a soft shadow under the player. Rail buttons use translucent hover
  and active layers and the session card is a darker well, so they keep
  their contrast on the lifted deck. Cards and page controls are unchanged.
- **The Signal Chain view is now drawn from the real settings.** It used
  to be a fixed list: right about the order, wrong about the numbers
  whenever a preset moved the crossover or the center-channel scale, and
  missing Trim at the start and Preserve volume / Export at the end. The
  server now describes the chain from the same preset, strength, sliders,
  mastering, EQ and export choices a Clean & Master click would use.
  Badges show live values, stages that do nothing for the current preset
  are dashed with the reason, and the view refreshes as you change
  settings. (Phase 0 of docs/PLAN.md.)
- **Analyze now tests presets instead of guessing.** The old auto-detect
  scored every preset from a few spectral rules that pass on almost any
  music, so the same three or four presence-band presets came back for
  every track, and cleaning a track with its own "best match" did not
  change its score at all. Analyze now scans the whole file for calibrated
  evidence (steady tones, flicker, comb spacing, sibilance, tilt, tail
  residue), then runs every artifact preset through the real cleaning
  pipeline on the hottest few seconds and measures what each one actually
  removed — artifact-like residue versus body, transients and musical
  partials. The ranking is what worked, not what looked plausible.
- **Analyze sets Preset strength.** Each match now carries the strength the
  trial found best: the gentlest setting that reaches the top net benefit
  without adding collateral. Applying a match moves the Preset strength
  slider; Batch auto-detect and Remix auto-clean apply it per file (the
  batch strength slider now multiplies the detected value).
- **Six matches instead of three.** With verified numbers behind each card,
  the runner-ups are meaningful alternatives rather than noise.
- **Second-pass and balance hints.** When a different preset still finds
  residue on the winner's cleaned output, Analyze says so. Low-mid mud and
  a dull top end are flagged with the EQ-style preset to consider.
- **Steady tones are tested, not assumed.** Suno's fixed 16–20 kHz tones
  are found across the whole file, re-measured after each trial clean, and
  count toward the ranking. When the best preset still leaves a tone mostly
  intact, Analyze names the frequency, says whether it sits in the center
  of the mix (where cleaning runs at 20% by design) and points you to a
  Parametric EQ notch instead of a stronger preset.
- `shimmer --suggest` prints the verified table (score, confidence,
  strength, residue, collateral, purity) and the reasons.

### Added

- **"What changed": a spectrum comparison after every run.** A new card
  above the stat readout shows the whole-file spectrum before and after
  the pass, the removed signal, and a level-matched "after minus before"
  strip (cuts in cyan, additions in amber), on a 1/6-octave grid with the
  same display tilt as the live analyzer. One sentence on top gives the
  verdict: the deepest cut and where, how much the region below 2 kHz
  moved, and the overall level change. Hover for the numbers at any
  frequency. The level match uses the 100 Hz to 2 kHz region, where the
  cleaning does not act, so a top-end cut reads as a cut, not as a level
  change. Measured in `shimmer/report.py`, drawn by `static/js/report.js`.
- **Two release-check numbers in the Loudness row.** Peak-to-loudness
  ratio (true peak minus integrated LUFS) in and out, and stereo
  correlation in and out, energy-weighted over the file.
- **The Job row says what the download is.** "Export 24-bit WAV · no
  dither needed", "Export MP3 320 kbps", and so on.

- **Analyze in the dock, and an Analysis workspace.** Step 2 now has a
  cyan Analyze button above Clean & Master, so the next action is always
  in view. It runs Analyze and jumps to the Analysis card with a brief
  ring. When the analysis is done it becomes "View analysis", a cyan
  outline with a check in its badge, and the card header shows a "Ready"
  pill naming the applied match. Clicking it then, or the card's Expand
  button, slides the analysis
  up over the page as a workspace: the noise timeline across the top,
  ranked matches on the left, second pass, notes and fixed tones on the
  right, with "Loop the worst part" and Close in its header. The
  transport stays visible under it. Escape closes it, and a new upload
  closes it too.

- **Fixed tones are cut first, on both channels, at full depth.** AI
  generators leave thin fixed-pitch lines (16–20 kHz on Suno, sometimes
  comb-spaced teeth) that never move for the whole song. Shimmer scans
  the whole file for them once and removes them with narrow zero-phase
  notches before the tone curve and the crossover, so the center-channel
  protection that limited them to a 20–25% cut no longer applies.
  Analyze and the upload list the lines with checkboxes; Batch, Remix and
  the CLI apply the scan automatically (`--no-static-repair` to skip).
  (Phase 1 of docs/PLAN.md.)
- **De-click / de-crackle, first in the chain.** Clicks and crackle on
  the high end (the v5.5 consonant complaint) are found with a
  linear-prediction detector that only accepts short, isolated runs, so
  drum hits and consonant onsets are left alone, and are re-synthesised
  from their neighbours. On in Sibilance Rattle and Deep Scrub; a
  De-click slider in Advanced and `--declick` expose it everywhere.
- **Bandwidth-aware boosts.** Many renders end at 12–15 kHz. Analyze now
  reports where the top end stops, the tone curve never boosts above it,
  and a lifting shelf (Dark Mix Rescue, Reverb Flutter) is capped there
  so it cannot lift pure residue.
- **The Flicker Tamer can finally see the flicker.** AI hash flickers at
  10–50 times a second. The cleaning engine works on 93 ms frames, so
  anything faster than about 23 flickers a second averaged out inside a
  frame and the tamer did little. It now runs in a fine pass on a short
  23 ms window, on the high band, before the main engine, where it
  sees the whole range. (Phase 2 of docs/PLAN.md.)
- **A real de-esser.** A new spectral de-esser in the same fine pass
  turns down sharp "s", "sh" and "t" bursts per frequency, so the rest
  of the band keeps its brightness. It is not held back on transients,
  which is exactly where the old de-harsh went quiet. On in Sibilance
  Rattle, Deep Scrub and Vocal Glaze + Top End; a De-esser slider in
  Advanced.
- **De-harsh cuts the peaks, not the whole band.** Its cut is now
  weighted per frequency: glazed overtones take more of it, the band
  around them takes less, so a vocal keeps its air.
- **A reminder to master once.** When Analyze suggests a second pass and
  mastering is still on, the second-pass card says so in plain words, and
  Clean & Master asks before it runs. The dialog is built around the
  decision: a "Decision needed" kicker, the finding in one line, the
  state that matters ("Mastering is on for this pass") as a state row, a
  two-line why, then the recommended action full width ("Turn mastering
  off for this pass", noting it keeps Preserve volume on) with Cancel and
  "Master anyway" as quieter choices under it. Cleaning a mastered file and mastering it again
  hurts the sound, so master on the last pass only.
- **Trim — see and fix the blip at the start of a track.** Every file you
  load is now checked at both ends for the short glitch AI generators leave
  behind: usually 15–35 ms of noise at the very top of the render, before
  the music starts. Shimmer tells you when it finds one — how long it is,
  how loud, and how much silence follows it — and offers a suggested cut.
  Nothing is changed until you say so.
- **A view that actually shows the glitch.** The Trim view draws level in
  decibels instead of a normal waveform. These blips are quiet enough to be
  a flat line on a waveform, which is why they are so easy to miss. Zoom in
  to 250 ms, drag the marker, nudge it a millisecond at a time with the
  arrow keys, and hit Audition to hear the track as it will export.
- **You always know the scan happened.** A track with nothing wrong says
  "edges clean" in green. A track with a pending cut shows it in the card
  header, and the finished download says what was removed —
  "Trimmed 40 ms head".

### Why this is separate from "Trim leading/trailing silence"

The existing silence trim cuts everything below −60 dBFS. These glitches
are louder than that — around −50 dBFS — so the silence trim reads them as
the start of the song and leaves them alone. That is why they survived
until now, and why fixing one used to mean a trip to Suno Studio.

## [1.1.1] — 2026-07-23

### Fixed

- Status messages no longer say "Uploading." Shimmer runs fully offline and
  never uploads your audio, so the preview and Clean & Master steps now say
  "Preparing."
- The Processed and Removed monitor buttons now show a hover tip explaining
  how to turn them on — start Live preview or run Clean & Master — instead of
  a description you cannot use yet.
- Fixed the Removed button's hover tip, which named the wrong control
  ("cleaning strength"); it now points to "Preset strength."

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

[1.1.1]: https://github.com/henricksmedia/shimmer/releases/tag/v1.1.1
[1.1.0]: https://github.com/henricksmedia/shimmer/releases/tag/v1.1.0
[1.0.2]: https://github.com/henricksmedia/shimmer/releases/tag/v1.0.2
[1.0.1]: https://github.com/henricksmedia/shimmer/releases/tag/v1.0.1
[1.0.0]: https://github.com/henricksmedia/shimmer/releases/tag/v1.0.0
