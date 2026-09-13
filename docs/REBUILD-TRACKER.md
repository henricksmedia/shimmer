# Rebuild tracker

This page shows where the rebuild stands. It is updated in the same commit as
each piece of work. The plan and the reasons behind it are in
[ARCHITECTURE.md](ARCHITECTURE.md): §15 is the plan, §19 the review rules,
§19.3 the cards. The rule every piece must pass is "Never damage the music"
in [GOALS.md](GOALS.md).

**Why we are rebuilding.** Over two months the old engine grew layer by
layer:

- 19 presets
- a nine-stage cleaner
- six copies of the processing steps

Most of the cleaning could not be shown to work. Only the notch filter clearly
did. Masters came out quiet because the default was Streaming (-14 LUFS), and
the A/B player matched loudness, so the difference could not be heard.

The rebuild keeps the screens and the pieces that proved themselves. It
builds one engine behind them, and every part must pass its tests and a blind
listening test.

**Status words:** Done · In progress · Next · Not started · Waiting (on a
decision or on another step).

## Where we are

- **Branch** `rebuild`, in the folder `.claude/worktrees/rebuild`. Run it
  with `testing\start-rebuild.bat` (local only), which uses port 7870 and its
  own settings folder. Not on GitHub yet: ask first.
- **Now:** Step 5, mastering. Step 4 is done, apart from pushing the branch
  to GitHub (ask first).

| Step | What | Status |
|---|---|---|
| 1 | Decide | Done 2026-09-12 |
| 2 | Settle the evidence | Done, with two optional listening rounds left |
| 3 | Contracts and the route map | Done 2026-09-12 |
| 4 | The new core | Done 2026-09-12 (push to GitHub waiting) |
| 5 | Mastering | In progress |
| 6 | Cleaning, one module at a time | Not started (Shimmer research done) |
| 7 | Finish, switch over, release 2.0.0 | Not started |

## Step 1 — Decide

*Done when:* `GOALS.md` states the decisions in the author's words. **Done
2026-09-12.**

- [x] Keep the screens; rebuild the engine.
- [x] Remix and the whole app ship in the first release, working as before.
- [x] Loudness is the user's pick from the list, and each choice is reached
      cleanly.
- [x] The branch and its folder exist.

## Step 2 — Settle the evidence

*Done when:* each result is written into the checklist, with its limits.

- [x] Render the corpus through today's app (`testing/baseline`).
- [x] Fixed tones census: only 3.51 kHz is notched below 8 kHz (checklist 16).
- [x] Click and crackle models; the de-clicker measured, and it must be
      rebuilt (checklist 17).
- [x] The louder choices sound clean: "Loudest doesn't sound bad" (checklist 18).
- [x] Every loudness choice reaches its level, by meter and by ear
      (checklist 19).
- [ ] *Optional:* judge the 15 older sets in the main folder (tonecheck x3,
      quiet x8, learned x4) with `bench.bat`. Needed before Step 6, not
      before Step 4.
- [ ] *Optional:* save the 8 "Does louder sound worse?" answers.

## Step 3 — Contracts and the route map

*Done when:* the tests run and fail for the right reason, and the route map
is signed off. **Done 2026-09-12.**

- [x] Contract tests in `tests/core` and `tests/api`, gated per module.
- [x] Route map: [API.md](API.md).
- [x] Adversarial review, with the fixes applied (ARCHITECTURE §19, commit
      `611eb58`).
- [x] Decisions D1-D5 answered (§19.2). D2: no 1.2; the full rebuild goes
      ahead.
- [x] [API.md](API.md) §1 signed off, all nine changes.
- [x] "Never damage the music" written into `GOALS.md`, with a measured
      filter-phase rule (§19.1 items 16-17).

## Step 4 — The new core

*Done when:*

- the contract tests pass
- each ported piece nulls against the old one
- the Master tab runs end to end on the new core

**Setup (§19.1):**

- [x] The rebuild gets its own settings folder: `SHIMMER_CONFIG_DIR`, set
      by `testing\start-rebuild.bat` (item 4).
- [x] `start.bat` reinstalls when `requirements.txt` changes (a hash kept in
      `.venv`). All four cases were checked. A CI job installs 1.1.1's
      requirements, then updates (item 5).
- [x] CI runs on `rebuild`, with an import check that cannot go stale, and
      with ffmpeg on Linux and on a new Windows job (item 10).
- [x] 2.0 download names are `{song}_{processed|removed|trimmed}_{id}`. The
      1.x preset keys are frozen in `tags.py`, so old names still strip
      (item 11).
- [ ] Push `rebuild` to GitHub as a backup, so CI runs on it: ask first.

**The engine:**

- [x] `shimmer/core/audio/filters.py`: one design for every EQ-type filter.
      It passes 42 contract tests, including "no pre-echo more than 20 ms
      before a hit".
- [x] `shimmer/core/audio/meters.py`: loudness (BS.1770) and true peak
      (louder channel, 8x). Both pass their contract tests. A 3.5-minute song
      takes 1.6 s for true peak and 0.4 s for loudness.
- [x] `shimmer/core/audio/io.py`: reading and writing files. Ported, with
      three fixes:
  - MP3 and M4A are encoded from float, not from an undithered 16-bit
    temp file.
  - Mono stays mono.
  - A sample rate that cannot be read is an error, not a guess.
- [x] `catalog` and `settings`, with `migrate()` for old saved settings.
      Commercial is the default. 38 contract tests pass.
- [x] Mastering, ported: the peak shaper and limiter were copied
      bit-exact, then fixed in three listed steps (8x peaks, no clicks, aim
      under the ceiling). At 16x, peaks now read -1.09 to -1.15 dBTP, where
      1.1.1 read -0.77 to -0.96 (`SOUND-CHANGES.md`). Album gains and the
      tone curve pass their contract tests.
- [x] Silence trim, ported bit-exact.
- [x] `render()`: one sound path, with the preview window and the output
      rate for each format. All 13 render contract tests pass, including
      "the preview is the export on a window".
- [x] `export()`, with dither, tags and the overwrite guard. Every render
      and export contract test passes.
  - It found and fixed two OGG faults in 1.1.1: its OGG export always
    stopped with an error, and writing OGG correctly in one call crashed the
    process.
  - Lossy files are decoded after encoding and corrected, so they can
    never clip when played.
- [x] Tags moved into the engine (`shimmer/core/tags.py`). The old module
      now points to it, so there is one copy.
- [x] Analysis, ported and nulled against 1.1.1 (identical or bit-exact):
      the edge-glitch scan, in/out trim, fixed-tone scan, notch plan and
      repair, bandwidth cutoff, spectrum and file fingerprint.
- [x] Findings, for the cards that can measure today: Fixed tones and
      Loudness. Every analysis and repair contract test passes, including
      "a held note is not notched" and "a finished master gets no artifact
      findings".
- [x] One job runner, with cancel (`shimmer/api/jobs.py`). The 1.x Remix and
      stem jobs run on it unchanged; they finish rather than stop when
      cancelled.
- [x] The release check and the report (spectra, PLR, correlation), ported
      and nulled.
- [x] Measure each lossy format's overshoot and set its ceiling (item 12).
      Done for OGG (quality 0.8, -2.0) and MP3 (-2.0); M4A overshot by up to
      +2.9 dB and is being probed.
- [x] `shimmer/api`, and the `GET /api/rules` route. Its contract tests pass.
- [ ] Ports: each copied unchanged and nulled first. Each bug fix then lands
      on its own as a listed sound change (item 1).
- [x] The transition rule: routes still accept the old fields
      ([API.md](API.md) §0), tested with a 1.x preset request.
- [x] Checked in the browser on port 7870: a real song through the
      untouched Master tab.
  - Every call returned 200: process, upload, envelope, result and
    metrics.
  - The download had its 2.0 name.
  - There were no console errors.
- [ ] Move the Master tab's routes one group at a time (ARCHITECTURE
      §18.3), and check the screen after each:
  - [x] Sessions: upload, envelope and drop. The original now lives and
        dies with its session, and a silent upload no longer fails. The 1.x
        preview, stem and Remix routes use the same store, and their tests
        pass.
  - [x] Render and export: preview, process, progress, metrics, result, and
        a new cancel, all on `render()` and `export()`:
    - 15 route and session tests pass, including one that checks a preview
      window against the exported file, level included.
    - `/api/process` takes the session in place of the file.
    - Every progress listener gets every event.
    - A run can be cancelled between stages.
    - Download names drop the preset.
    - The 1.x fields still work.
  - [x] Analyze (`/api/suggest`) runs on the new engine (2026-09-12, once
        the "What do you hear?" card replaced the preset list).
    - It measures loudness, tone and fixed tones, gives the card's
      findings, and a top-end timeline that parks the preview loop.
    - The 19-preset trial is gone: 8.7 s on a 3:43 song, where it was
      about 30 s.
    - The preset fields come back empty, as the transition rule allows.
    - The Analysis card shows the approved verdict-first rows.
    - The Suggested EQ still comes from 1.x's planner, until the Step 5
      rewrite.
  - [x] Suggested EQ and `/api/tone` run on the new engine (2026-09-12).
    - 1.x's tone planner, ported and nulled: identical plans on 12 test
      tracks. Only the check's true peak reads differently (per channel at
      8x).
    - `core.tone_plan()` judges each song the way `render()` runs it:
      after the fixes and, with mastering on, after the tone curve.
    - Analyze, `/api/tone` and Batch use it; `shimmer/autoeq.py` points to
      it.
  - [ ] The chain view (`/api/chain`) still runs on 1.x. It draws 1.x's
        stages, so moving it means redrawing the Signal Chain view: a
        mockup first.

## Step 5 — Mastering (the main complaint)

*Done when:*

- it beats today's app in a blind test
- it does not lose to released songs at matched loudness
- a Commercial master in Windows Media Player holds up next to released
  music on Spotify, on the same computer

- [x] Fetch the sources first (`STYLE.md` rule):
      [MASTERING-SOURCES.md](MASTERING-SOURCES.md), 2026-09-12. What they
      settle, marked as our inference:
  - Commercial at -9 LUFS is a sound default (large-catalogue median about
    -8.5 to -9.5, chart hits -8.3). All loudness sources are vendors.
  - The release check had three services wrong. Amazon, Tidal and Deezer
    do not turn quiet tracks up; corrected in the new engine.
  - Genre targets: no reusable published curves exist. Build one curve
    from our own captures, adjusted for how percussive the track is.
  - Reference matching:
    - 50 % or less of the difference
    - smoothed to about an octave
    - level-matched first
    - at most ±3 dB
    - warn when the reference's tempo or percussion differs a lot
  - Low-end mono is a check, not a process. Flag steady negative
    correlation and side energy below about 100 Hz; mono bass only as a
    vinyl option.
  - The deadband (`REF_TOL_DB`) is in the published range, but its
    midrange is tighter than any guide: test it by ear.
- [x] Every loudness choice reaches its level cleanly: one static gain, then
      the fixed limiter.
  - On a dense mix, each choice lands within 0.3 LU, with peaks at or under
    -1.0 dBTP read at 16x.
  - A very dynamic track is never pushed past its target.
  - These are contract tests.
- [x] 1.1.1's tone curve, ported bit-exact and wired into `render()`: the
      target, Intensity and Tilt, with mastering on.
- [x] Commercial (-9 LUFS) is the default. Decided 2026-09-12.
- [x] New loudness names as three cards: mockup approved and built
      2026-09-12.
- [x] Tone target as a replaceable input, with a deadband (engine,
      2026-09-12).
  - `compute_tone_curve` takes the target and a deadband. With neither,
    it gives 1.1.1's curve bit for bit, tested against 1.1.1's own
    function.
  - The deadband (`REF_TOL_DB`, or one value) is built but off: its
    midrange is tighter than any published guide, so the bench decides.
- [ ] Reference-track matching.
  - [x] Engine (2026-09-12): `render(..., reference=song)` moves the tone
        toward the reference instead of the built-in target, following
        MASTERING-SOURCES.md §4:
    - 50 % of the difference by default (`Settings.match_amount`)
    - about an octave of smoothing
    - level-matched first
    - never more than ±3 dB
    - 1.1.1's +2 dB limit on boosts where fizz lives (5-12 kHz)
    - an empty top in an MP3 reference never cuts the song's real top
    - Tilt still applies. The preview matches the export, and every
      loudness choice still lands. 20 contract tests.
  - [ ] Upload route and screen: a mockup first, then sign-off.
  - [ ] A warning when the reference's tempo or percussion differs a lot
        (the sources' last rule).
  - [ ] Judge on the bench.
- [ ] Genre targets.
- [x] Low-end mono and width checks (2026-09-12), as checks, not a process.
  - New release-check row, "Bass in mono": how far everything below
    100 Hz drops when played in mono. It warns past -3 dB, where the bass's
    correlation turns negative. 8 contract tests, including out-of-phase
    bass under an in-phase top, which the whole-mix mono check misses.
  - Width across the whole mix: 1.1.1's mono check already flags a steady
    negative correlation; kept.
  - Not built: a guard for Shimmer itself narrowing the width. It belongs to
    Step 6's "lost width" rule and needs a sourced threshold (how small a
    width change the ear hears) before it can grade anything.
  - Mono bass as a vinyl option: not built; only if asked.
- [ ] A compressor, only if the bench asks for one.
- [ ] Judge on the bench: headphones and speakers.

## Step 6 — Cleaning, one module at a time

*Each module ships only when it passes the decision rule and "Never damage
the music" (`GOALS.md`):*

1. it removes its fault on the ground-truth models
2. its cost in sones is acceptable, and that cost sets the top of its Amount
   slider
3. it adds no new problems: pre-echo, musical noise, pumping, lost width or
   softened attacks
4. it wins or ties in a blind round

| Card | Tool | Status |
|---|---|---|
| Fixed tones | Notch filter (port) | Not started |
| Clicks and crackle | De-click, rebuilt | Not started |
| Sibilance | De-esser | Not started |
| Low-mid build-up | Dynamic EQ, 200–500 Hz | Not started |
| Harshness | Dynamic EQ, 2–4 kHz | Not started |
| Shimmer (the fizz) | See [SHIMMER-RESEARCH.md](SHIMMER-RESEARCH.md) | Research done 2026-09-12; real-codec test case next |
| Phasiness | A model first, then a tool | Not started |
| Lack of air | Tone target (Step 5) | With Step 5 |
| Loudness | Loudness target (Step 5) | With Step 5 |

**Shimmer, in order:**

- [x] Research: what it is, why past fixes fell short, candidate fixes.
- [ ] Judge the never-judged `quiet-*` sets and rounds 3 and 7 (free).
- [ ] A real-codec test case: clean masters through an open AI codec.
- [ ] Listening questions 1-3 in the research: is the codec damage "shimmer"?
      Birdies or hiss? Does it only go when the brightness goes?
- [ ] Update the test models to match what the listening shows.
- [ ] Try fixes in the ranked order, each against both test cases, then
      blind.

**All cards:**

- [x] "What do you hear?" is in the Master tab, where the preset list was
      (started 2026-09-12, at the author's request; approved mockup).
  - It reads its cards from `/api/rules`, and its findings from the upload
    and Analyze.
  - It sends the picks as `fixes` and `auto`.
  - Checked in the browser on "Alive Again": Fixed tones on with
    "Found · 3.51 kHz" (the tone the census found), Loudness
    "Found · 2.3 dB under", and no console errors.
  - Cards whose tool is not built show "Not built yet". Cards with no tool
    show "No fix yet" and can only be noted.
  - The mockup's "Solo band" button is left out until the player can solo a
    band.
  - The old preset card is hidden, not deleted, until Step 7.
- [x] Loudness menus (Master, Remix, Batch): the decided names, Commercial
      (-9 LUFS) as the default, and no "distortion risk" warning.
- [x] Loudness as three cards in Master, Remix and Batch (mockup approved
      2026-09-12). The choices come from `/api/rules`. The old menu stays in
      the page, hidden, as the value the other scripts read and set.
- [ ] The icon font loads from Google Fonts, like the app's other fonts:
      offline, icons show as words. Bundling it needs a download (ask
      first).
- [ ] The cards and their Amount sliders are wired into the existing panels,
      with sign-off.
- [ ] Everything on at full, on clean music, passes the same checks.
- [x] The screens read `/api/rules`, and the Step 6 test mark comes off
      (2026-09-12).
  - The three loudness menus are filled from the rules; no screen keeps its
    own copy of the choices or their LUFS numbers.
  - The player's target line takes its level from the chosen card.
  - The "no copies" test now passes for real.
- [x] The progress chain reads its stages from the server (2026-09-12).
  - Its names are the engine's: Read, Trim, Sample rate, Fixes, Tone, EQ,
    Master, Export, Report.
  - Stages the settings do not use show as skipped.
  - Checked in the browser on "Alive Again": Trim, Sample rate and EQ
    skipped, the rest ran, no console errors.

## Step 7 — Finish, switch over, release

*Done when:*

- the release check passes
- CI is green on Windows and Linux, with ffmpeg
- updating from 1.1.1 is tested
- the changelog and README are updated

- [x] Batch and album mode on `render()` (2026-09-12).
  - Every file goes through the Master tab's own path:
    - `render()` and `export()`
    - tags, silence trim and the release check (`api.render.export_file`)
  - A test holds a batch file equal to the engine's own render, within one
    24-bit step.
  - Album mode measures each track just before mastering's gain
    (`core.premaster_levels`), picks one gain, then renders each track again
    with it (`render(..., gain_db=)`). Nothing is parked on disk, and a
    long album is never all in memory.
  - The preset trial is gone; each file's findings are logged instead.
  - "Suggested EQ" uses the engine's tone plan for each file.
  - Not yet: a cancel button (batch is not on the job runner), and the
    Batch screen's preset menu becoming the cards.
- [ ] Remix:
  - [x] Its export on `render()` (2026-09-12).
    - The stems' effects and sum, then `render()` and `export()`.
    - A test holds the file equal to the engine's render of the mix.
    - It runs on the job runner, so it can be cancelled.
    - Its progress window reads the engine's stages.
    - The cleanup report says what ran: "Fixed tones, 2 notches", or
      which cards are not built yet.
    - It writes tags (from the original upload's, with the provenance
      note) and runs the release check, like every other tab.
  - [ ] Its preview on `render()`: Option A, chosen by the author
        2026-09-12. The loop plays at once from its own mix; the full mix is
        worked out in the background after each edit, and until it lands
        the status line says the level is approximate. Then the preview is
        the export on a window. The note lives in the existing status line,
        so no new screen element is needed.
  - [ ] its cleanup menu becomes the cards
  - [ ] saved projects migrated
  - [ ] the doubler drift and the silent formant tail fixed
- [x] The command-line tool, as a thin layer over `render()` (2026-09-12).
  - One file through `render()` and `export()`. A test holds its file
    equal to the engine's render.
  - The 1.x commands still work:
    - mastering only with `--master` or `--target`
    - `--preset` turns on its card
    - `--release`, `--write-diff`, `--no-static-repair`, `--list-presets`
    - `--suggest` prints the findings
  - The 84 retired 1.x flags (cleaning controls, custom ceilings and
    rates) still parse and are ignored, with a note naming them.
  - New: `--fix CARD[=AMOUNT]`, `--no-auto`, `--reference FILE`,
    `--match-amount`, `--trim-silence`, and a release-check line.
  - Lack of air and Loudness report "with mastering", not "not built yet",
    in every tab's report.
- [ ] Old saved settings migrate.
- [ ] Delete the retired modules and their tests.
- [ ] README, `docs/README.md`, `FEATURES.md` and the help text rewritten; a
      new architecture doc.
- [ ] Release check: 1.1.1 against 2.0, blind; 2.0 must win or tie.
- [ ] Changelog: every sound change, with numbers.
- [ ] Pull request from `rebuild` into `main`, then release 2.0.0: ask first.

## Proposals waiting for sign-off

- **A file size limit (asked 2026-09-12: a service takes 50 MB at most).**
  - An optional "Size limit (MB)" setting.
  - The Download step shows the exact size before export.
  - When the song will not fit, it suggests the format that does: WAV
    16-bit 44.1 kHz (10.6 MB a minute, 4:43 under 50 MB), then FLAC
    (lossless, about half the size).
  - It never picks a lossy format without asking, and never cuts the song.
  - Today's default, WAV 24-bit 48 kHz, is 17.3 MB a minute (2:53 under
    50 MB).
  - It needs a mockup before it is built.

- **The Remix preview matching the export (measured 2026-09-12).**
  - The export runs on the new engine now; the preview does not yet.
  - To match the export exactly, the preview must work from the whole
    remix. The tone curve, the fixed-tone scan and the loudness gain all
    come from the whole song.
  - On a 4-minute song with vocal effects on
    (`testing`-style probe, scratch `remix_cost.py`):
    - mixing the whole song takes 9.1 s (the vocal effects alone 7.6 s)
    - the engine's whole-song work takes 3.1 s
    - each later loop window takes 0.24 s
  - Option A (recommended): the loop plays at once, as now. The full mix
    is worked out in the background after each edit. For the few seconds
    until it lands, the screen says the level is approximate; then the
    preview matches the export exactly.
  - Option B: every edit waits for the full mix, 3 to 11 s.
  - Option C: keep today's preview, which is never exact.
  - It needs a mockup of the "approximate" state before it is built.

## Open questions (answered when their step comes)

- **The release check names streaming services on screen.** It lists
  Spotify, Apple Music, YouTube and others, while `STYLE.md` says never to
  name a third-party service in anything the user reads. 1.1.1 already did
  this. Keep the names, or describe the services generically ("services
  that turn quiet tracks up")? Decide in Step 6 with the screen work.

- **Users whose saved choice is Streaming.** Many saved Streaming only
  because it was the old default. Does updating keep Streaming, or move them
  to Commercial? Decide in Step 7, with the settings migration.

## Decisions log

| Date | Decision | Where |
|---|---|---|
| 2026-09-12 | Keep the screens; rebuild the engine | ARCHITECTURE §15 |
| 2026-09-12 | Final names from day one; the rebuild stays off `main` until 2.0.0 | §18 |
| 2026-09-12 | Remix and the whole app ship in the first release | GOALS.md |
| 2026-09-12 | Loudness is the user's pick from the list, reached cleanly | GOALS.md |
| 2026-09-12 | "What do you hear?" cards replace presets | §13.2a, §19.3 |
| 2026-09-12 | Commercial (-9 LUFS) is the default | §19.2 D1 |
| 2026-09-12 | No 1.2; the full rebuild goes ahead | §19.2 D2 |
| 2026-09-12 | The Shimmer and Phasiness cards stay and get real fixes, researched first | §19.2 D3 |
| 2026-09-12 | The whole rebuild, in steps, tracked here | §19.2 D4 |
| 2026-09-12 | The bench, reference library and measurement files stay for all testing | §19.2 D5 |
| 2026-09-12 | All nine user-visible route changes signed off | API.md §1 |
| 2026-09-12 | Never damage the music: accurate tools, the user decides, damage measured and capped | GOALS.md |
| 2026-09-12 | Filters: zero-phase only where pre-echo stays within 20 ms; low-cuts and long-ringing filters run one way | §19.1 item 16 |
| 2026-09-12 | 2.0 download names drop the preset | API.md §4 |
