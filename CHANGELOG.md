# Changelog

All notable changes to Shimmer are recorded here.
Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- **The mastering tone match was a fixed 3 dB brightening, not a match.**
  `compute_tone_curve` compared a reference written in relative dB with
  the track's absolute band levels, so the "difference" was the same for
  every track: about −3 dB everywhere below 8 kHz and nothing above it.
  After the level gain that is a +3 dB air lift on every mastered export,
  at every Tone match setting. The analyzer also doubled every dB (it took
  20·log10 of a power). Both are fixed. The track is now measured as
  1/3-octave band power relative to its own 200 Hz–2 kHz median, and the
  reference is the same kind of number: the shape of released music
  (the AES study by Pestana, Reiss and others: about −5 dB per octave
  from 100 Hz to 4 kHz in the raw spectrum, flatter in recent decades),
  which is roughly flat from 60 to 500 Hz a few dB above the mids, then
  falling. The curve now differs per track and stays inside the same
  ±2 / −3 dB bounds. On a bass-heavy render the lows come down a little;
  a balanced track gets close to nothing. The EQ panel's grey silhouette
  is drawn from the corrected numbers too.

- **"Second pass" no longer runs the first preset again.** The Next
  step card was titled "Second pass with Sibilance Rattle", but its
  button ran this pass with whatever preset was applied, so on a file
  that had already been through Vocal Glaze it ran Vocal Glaze again.
  The card now names each pass and its preset: "Pass 1: Vocal Glaze +
  Top End now · Pass 2: Sibilance Rattle", and the button reads "Run
  pass 1: Vocal Glaze + Top End (Clean)". When pass 1 finishes, a
  Continue button loads its result right here, applies the pass-2 preset,
  turns mastering on, and shows the pass-2 card at once with both rows
  green and one button, "Run pass 2: Sibilance Rattle (Clean & Master)".
  Analyze is offered on that card as an optional check, not a required
  step. No download and re-upload. A file that
  is one of Shimmer's own exports is recognised by its name
  ({stem}_{preset}_processed_{id}); the dropzone says "Shimmer output ·
  pass 1 was Vocal Glaze + Top End", and the card becomes "Pass 2:
  Sibilance Rattle" with a line saying the next step is not the first
  preset again. Its state rows then ask for mastering on and Preserve
  volume off, and its button applies the pass-2 preset and runs
  Clean & Master. The card walks the sequence: pass 1 pending, pass 1
  done (Continue becomes the one action, the re-run is a quiet second
  button, the setting rows fold away), pass 2 pending, both done ("Both
  passes are done. Download from the green banner."). The green banner
  says "pass 1 of 2 · cleaning only" or "pass 2 of 2 · mastered". On a
  recognised pass-1 output the master-once question is skipped, since
  pass 2 is the last pass and should master.

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
  row below about 720 px, where the pills and loop controls wrap. The bar
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

- **The progress window shows the chain, live.** It used to say
  "Cleaning AI artifacts…" for most of the run. It now draws the Signal
  Chain as a wire with the eleven stages on it (Edit, Repair, Pre, Split,
  Fine, Engine, Recombine, Post, Level, Master, Export): audio comes in
  on the left as a small waveform packet, each stage lights in its own
  colour as the server reports it, the active one pulses, stages that
  are not in this run are dashed, and the packet leaves through Out when
  the file is written. Under it, the stage in plain words with its
  detail: "Fixing clicks and fixed tones · 3 fixed tones notched",
  "Splitting the band · below 4500 Hz passes through · highs go
  Mid/Side", "Cleaning: the 9-stage engine · Side channel", "Mastering ·
  level to −14 LUFS · peak shaper · true-peak limiter", "Writing the
  file · WAV · tags". The pipeline reports each stage as it starts
  (`clean_and_master(stage_callback=...)`), the job stream carries it
  as `{stage, status, detail}`, and an older server without stage
  events falls back to the old wording. The card is sized for the job:
  940 px wide on a desktop, stage names on one line, the stage in
  19 px type, so it reads from across the room.

- **The Suggested EQ card says whether it is in the EQ.** A state line under the verdict reads In the EQ, Held for pass 2 (this run is pass 1, cleaning only; the plan is made again on the cleaned file and applied by itself when pass 2 runs; use Apply to take it now), Goes into the EQ on the final pass, or Not in the EQ. The EQ strip shows the same state and its button says Apply now when the plan is held.

- **The Remix tab's player lives in the bridge.** Its transport, A/B
  and loop controls used to sit in a card that scrolled away with the
  page while the bottom bar showed the Master tab's idle player. The
  bar now belongs to whichever tab owns the player: on Remix it shows
  the same transport (start, back 5 s, play, forward 5 s, a scrubber
  with the loop window), a Monitor with 1 Original / 2 Remix, and the
  loop controls (Live is always on there, loop length, Set from
  playhead, the live status). The waveform stays in the page. Keyboard:
  Space, 1, 2, and the arrow keys work on the Remix tab like on Master.
  Fixed on the way: the remix render's report always said "Not
  mastered" because it read the wrong level of the metrics response.

- **The Remix tab uses the same live-chain window.** Stem separation
  shows Engine setup (only on the first run), Separate and Load, with
  the four stems as its Out; the remix render shows Mix, Analyze (when
  the cleanup preset is Auto), the Signal Chain phases that apply, and
  Export. The two inline bars under the buttons are gone. One module,
  `static/js/progress-chain.js`, now draws the window for every job.

- **EQ presets rebuilt at mastering scale.** The seven one-band
  sketches are replaced by thirteen starting points a mastering engineer
  would reach for, genre-neutral first: small broad moves (tonal 1 to
  1.5 dB, Q 0.7 to 1.0; corrective cuts a little narrower). Corrective:
  Rumble cut, Tighten lows, De-mud, Box cut, Smooth the top. Tonal: Tilt
  darker, Tilt brighter, Warmth, Open mids, Presence, Air (gentle), Vocal
  clarity. Creative: Lo-fi telephone. The old Air lift (+2 dB at 11 kHz)
  and Presence (+2 dB, narrow, at 3.5 kHz) were too hot for a master and
  worked against the cleaner on limited renders; Warmth no longer adds
  low-mid weight at 200 Hz. The menu is grouped and every entry says what
  it does; Air is greyed out when the render's top end stops under
  12 kHz. A preset still replaces the current bands, and every band stays
  editable.

- **Advanced artifact controls is a working pane, not a drawer.** The
  narrow side drawer with a bullet list above every group is replaced by
  a wide sheet. Controls sit on the left in chain order, in sections
  coloured like the Signal Chain (Repair, Band, Detection, Cleanup
  tools, Recombine, Post), labelled with the chain's own terms and a
  short gloss; each slider says what its two ends mean, right under the
  track. A Focus panel on the right explains whatever is under the
  pointer or keyboard and lights its stage on a mini chain. The tick
  under every slider is the preset's value at the current strength;
  anything you move is marked "changed", counted per section and in the
  header, and Reset all brings the preset back. Double-click a slider to
  reset it; Shift + arrow keys move ten steps. The header says whether
  the Live loop is on, since that is how a change is heard. Three
  amounts the presets already used but no slider reached are now
  sliders: Flicker Tamer, Tone Notcher and Noise Resynthesis (they scale
  with Preset strength like the others, and the Signal Chain links to
  them). The Help tab's Controls reference uses the same entries.

- **The Analysis card's help text is scannable.** The paragraph under
  the fixed-tones list is now one lead line, three numbered items across
  the full width (picks the preset, finds the worst spot, plans the EQ),
  and one closing line with the time it takes. While Analyze runs, the
  card shows one honest line and a moving bar instead of the help text.

- **Right pane in chain order, with state in every summary.** The
  Parametric EQ card now sits above Mastering, because the EQ runs
  before the mastering stage. Each section's summary line shows its
  state even when closed: "3 bands · suggested", "−14 LUFS · match
  medium", "WAV 24-bit", the artist name. Mastering's "Tone" tilt select
  is labelled "Tilt", the standard name, so only the tone match and the
  suggested EQ share the word tone.

- **The Signal Chain is drawn as a wired flow.** It was a row of
  identical grey boxes in a horizontal scroller. Stages now flow left to
  right and wrap like text, with one continuous wire that drops down and
  comes back to the left edge at each row break, so the whole chain fits
  the screen with no sideways scrolling. Colour carries meaning: each
  phase (Edit, Repair, Pre, Split, Fine pass, Engine, Recombine, Post,
  Level, Master, Export) has a hue, and the hues move around the wheel in
  signal order, on the wire, the card rail, the phase label and the
  badges. Every card shows where on the spectrum its stage works, as a
  small log-frequency bar with a tick at the crossover. Stages that do
  nothing for the preset are dashed with a one-line reason and a dashed
  wire into them. The summary moved to the top: stages on, STFT size and
  passes, the bypass point, the two gates, and a phase legend with on/
  total counts. The detail panel sits beside the flow and stays in view;
  it carries the phase, the stage number, a larger band bar with axis
  labels, the full text and every value, then the Advanced-drawer link.
  The server now sends each stage's phase and band (`chain.py`).
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
  and the monitor pills stretch across their zone. Buttons are 34 px and
  up for touch; when the bar stacks on narrow screens the buttons centre
  and the scrubber spans the full width, and the bar stacks below about
  720 px so the transport and the monitor pills never collide.
- **The workflow stepper fills its row and names the stage you are in.**
  The three steps were small chips in a corner. They are now three equal
  segments across the page: the current stage has a filled number badge
  and a full underline in its own stage colour at 15 px, stages already
  done keep an outlined badge and a faded underline, and the ones still
  to come stay grey. Same three elements, more room.
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

- **Suggested EQ (the Tone step).** Analyze now plans a short corrective
  EQ for the track, the way a mastering engineer would: fix first, shape
  second, cuts before boosts, nothing big. It looks only at the loud parts
  (windows within 6 dB of the loudest tenth), and judges the balance
  after the chosen preset's cleaning on the loudest 20 seconds and after
  the mastering tone match when mastering is on, so nothing gets
  corrected twice. Fix moves: a ringing tone (a narrow peak 8 dB above
  its neighbours in most loud windows, with no harmonic partner, not
  already a fixed-tone notch; never under 120 Hz), a mud stack (200–500 Hz
  more than 2 dB over the low-end trend), a harsh band (2–5 kHz more than
  2.5 dB over the top-end trend, cut at most 1.5 dB). Shape moves: at
  most three broad moves of 2 dB or less, only where a region sits
  outside the family's range; sub and bass moving the same way share one
  low shelf. Boosts stay at +1.5 dB (+1 dB from 5 kHz up, none at or
  above the render's cutoff). Every plan is checked on the loudest
  20 seconds: if peaks rise more than loudness, the limiter would work
  harder, so boosts are halved, then dropped. Four moves at most.
  - **Genre families are a tolerance, not a target.** Neutral (default),
    Pop, Hip-hop / Trap, EDM / Dance, Rock / Metal, R&B / Soul, Acoustic /
    Folk, Lo-fi / Ambient, Cinematic / Orchestral. A family says how far
    from neutral each region may sit before a move is worth making. No
    reference track, and no guessing the genre: the family is the user's
    pick.
  - **Where it shows.** The Analysis card gets a Suggested EQ block:
    the verdict ("2 moves suggested" or "Sits inside the Neutral
    range"), six region bars (sub, bass, low mids, mids, presence, air:
    the family range and where the track sits, before and after), the
    moves with their reasons, an amount slider, Apply to EQ, and the
    check on the loudest part. A tile in the workspace says the same
    in four words. The EQ card gets a strip with the same verdict, Apply
    or Remove, the family, and "Use on the final pass"; a See why button
    jumps to the block. Bands that came from the plan are marked S in
    the EQ chips and stay editable like any band.
  - **In the flow.** With "Use on the final pass" on (the default), the
    plan goes into the EQ by itself when Analyze finds one pass is
    enough. In a two-pass plan, pass 1 stays EQ-free, and pass 2 plans
    its own EQ on the cleaned file (Continue and Run both passes do
    this before pass 2 starts). The Passes card shows the step and its
    state. Changing the family re-plans in a few seconds; changing the
    preset, strength or mastering marks the plan stale with a Re-plan
    button.
  - **Batch:** "Suggested EQ per file" plans and applies an EQ for each
    file on its own (judged after that file's cleaning), added to any EQ
    from the Master tab, with a family picker. The log line says how
    many moves each file got.
  - New module `shimmer/autoeq.py`; `POST /api/suggest` returns
    `tone_plan` and takes `tone_family`, `mastering` and `overrides`
    form fields; new `POST /api/tone` re-plans a file; `GET
    /api/tone/families` lists the families. Tests in
    `tests/test_autoeq.py`.

- **Tags on every export.** A finished file now says what it is. The
  source's own tags are read (RIFF INFO and ID3 in WAV, Vorbis comments
  in FLAC and OGG, ID3 in MP3, iTunes atoms in M4A), carried through,
  and the blanks are filled from the new Tags section on the Master tab:
  Title (from the file's tags, else a cleaned-up filename, and editable
  per track), Artist, Album artist, Album, Genre, Year, Track number,
  Copyright (filled in as "© year artist" when empty) and ISRC. One
  note per pass goes into the comment ("Shimmer 1.1.1: pass 2, Sibilance
  Rattle 75%, EQ 1 band, mastered −14 LUFS / −1 dBTP"), so a file
  carries its own history; the pass number comes from the notes already
  in the source. WAV exports get both a RIFF INFO chunk (DAWs, libsndfile
  tools) and an ID3v2.3 chunk (Windows Explorer, most players); MP3 gets
  ID3v2.3 in UTF-16, the version everything reads. "Keep the file's own
  tags" (default) fills only the blanks; off, the fields replace them.
  Batch writes the same tags to every file. New module `shimmer/tags.py`
  (mutagen is a new dependency); tests in `tests/test_tags.py`.

- **Export names no longer chain.** A pass-2 file used to be named
  `song_glaze_processed_ab12cd34_rattle_processed_9f8e7d6c.wav`. The
  suffix is stripped before a new one is added, so every export reads
  `{original stem}_{preset}_processed_{id}`; the pass history lives in
  the tags instead.

- **A two-pass plan that runs itself.** When Analyze suggests a second
  pass, the Next step card becomes a plan: three numbered steps, Pass 1
  with its preset and "clean only", Pass 2 with its preset and the master
  target, and Download, each with a live status (next, running, done
  with its LUFS). One button, "Run both passes", sets the settings,
  cleans, loads pass 1's result in place, applies the pass-2 preset,
  masters, and stops at Download. Per-pass buttons remain for listening
  in between: "Run pass 1 only", "Continue: run pass 2", "Load the
  result, don't run yet", "Analyze this result first". "Stop after this
  pass" halts the automation between passes. Each state shows only what
  applies to it; the finished state shows a Download button and nothing
  about setting up.
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
