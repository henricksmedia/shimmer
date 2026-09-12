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
- **Now:** Step 4, the new core. The setup is done and the filters are
  built.

| Step | What | Status |
|---|---|---|
| 1 | Decide | Done 2026-09-12 |
| 2 | Settle the evidence | Done, with two optional listening rounds left |
| 3 | Contracts and the route map | Done 2026-09-12 |
| 4 | The new core | In progress |
| 5 | Mastering | Not started |
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
- [ ] One job runner, with cancel.
- [x] Measure each lossy format's overshoot and set its ceiling (item 12).
      Done for OGG (quality 0.8, -2.0) and MP3 (-2.0); M4A overshot by up to
      +2.9 dB and is being probed.
- [x] `shimmer/api`, and the `GET /api/rules` route. Its contract tests pass.
- [ ] Ports: each copied unchanged and nulled first. Each bug fix then lands
      on its own as a listed sound change (item 1).
- [ ] The transition rule: routes still accept the old fields
      ([API.md](API.md) §0).
- [ ] Move the Master tab's routes one at a time, and check the screen after
      each.

## Step 5 — Mastering (the main complaint)

*Done when:*

- it beats today's app in a blind test
- it does not lose to released songs at matched loudness
- a Commercial master in Windows Media Player holds up next to released
  music on Spotify, on the same computer

- [ ] Fetch the sources first (`STYLE.md` rule).
- [ ] Every loudness choice reaches its level cleanly: gain into unused
      headroom first, then gentle limiting.
- [x] Commercial (-9 LUFS) is the default. Decided 2026-09-12.
- [ ] New loudness names as three cards: mockup and sign-off first.
- [ ] Tone target as a replaceable input, with a deadband.
- [ ] Reference-track matching.
- [ ] Genre targets.
- [ ] Low-end mono and width checks.
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

- [ ] The cards and their Amount sliders are wired into the existing panels,
      with sign-off.
- [ ] Everything on at full, on clean music, passes the same checks.
- [ ] The screens read `/api/rules`, and the Step 6 test mark comes off.

## Step 7 — Finish, switch over, release

*Done when:*

- the release check passes
- CI is green on Windows and Linux, with ffmpeg
- updating from 1.1.1 is tested
- the changelog and README are updated

- [ ] Batch and album mode on `render()`.
- [ ] Remix:
  - [ ] its render and preview on `render()`
  - [ ] its cleanup menu becomes the cards
  - [ ] saved projects migrated
  - [ ] the doubler drift and the silent formant tail fixed
- [ ] The command-line tool, as a thin layer over `render()`.
- [ ] Old saved settings migrate.
- [ ] Delete the retired modules and their tests.
- [ ] README, `docs/README.md`, `FEATURES.md` and the help text rewritten; a
      new architecture doc.
- [ ] Release check: 1.1.1 against 2.0, blind; 2.0 must win or tie.
- [ ] Changelog: every sound change, with numbers.
- [ ] Pull request from `rebuild` into `main`, then release 2.0.0: ask first.

## Open questions (answered when their step comes)

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
