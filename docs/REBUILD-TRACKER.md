# Rebuild tracker

This page shows where the rebuild stands. It is updated in the same commit as
each piece of work. The plan and the reasons behind it are in
[ARCHITECTURE.md](ARCHITECTURE.md): §15 is the plan, §19 the review rules,
§19.3 the cards.

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

- **Branch** `rebuild`, in the folder `.claude/worktrees/rebuild`, on port
  7870. Not on GitHub yet: ask first.
- **Now:** finishing Step 3. Step 4's setup work can start.
- **Tests:** 412 pass. 109 contract tests wait for the new engine, and one
  waits for Step 6.

| Step | What | Status |
|---|---|---|
| 1 | Decide | Done 2026-09-12 |
| 2 | Settle the evidence | Done, with two optional listening rounds left |
| 3 | Contracts and the route map | In progress: route sign-off waiting |
| 4 | The new core | Next |
| 5 | Mastering | Not started |
| 6 | Cleaning, one module at a time | Not started (Shimmer research in progress) |
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
is signed off.

- [x] Contract tests in `tests/core` and `tests/api`, gated per module.
- [x] Route map: [API.md](API.md).
- [x] Adversarial review, with the fixes applied (ARCHITECTURE §19, commit
      `611eb58`).
- [x] Decisions D1, D3, D4 and D5 answered (§19.2).
- [ ] **Waiting:** D2, whether to put out a small 1.2 of today's app
      (recommended: no).
- [ ] **Waiting:** sign-off on [API.md](API.md) §1, the changes a user will
      see.

## Step 4 — The new core

*Done when:*

- the contract tests pass
- each ported piece nulls against the old one
- the Master tab runs end to end on the new core

**Setup, before engine code (§19.1):**

- [ ] The rebuild gets its own settings folder (`SHIMMER_CONFIG_DIR`), so
      your everyday settings are never touched (item 4).
- [ ] The launchers reinstall when `requirements.txt` changes, and a CI job
      upgrades a 1.1.1 install (item 5).
- [ ] CI runs on `rebuild`, with the new import list and a Windows job with
      ffmpeg (item 10).
- [ ] Decide the 2.0 download-name pattern, and freeze the 1.x preset keys
      (item 11).
- [ ] Push `rebuild` to GitHub as a backup: ask first.

**The engine:**

- [ ] `shimmer/core/audio`: file reading and writing, filters, meters.
- [ ] `catalog` and `settings`, with `migrate()` for old saved settings.
      Commercial is the default.
- [ ] `render()`, with the preview window and the output rate for each format.
- [ ] `export()`, with dither, tags and the overwrite guard.
- [ ] One job runner, with cancel.
- [ ] Measure each lossy format's overshoot and set its ceiling (item 12).
- [ ] `shimmer/api`, and the `GET /api/rules` route.
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

*Each module ships only when:*

1. it removes its fault on the ground-truth models
2. its cost in sones is acceptable
3. it wins or ties in a blind round

| Card | Tool | Status |
|---|---|---|
| Fixed tones | Notch filter (port) | Not started |
| Clicks and crackle | De-click, rebuilt | Not started |
| Sibilance | De-esser | Not started |
| Low-mid build-up | Dynamic EQ, 200–500 Hz | Not started |
| Harshness | Dynamic EQ, 2–4 kHz | Not started |
| Shimmer (the fizz) | Research first, then a new fix | Research in progress (2026-09-12) |
| Phasiness | A model first, then a tool | Not started |
| Lack of air | Tone target (Step 5) | With Step 5 |
| Loudness | Loudness target (Step 5) | With Step 5 |

- [ ] The cards and their Amount sliders are wired into the existing panels,
      with sign-off.
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
| 2026-09-12 | The Shimmer and Phasiness cards stay and get real fixes, researched first | §19.2 D3 |
| 2026-09-12 | The whole rebuild, in steps, tracked here | §19.2 D4 |
| 2026-09-12 | The bench, reference library and measurement files stay for all testing | §19.2 D5 |
