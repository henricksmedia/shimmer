# Changelog

All notable changes to Shimmer are recorded here.
Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **Masters from an upgraded copy were 5 dB too quiet.** 1.1.1's default
  loudness was Streaming (-14 LUFS), so almost every saved settings file
  carried it, unchosen. 2.0 kept it, and mastered those songs well under the
  Commercial default (-9 LUFS) it was built for. A Streaming choice saved
  before this version now loads as Commercial, once. Pick Streaming again if
  you want it: from now on your choice is kept.

## [2.0.1] — 2026-09-24

### Added

- **Vocal grain card.** A new "What do you hear?" card for a grainy hiss
  that rides on an AI lead vocal and never quite goes away, often worse
  later in the song. Its tool, the voice de-noise, takes out a steady hiss
  floor, a hiss that follows the voice, and sharp little spikes. It reads
  the whole song once, the first time the card is on, so it can follow the
  hiss as it grows.
  - **Works on**, under its Amount slider: the centre of the mix (the
    default, needs nothing extra), or the vocal alone, split out by the
    Remix tab's splitter, for songs where cymbals share the centre with the
    voice. Without the splitter it uses the centre and says so.
  - Its Amount starts at 50 %. It was picked by ear on the author's songs.
    Unlike the other fixes, it is not held to the 0.10-sone limit: on five
    clean songs it took 0.17-2.1 sones at 50 %, because it also thins the
    steady top end of a song that has no grain. The first time you turn it
    on, a box says so and asks you to confirm. Check the Removed track: it
    should hold only hiss and grit.
- **Help** covers the new card: the card guide, a problem-and-fix entry,
  and a new answer in the "What do you hear?" quiz.

### Changed

- **Cleaner loud masters.** The peak shaper, which does most of the peak
  work at −9 LUFS, now runs at 4× the sample rate with both channels
  linked. It no longer folds harsh, off-key tones back into the top end,
  and the stereo image stays put.
- **Songs land on their loudness target.** The gain is checked against the
  finished loudness, after the shaper and limiter, and corrected: −9.01
  LUFS where 2.0.0 gave −9.09 to −9.32. A full master takes a few seconds
  longer (about 10-18 s for a 4-minute song).
- **Sibilance and Harshness stay under the damage limit at 100 %.** Their
  Amount tops were set on the loudest 8 seconds rendered on their own; the
  app works from the whole song, where they took more. Measured again that
  way: Sibilance now cuts up to 6.5 dB (was 7.2), Harshness up to 3.3 dB
  (was 5.1).

### Fixed

- The upload box and one quiz answer named a music service. They now say
  "AI song" and describe the sound instead.
- The tone curve could boost past the song's top cutoff, and with no cutoff
  found it boosted 16-20 kHz, which was mostly noise. It no longer boosts
  either.
- The Fixed tones notch could cut a held musical note (A7 on one song). A
  line off the generator's 200 Hz grid, at a note's pitch, is now left
  alone.
- 16-bit WAV files rounded every sample down, adding a little noise and a
  tiny DC offset. They now round to the nearest step, as FLAC always did.

## [2.0.0] — 2026-09-13

Shimmer 2.0 is a rebuild of 1.1.1. The sound engine is new. Every tab now
uses one sound path, so what you preview is what you export. The 19 presets
are gone from the Master tab. Instead, you say what you hear, and each
choice turns on one tool made for that problem. Each tool was measured on
test songs before it was turned on. Masters are louder by default: the
default loudness is now Commercial (-9 LUFS). This release also ships the
work done since 1.1.1 that was never released, such as the Remix lane
mixer, album mode and the release check.

**Updating from 1.1.1:**

- Your saved settings carry over. A 1.x preset turns on its matching card,
  at that card's default Amount. A saved loudness choice stays as it was.
- The old cleaning sliders (Advanced controls) and Preset strength no
  longer do anything.
- The command line still accepts the 84 retired 1.x flags. It ignores them
  and prints a note that names them.
- Scripts that call the server can still send the old fields (`preset`,
  `preset_strength`, `overrides`, `auto_detect`, `static_repair`,
  `cleaning.preset`). They are mapped to cards.

### Changed

- **One sound path.** The Master tab's preview and export, Batch, album
  mode, the Remix export and the command line all run the same code,
  `render()`. The preview is the export on a short window, level included,
  and a test holds the two equal. The path runs in this order: Read, Trim,
  Sample rate, Fixes, Tone, EQ, Master, Export, Report. No preset cleaning
  runs anywhere.
- **"What do you hear?" cards replace the 19 presets in the Master tab.**
  Turn on a card for each problem you hear. Each card that is on has one
  Amount slider.
  - **Shimmer** (fizzy, flickering hiss up top): Spectral de-noise. A small
    trained model that runs on your computer sets a gain for each frequency
    in 1.5-16 kHz. The first time you use it on a song, it reads the whole
    song once: about 50 s for a 3-minute song. The screen shows its
    progress, and turning the card off stops it. After that, a new Amount or a preview
    takes about 0.3 s.
  - **Fixed tones** (a whistle or whine that never changes): Notch filter,
    at full depth, as in 1.1.1.
  - **Sibilance** (harsh "s" and "sh"): De-esser. While a consonant sticks
    out, it turns 4.5-10 kHz down, by up to 7.2 dB at Amount 100 %.
  - **Harshness** (piercing upper mids): Dynamic EQ on up to two bands in
    2-5 kHz, by up to 5.1 dB.
  - **Low-mid build-up** (muddy, boxy): Dynamic EQ on one band in
    200-500 Hz, by up to 4.0 dB.
  - **Lack of air** and **Loudness**: handled in mastering, by the tone
    target and the loudness target.
  - **Clicks and crackle**: the de-click is built but has not passed its
    tests, so the card says "Not built yet" and changes nothing.
  - **Phasiness**: the card says "No fix yet" and can only be noted.
- **Each fix has a cap on what it may take from the music.** Sones measure
  how loud a sound seems to the ear. The top of each Amount slider is set
  so the fix takes at most 0.10 sones from a clean song. The Shimmer fix
  takes at most 0.064 sones. These were measured on five clean songs,
  through `render()` itself.
- **Commercial (-9 LUFS) is the default loudness.** 1.1.1 started at
  -14 LUFS, so masters sounded quiet next to released songs. The choices
  have new names and show as three cards in Master, Remix and Batch:
  Commercial (-9 LUFS, was CD / Club), Balanced (-11, was Loud) and
  Streaming standard (-14, was Streaming). Saved choices keep working.
- **Analyze is faster and names what it finds.** The 19-preset trial is
  gone. Analyze measures loudness, tone and fixed tones, marks each card it
  finds, and parks the preview loop with a top-end timeline. It takes 8.7 s
  on a 3:43 song, where it took about 30 s.
- **The song is uploaded once.** Analyze, EQ re-plans and the export reuse
  it, so each one starts faster.
- **Batch and album mode use the Master tab's path** for every file, with
  tags, silence trim and the release check. The log lists each file's
  findings in place of a preset guess. "Suggested EQ per file" uses the
  same EQ planner. Album mode measures each track just before mastering,
  picks one gain, then renders each track again with it. Nothing is parked
  on disk, and a long album is never all in memory.
- **The Remix export uses the Master tab's path.** The stems' effects and
  sum go through `render()`. The export writes tags and runs the release
  check. Its report says what ran, for example "Fixed
  tones, 2 notches". "Auto" applies what the remix shows (Fixed tones
  today).
- **The Remix preview matches the export.** The loop plays at once from
  its own mix, marked "level approximate". A few seconds later the whole
  mix is built, and the preview becomes `render()` on a window of it,
  marked "matches the export". A test holds any difference 60 dB down. The
  export then reuses that mix, which saves about 9 s on a 4-minute song
  with vocal effects.
- **The command line runs on the same path.** The 1.x commands still work.
  Mastering stays off unless you ask for it with `--master` or `--target`,
  as in 1.x. `--preset` turns on its card. `--release`, `--write-diff`,
  `--no-static-repair` and `--list-presets` work as before, and `--suggest`
  prints the findings.
- **Suggested EQ is judged the way the song renders**: after the fixes
  and, with mastering on, after the tone curve. The planner was copied over
  and makes the same plans on 12 test tracks. Its peak check now reads true
  peak per channel at 8x. On a cut-only plan for a ringing tone, it now
  says the limiter works about 1.1 dB harder (1.07 dB, where 1.1.1 read
  0.69).
- **Lossy ceilings are set from measurement.** MP3, OGG and M4A now use a
  -2.0 dBTP ceiling, where 1.1.1 used -1.5 for all three. Every lossy file
  is decoded after encoding. If it is still over -1.0 dBTP, it is turned
  down by the excess and encoded again, and the report says by how much.
  On drum-heavy songs an M4A can be turned down by up to about 2.5 dB. The
  format menus take their ceilings from the engine.
- **OGG Vorbis is written at quality 0.8** (about 270 kbps on a dense mix).
  It decodes at -1.29 to -1.91 dBTP.
- **The true-peak meter reads each channel at 8x.** 1.1.1 read a mono mix
  at 4x, so it read low whenever the channels differed. On the test render
  the upload analysis now reads -5.47 dBTP, where 1.1.1 read -5.92
  (0.45 dB low). The report's peak-to-loudness ratio (PLR) moves with it:
  12.43 dB, where 1.1.1 read 11.98.
- **Low-cut (high-pass) filters run one way.** The 25 Hz low-cut no longer
  rings ahead of a kick. In 1.1.1 its pre-echo started 32 ms before the hit
  at -25 dB. It is now -3 dB at 25 Hz, where it was -6 dB. It also removes
  DC offset, so a preview window needs nothing from the rest of the song.
  The user EQ's low-cut and high-cut work the same way: -3 dB at the set
  frequency, no pre-echo, and Q still sets the resonance.
- **A filter runs zero-phase only where it cannot smear a hit**, that is,
  where its pre-echo stays inside 20 ms. A test holds every filter to
  -60 dB beyond 20 ms before a hit.
- **16-bit dither at the textbook level.** TPDF dither is now ±1 LSB in
  total. 1.1.1 used twice the usual noise. On silence, 25 % of samples are
  now non-zero, where 1.1.1 had 56.5 %. A -100 dBFS tone still comes
  through, at -99.9 dBFS.
- **The Signal Chain view shows the new engine**: nine stage cards, drawn
  from the same rules `render()` follows. Stages your settings skip are
  dashed, with the reason. Cards that are on show in the Fixes stage, and
  cards with no working fix show under Noted. Once the preview has worked
  it out, Master shows the gain it adds.
- **The progress window reads its stages from the server**, with the
  engine's nine names. Stages a run skips show as skipped.
- **Download names drop the preset**: `{song}_{processed|removed|trimmed}_{id}`.
  A 1.x export processed again still loses its old suffix.
- **The tone target can be swapped.** Reference matching uses this. With no
  reference, the tone curve is 1.1.1's, bit for bit. A deadband (a range
  left alone) is built but stays off until it is judged by ear.
- **Parts that already worked were copied over unchanged** and checked
  against 1.1.1 (identical or bit-exact): the peak shaper and true-peak
  limiter (before the fixes below), silence trim, the edge-glitch scan and
  in/out trim, the fixed-tone scan and notch, the bandwidth cutoff and
  spectrum, the file fingerprint (so Remix projects and the stem cache
  still match), the report spectra and the release check.
- **Screens.** The bottom bar has a full transport (back to start, back and
  forward 5 s, and a scrubber that shows the loop), shared with the Remix
  tab. The live analyzer has a dB grid and frequency labels. The loudness
  strip shows momentary LUFS (BS.1770, 400 ms). The readout is grouped into
  Loudness, Cleaning and Job rows. The EQ has 13 starting points at
  mastering scale, in place of 1.1.1's 7. "Preserve volume" has the same
  name everywhere and stays in view.

### Added

- **Reference-track matching.** Under Mastering, pick Tone target, then
  Reference track, and load a released song. The tone moves toward it: 50 %
  of the difference by default, smoothed to about an octave, at most
  ±3 dB, level-matched first. An Amount slider sets how much. Shimmer warns
  when the two songs' drums differ a lot (one has 1.5 times the other's
  share of hits). It also says where matching stops when the reference's
  top end stops early.
- **WAV release copy: 16-bit, 44.1 kHz, with TPDF dither**, on the Master,
  Batch and Remix tabs, and `--release` on the command line. The sample
  rate changes before the chain runs, so the true-peak limiter works at the
  rate you deliver.
- **FLAC release copy: 16-bit, 44.1 kHz, with TPDF dither.** The same audio
  as the WAV release copy at about half the size ("Crosscut": 33 MB against
  48 MB).
- **Release check.** Every mastered run ends with one verdict: "Ready to
  upload", "n things to look at" or "Not ready". Each check shows its value
  and one line of advice: loudness against the target, true peak against
  the ceiling, clipping in the source, sample rate, format, silence at the
  ends, length, DC offset, mono compatibility and tags. A "Bass in mono"
  row says how far everything below 100 Hz drops in mono, and warns past
  -3 dB. "How loud it plays" says how far each of six streaming services
  turns the file up or down. Only two of them turn quiet tracks up.
- **Album mode in Batch.** It masters a folder as one record. One gain,
  set from the loudest track, goes on every track, so the tracks keep their
  relative levels and the loudest lands on the target. The limiter still
  runs per track. The log shows each track's level and an album line.
- **A Download step ends every run**, with the file's name and size. A new
  Settings tab holds **Download automatically** and **Download location**
  (the browser's Downloads folder, or a folder of yours).
- **A file size warning.** In Settings, "Warn when a file is over [50] MB".
  The size under Format is worked out before export, within 2 % of the
  written file on two songs. A file over the limit is offered the lossless
  formats that fit.
- **Remix lane mixer.** The Remix tab has three steps: Upload, Separate,
  and Mix & Render. Separation has quality tiers: Fast, Best, 6 stems
  (adds guitar and piano), Ultra and Studio. Stems are cached per track and
  per model. Each lane has its waveform, mute, solo, fader, pan and an
  effects rack (formant, saturation, doubler, reverb). Keys 1 and 2 switch
  between Original and Remix.
- **Residual lane.** What the separator leaves out (`mix − stems`: reverb
  tails, room) is kept as its own lane, so an untouched remix is identical
  to the original.
- **Stems export**: a ZIP of 24-bit WAVs, as separated or through the mix.
- **Trim finds the glitch at the start and end of a render**, usually
  15-35 ms of noise before the music. A dB view shows it, with a suggested
  cut. Nothing changes until you say so.
- **Suggested EQ.** Analyze plans a short corrective EQ: fixes first, cuts
  before boosts, four moves at most, boosts no more than +1.5 dB. A genre
  family (Neutral by default) sets how far each region may stray before a
  move is worth making. Every plan is checked on the loudest 20 s, so the
  limiter does not work harder.
- **Tags on every export.** The source's tags are read and kept. The blanks
  are filled from the Tags section: title, artist, album artist, album,
  genre, year, track, copyright and ISRC. A note in the comment tag records
  the run: the pass, every fix that ran (Fixed tones with its notch count,
  each card's fix at its Amount), each EQ move with its frequency, gain and
  Q, and the loudness target and ceiling.
- **"What changed"**: a before-and-after spectrum after every run,
  level-matched on 100 Hz-2 kHz, with a one-line verdict. The Loudness row
  adds peak-to-loudness ratio and stereo correlation, in and out.
- **Cancel, on the server.** `POST /api/cancel/{job_id}` stops a Master or
  Remix export between stages. The screens have no Cancel button yet.
- **Remember settings keeps your card picks.** With it on, the Master tab
  restores your cards, and your own picks stay when a new song loads. What
  Analyze found does not carry over.
- **New command-line flags**: `--fix CARD[=AMOUNT]`, `--no-auto`,
  `--reference FILE`, `--match-amount` and `--trim-silence`. A release
  check line prints after each file. `--list` shows which cards are ready,
  which fixes are built but have not passed, and which have no fix.
- **New server routes**: `GET /api/rules` (the cards, loudness choices,
  formats and EQ limits, stated once so no screen keeps its own copy),
  `POST /api/prepare` (the Shimmer fix's whole-song pass, with progress and
  cancel), `POST /api/cancel/{job_id}`, `POST /api/size`,
  `POST /api/reference`, `DELETE /api/reference/{session_id}` and
  `POST /api/reference/view`. For Remix: `GET /api/stems/engine`,
  `GET /api/stems/library`, `GET /api/stems/info/{session_id}` and
  `POST /api/stems/export`. `/api/process`, `/api/suggest` and `/api/tone`
  take a `session_id` in place of the file. `POST /api/settings` saves
  `fixes`, your card picks. A result that is not finished answers 409,
  not 202.

### Fixed

- **Limiter: peaks are found at 8x, not 4x.** Read at 16x, the output now
  reaches -0.98 dBTP (dense mix) and -0.93 to -0.94 (sparse mix) against a
  -1.0 ceiling. 1.1.1 reached -0.91 and -0.77 to -0.78.
- **Limiter: no clicks when it acts.** The gain now ramps across the 2 ms
  lookahead: at most 0.01 dB per sample (dense mix) and 0.04-0.06 dB
  (sparse mix). 1.1.1 dropped the gain within one sample, by up to 0.84 dB
  and 3.27-3.84 dB per sample. Loudness is unchanged.
- **Limiter: peaks stay under the ceiling.** It now aims 0.17 dB under the
  ceiling, the most a peak can hide between 8x readings. Read at 16x, peaks
  land at -1.09 to -1.15 dBTP against -1.0. 1.1.1 let -0.96 to -0.77
  through. This costs 0.01-0.04 dB of loudness.
- **The mastering tone match was a fixed 3 dB lift.** A units mix-up gave
  every track the same curve: about +3 dB of air on every mastered export,
  at every Tone match setting. The curve now differs per track and stays
  inside +2 / -3 dB. A bass-heavy song's lows come down a little. A
  balanced song gets close to nothing.
- **Shelf and bell filters land on their setting.** 1.1.1's preset shelves
  and bells ran forward and backward, so each landed at twice its setting:
  -3 dB became -6 dB. Bells now land within 0.1 dB and shelves within
  0.2 dB.
- **OGG export works.** In 1.1.1 every OGG export stopped with an error
  ("Invalid combination of format, subtype and endian"). OGG is now written
  a block at a time. At the old default quality it also went past full
  scale when decoded (+0.26 dBTP).
- **Lossy files no longer clip when played.** Decoded, 1.1.1's M4A reached
  +1.24 dBTP and its MP3 -0.42. See the lossy ceilings under Changed.
- **MP3 and M4A keep every bit.** They are encoded from 32-bit float, not
  from a 16-bit temp file with no dither.
- **Mono files stay mono.** Decoding no longer forces two channels.
- **A sample rate that cannot be read is an error**, not a guess of
  44.1 kHz.
- **The preview plays at the export's level.** With mastering off and
  Preserve volume on, 1.1.1 matched each preview window to its own level,
  so a quiet verse previewed louder than it would export. Now one gain,
  worked out from the whole song, serves the preview and the export.
- **A silent upload no longer fails.**
- **Every open tab gets a job's progress.** A second tab or a reconnect no
  longer takes the events away from the first.
- **"Download WAV" could save an error message as the file** after a
  server restart. The button now checks first and shows the error.
- **The Remix loudness match could silence the Original.** It is now
  capped at 6 dB, like Master's.
- **"Show in folder" works.** It failed on every real call, because the
  server never imported `sys`.
- **The comment tag names every fix that ran.** Its note named only Fixed
  tones, so an export with only the de-esser on said "no fixes".

### Removed

- **The 19 presets, the nine-stage cleaner and Analyze's preset trial.**
  1.x preset cleaning no longer runs anywhere. The Remix and Batch tabs
  still show the preset menu (see Known issues).
- **Advanced controls and Preset strength no longer apply.** Each card has
  one Amount slider instead.
- **Four unused server routes**: `POST /api/analyze` (an alias of
  `/api/suggest`), `GET /api/stems/status/{session_id}`, `GET /api/projects`
  and `GET /api/project/{digest}` (the project comes back with
  `/api/upload`). `?kind=original` on `/api/result` is gone too.
- **The old Signal Chain module** (`shimmer/chain.py`, 560 lines) and the
  **dead diagnostics module** (`shimmer/probe.py`, 274 lines), with the old
  chain view's tests. The new chain view is `shimmer/core/chain.py`.
- **Old server code**: 878 lines of dead 1.x code in `server.py`, including
  8 handlers the new routes answer first and 1.x's job pipeline.
- **84 command-line flags** (cleaning controls, custom ceilings and sample
  rates) no longer do anything. They still parse, with a note.

### Known issues

These are planned for later releases.

- The Remix and Batch tabs still show the old preset menu. A preset picked
  there turns on its matching card.
- Clicks and crackle has no working fix. The de-click is built, but in
  dense music it finds only 0-2 of 4 moderate pops, so the card says "Not
  built yet". Phasiness has no fix yet.
- With all four fixes (Shimmer, Sibilance, Harshness, Low-mid build-up) on
  at full, two of the five test songs lost a little more than one fix may
  take: 0.138 and 0.128 sones, against the 0.10 limit. Each fix still
  removes about as much as it does alone, and the preview still matches the
  export.
- The Sibilance, Harshness, Low-mid build-up and Shimmer fixes are on so
  they can be tried on real songs. Their blind listening rounds are still
  to come. The Shimmer fix passes on one of its four test models: at
  Amount 100 % it removes 61 % of the faint flicker it was trained on, but
  not steady fizz.
- Offline, icons show as words. The icon font loads from Google Fonts.
- No screen has a Cancel button yet, though the server can stop a Master
  or Remix export. Turning the Shimmer card off during a preview stops its
  first read.
- Batch has no cancel button. Its "Preset strength" slider and its
  "Auto-detect each file" choice do nothing in 2.0: the preset picked turns
  on its card either way.
- Remix ignores the Settings tab's download folder and size limit, and a
  remix of a song longer than 30 minutes stops at 30 minutes.
- In Remix, the doubler can drift out of time, and a formant shift can leave
  a silent tail.
- A reference track is not kept when you load the next song.
- Sound tuning is planned for 2.0.1.

### Developer tools

- **Efficacy harness** (`scripts/efficacy_harness.py`). It plants a known
  problem (`shimmer/artifacts.py`) in a clean song, runs a card's fix
  through `render()` as the Master tab does (`--cards <card>`), and reports
  how much of the problem went and how much music went, both in sones. It
  never asks the detector. On the 1.x presets it showed that only the notch
  clearly worked (96 % of a fixed line removed). Results are in
  `docs/efficacy-core.json` and `docs/efficacy-harness.json`; tests are in
  `tests/test_efficacy.py`.
- **Side-effect checks** (`shimmer/side_effects.py`): width, hits and
  pumping, on a clean song.
- **Blind rounds** (`scripts/make_fix_round.py`): level-matched, shuffled
  sets for each card, from the songs where it acts most.
- **Codec test case** (`scripts/make_codec_case.py`): clean masters through
  the EnCodec codec at 3, 6 and 12 kbps. Test material only; it never
  ships.
- **Tilt gap** (`scripts/tilt_gap.py`): 35 pairs of a mastering service's
  master and a Shimmer master of the same song. The Shimmer master was
  duller on 34 of 35, by 6.3 dB on average (800 Hz to 6.3 kHz tilt,
  spread 2.9). The earlier "11 dB" came from six songs on mixed settings.
- **Hearing model** (`shimmer/perceptual.py`). The linear-distortion
  constant S0 is corrected to 1 (Kabal 2002). Inputs are level-matched
  first, so a pure -3 dB gain reads zero instead of 13.6. Golden-value
  tests pin its outputs to 0.2 %. It is 6x faster: 0.11 s for a 5 s clip,
  where it took 0.70 s.
- **Contract tests** in `tests/core` and `tests/api`. CI runs on Windows
  and Linux with ffmpeg. `start.bat` reinstalls when `requirements.txt`
  changes. `SHIMMER_CONFIG_DIR` gives a copy its own settings folder.

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

[2.0.0]: https://github.com/henricksmedia/shimmer/releases/tag/v2.0.0
[1.1.1]: https://github.com/henricksmedia/shimmer/releases/tag/v1.1.1
[1.1.0]: https://github.com/henricksmedia/shimmer/releases/tag/v1.1.0
[1.0.2]: https://github.com/henricksmedia/shimmer/releases/tag/v1.0.2
[1.0.1]: https://github.com/henricksmedia/shimmer/releases/tag/v1.0.1
[1.0.0]: https://github.com/henricksmedia/shimmer/releases/tag/v1.0.0
