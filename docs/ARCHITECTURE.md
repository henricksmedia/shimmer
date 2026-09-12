# Shimmer: how it works today

Written 2026-09-11, as the ground truth for deciding whether to rebuild.

It covers two code lines:

- **`main`** at `c1d18e0` (2026-09-06) — what the app ships.
- **`fix/tone-target-and-measurement`** at `fec79e3` (2026-09-09) — 82 commits
  of measurement and listening work, not merged. Called "the evidence branch"
  below. Its documents (`GOALS.md`, `PITFALLS.md`, `STYLE.md`,
  `HANDOFF-CHECKLIST.md`, `BRIGHTNESS-ASSESSMENT.md`) are not on `main`. The
  `rebuild` branch starts from its tip (§18), so they come along.

How sure each claim is:

- **(measured)** — code was run for this document; the number is shown.
- **(recorded)** — taken from the project's own evidence files or listening
  records.
- **(read)** — read from source; not run.

---

## 1. The short version

**Size (read, measured).** About 15,400 lines of Python in 32 modules and
16,600 lines of frontend (10,800 JS, 4,150 CSS, 1,730 HTML). About 40 HTTP
routes. 236 tests pass and 3 skip, in 52 s (measured). The evidence branch
adds about 4,900 lines of code and scripts plus 265,000 lines of cached
measurement JSON.

**Most of the idea is sound.** Fix the fixed faults first, clean only the
high band, master once at the end, and let the user hear what was taken out.
Those rules came from real mistakes and should carry over into any rebuild.
One rule is in doubt: cleaning the centre at 0.2× protects vocals, but it also
blocks faults that sit in the centre — centred sibilance −2 %, centred tones
about 25 % (recorded). Fixed tones and clicks are not music and should not get
that protection.

**Most of the cleaning does not do its job (recorded).** Against injected,
known artifacts, only the static notch plan clearly works: it takes out 96 %
of a fixed tone at no measurable cost. The preset named for the main fault,
Suno Hash, removes 12 % of the hash. Two presets remove nothing and still take
music. See §8.

**The full chain lost every blind test (recorded).** On 2026-09-09, the
untouched render beat the full chain 3–0, and the service master beat the
chain 8–0. One listener, laptop speakers, short clips, and a tone target that
has since been reverted, so the chain after the revert has not been re-tested.

**Why masters sound low and dull next to released music.** Four causes stack:

1. **Level.** The default target is −14 LUFS.
   - **One render (measured).** On a 3 min 43 s render the limiter did no
     work (0.0 dB gain reduction) and true peak read −3.5 dBTP. The meter
     reads a mono mix; the limiter checks each channel.
   - **Across the eight bench songs (recorded).** The service masters
     average −10.0 LUFS against Shimmer's −14.0. That is a 4.0 dB gap, 1.4
     to 6.7 dB per song, taken from the bench answer keys (five of eight
     re-read for this document).
   - **The gap is gain, not compression.** Peak-to-loudness ratio is about
     10 dB for both, so the gap is mostly headroom Shimmer leaves unused.
   - **The service ignores the ceiling.** Its masters peak at about 0 dBFS,
     above the −1 dBTP that AES TD1008 recommends.

   When a player does not level-match, a Shimmer master plays about 4 dB
   below them.
2. **Tone.** On four same-song comparisons the automated flow left the
   master 11.0 dB darker on average than the reference across 800 Hz to
   6.3 kHz (range 7.8–13.7) (recorded, `BRIGHTNESS-ASSESSMENT.md` §1). It
   added low-mid and removed presence.
3. **A filter bug.** Preset shelves and bells apply at twice their written dB
   (measured, §10). A "−2 dB above 10 kHz" shelf is really −4 dB.
4. **Hearing.** The ear is most sensitive around 2–5 kHz (ISO 226
   equal-loudness contours; not re-fetched here). A master that loses presence
   sounds quieter even at the same LUFS, so causes 2 and 3 make cause 1 worse.

**The same job is written six times.** Load → fix → clean → master → save
exists separately for single-file export, live preview, batch, album, remix,
and the CLI (read, §5). The copies have drifted: the preview differs from the
export in 13 ways, and the CLI without `--preset` runs different settings from
the app while printing "Preset: generic".

---

## 2. The sound path, stage by stage

This is the order audio moves through on a single-file export
(`server._run_job_sync` → `pipeline.clean_and_master` → `mastering.master`).
Every stage that changes sound is listed. Timing is for a 3 min 43 s,
48 kHz stereo Suno render (measured).

| # | Stage | What it does | Code | Runs when |
|---|---|---|---|---|
| 0 | Load and resample | Decode (WAV/FLAC/OGG via soundfile; MP3/M4A via ffmpeg). The 16-bit release copy resamples to 44.1 kHz *before* the chain. | `audio_io.load_audio`, `resample_to` | Always |
| 1 | Edge trim | Cuts render glitches at the head or tail, with 5 ms fades. | `edges.apply_trim` | User accepts the suggested cut. Export only. |
| 2 | De-click | Finds clicks above 2 kHz with a 32nd-order linear-prediction model, keeps runs ≤ 2 ms that are isolated and sharp, and fills them by prediction from both sides. Slow: a per-sample Python loop. | `repair.declick` | Preset sets `declick` > 0 |
| 3 | Static notches | A whole-file scan finds fixed generator tones and comb teeth. Up to 24 zero-phase notches, ≤ 30 dB deep, on both channels at full depth. | `detect.scan_fixed_lines`, `repair.apply_static_repair` | Tones found |
| 4 | Tone curve | Compares the raw track's 1/3-octave shape to a reference shape and applies the bounded difference, before cleaning. Limits +2 / −3 dB; boosts in 5–12 kHz capped at +0.5 dB (+2.0 dB on the evidence branch); no boost above the source's cutoff. Plus the warm↔bright tilt. | `mastering.compute_tone_curve`, `apply_tone_curve` | Mastering on |
| 5 | Crossover | 1023-tap linear-phase FIR split. The band below the split skips all cleaning. Default 4.5 kHz; presets use 300 Hz to 4.5 kHz. | `bands.complementary_fir_split` | Always |
| 6 | Mid/Side | The high band goes to Mid/Side. Mid is cleaned at 0.2× strength, Side at 1.0× (presets use 0.2–0.5 for Mid). | `bands.encode_ms`, `pipeline._scaled_params` | Always |
| 7 | Fine pass | 1024/256 STFT on each of Mid and Side: a flicker compressor measured against a floor follower, and a spectral de-esser (4–10 kHz against 1–4 kHz). | `finepass.fine_pass` | Preset sets flicker or de-ess |
| 8 | Nine-stage engine | 4096/1024 STFT on each of Mid and Side. See §2.1. | `engine.process` | Always |
| 9 | Side width makeup | Where cleaning took more than 3 dB out of Side, gives back up to +1.5 dB, smoothed over 150 ms. | `bands.side_width_compensation` | Always |
| 10 | Recombine | Mid/Side decode, add the low band back, wet/dry mix against the toned input. | `bands.decode_ms`, `recombine_bands` | Always |
| 11 | Preset post filters | High-pass, high shelf, presence shelf, a low-pass at the cutoff when a shelf boosts, and a low-mid bell. **Applies twice the written dB** (§10). | `engine.apply_post_filters` | Preset sets them |
| 12 | Fade | 5 ms in and out. | `pipeline.py:285` | Always |
| 13 | Parametric EQ | Up to 12 RBJ bands, zero-phase, landing on the drawn dB. The browser merges Suggested EQ bands into this list. | `eq.apply_eq` | EQ on |
| 14 | Mastering | DC removal and a 25 Hz high-pass → one static gain to the LUFS target → soft peak shaper on the top ~2 dB → 4× oversampled true-peak limiter (2 ms lookahead, 50 ms release). See §3. | `mastering.master` | Mastering on |
| 15 | Export | Format and bit depth; TPDF dither for 16-bit PCM only. Tags, optional silence-trim copy, release check (mastering on only), before/after report. | `audio_io.save_audio`, `tags`, `release`, `report` | Always |

**Time (measured).** Generic preset: 21.7 s total. About 10 s is cleaning,
and 11.5 s is mastering, which measures loudness twice, runs a full spectrum
pass, and oversamples 4× for the limiter. Deep Scrub: 45.9 s, and its removed
signal is −24 dB against the input, where Generic's is −43 dB.

### 2.1 The nine-stage engine

Each STFT frame runs two shared gates and then the stages in a fixed order.

**Shared gates (read).**

- *Noise-likeness:* spectral flatness in the denoise band, mapped 0.25→0.70
  to 0→1.
- *Transient hold:* a jump in band energy above 6 dB starts protection. It
  drops cleaning to zero at once, holds 70 ms, then ramps back over 160 ms.
  The "dynamic" group (shimmer, de-harsh, flicker) gets the full gate; the
  "surgical" group (denoise, de-resonator, de-checker) gets 35 % of it.

| Stage | What it does | Default | Evidence |
|---|---|---|---|
| Expander | Pushes quiet 3–8 kHz tails further down (2:1 below −45 dB). | Off | Echo Sheen only |
| Denoise | Wiener-style gain from a minimum-statistics noise estimate, 1.5–16 kHz, floor −18 dB. | Off | In most presets |
| De-resonator | Dynamic notch on peaks that persist above a wide median, 300 Hz–12 kHz. Backs off in dense frames. | Off | |
| Shimmer suppressor | Cuts outlier bins above a local median in its band (default 5.1–7.2 kHz), scaled by noise-likeness and density. | **Always on** | |
| De-harsh | Band-vs-reference (1–4 kHz) level control with a per-bin weight. | Off | |
| Flicker tamer | Fast-vs-slow energy per sub-band in 4.5–12 kHz. | Off | **Dead code** whenever the fine pass runs, because the pipeline switches it off. |
| De-checker | Autocorrelation along frequency finds a steady comb spacing (80–600 Hz) and cuts the matching peaks. | Off | Checkerboard Grid removes −1 % of a comb (recorded) |
| Narrow-tone kill | Long-term (2 s) per-bin excess over a wide median; deep narrow notches, no gates. | Off | **On in every preset**, 0.3–0.9. Overlaps stage 3. |
| Noise resynth | Replaces the phase of noisy bins with random phase. | Off | In all but three presets |

**Optional extras (read).** `iterations` reruns the whole STFT pass up to 3
times. `pre_analyze` builds a whole-file mask from long-term excess and
applies it to every frame before the stages. Only Deep Scrub and Echo Sheen
use them.

**Mid is protected more than "0.2×" suggests (read, from the presets agent).**
The 0.2× is applied through the same function as the strength slider, so it
also turns off Mid's second iteration (`round(1 + 0.2)` is 1) and shrinks
Mid's denoise floor. Centred faults are hard to reach: centred steady tones
lose only about 25 %, and the de-esser removes −2 % of centred sibilance
(recorded, `PITFALLS.md`).

---

## 3. The mastering half

What `mastering.master` does, in order (read):

1. **DC removal and a 25 Hz high-pass.** Written as 2nd order, but zero-phase
   filtering applies it twice: it is −6.1 dB at 25 Hz, not −3 dB (measured).
2. **One static gain** to the target. Targets are −14 (Streaming), −11
   (Loud) and −9 (CD) LUFS. Preview slices use a whole-file estimate; album
   mode uses one gain from the loudest track.
3. **Soft peak shaper** — a rational curve that starts 2 dB below the ceiling
   and allows about 1 dB of overshoot into the limiter.
4. **True-peak limiter** — 4× oversampled detection, 2 ms lookahead, 50 ms
   release, ceiling −1.0 dBTP lossless / −1.5 dBTP lossy.

**What is not there.** No compressor of any kind (broadband, multiband or
bus), no clipper built for loudness, no saturation, no low-end mono, no width
control, no mid/side EQ, and no matching to a reference track. The only
stages that touch dynamics are the shaper and the limiter, and at −14 LUFS
neither engages.

**The loudness disagreement, stated plainly.** `BRIGHTNESS-ASSESSMENT.md` §2.9
(evidence branch) argues −14 LUFS is correct. Spotify, YouTube and Tidal play
at −14 LUFS and Apple Music at −16, so a louder master gets turned down, and
AES TD1008 favours a high peak-to-loudness ratio. That holds when the player
level-matches. It does not hold in a local player, in a DAW, or with
normalisation off. Those are the places the author compares, and there a
−14 LUFS master is 3–5 dB below released music. `GOALS.md` lists "not
loudness-first" as an *inferred* anti-goal and asks to be corrected. The
author's own report of the main problem ("very low sounding compared to
Spotify") is that correction.

**What closing the gap takes (recorded, 2026-09-12).** The peak-to-loudness
ratios match, so most of the 4 dB is plain gain:

- Gain alone, up to a −1 dBTP ceiling, gets about 2.5 dB.
- The last 1.5 dB needs gentle limiting.
- A compressor is not proven necessary.

Loudness is not the whole story, though. Level-matched and blind, the service
master still won 16 of 16 rounds, so tone matters too. The bench is where that
gets settled.

**How the reference tone shape changed (recorded).** The reference in stage 4
has moved four times:

1. `main`: a 1950–2010 average of commercial recordings (Pestana et al.,
   AES 135).
2. Branch: a median of 309 masters one service made from AI renders.
3. Branch: retracted as 7–9 dB too bright above 2 kHz; replaced by a curve
   derived from commercial music.
4. Branch: the derived curve lost a blind test on 7 of 8 songs (1 tie), so
   the service median was restored.

The delivered difference between the curves was only about 2 dB, because the
chain applies part of the target. The tolerance band (`_REF_TOL_DB`) is
defined and unused.

---

## 4. Analysis tools (these measure; they do not change sound)

| Module | Job | Notes |
|---|---|---|
| `detect.py` (1,409 lines) | **Analyze.** Scans up to 300 s for evidence (fixed tones, band balance, flicker, comb, sibilance, echo), turns it into a 0–1 prior per preset, then *tries* 16 presets on the hottest 5 s window through the real pipeline and scores what each removed. Then tunes strength and suggests a second pass. | About **28 pipeline runs per click** — roughly the cost of cleaning a 2–3 minute song (read). On `main` the score uses `purity`, which correlates −0.003 with audible damage and fired on 9 of 9 finished masters (recorded). The evidence branch replaces it with a net-benefit score from the hearing model: 0 of 2 references and 1 of 9 finished masters fire. |
| `autoeq.py` (782 lines) | **Suggested EQ.** Measures loud 3 s windows, fixes ringing tones, mud and harshness, then shapes toward a target plus a genre offset (9 families, no stated source). At most 4 moves; checks the limiter afterwards. | Tone is set in **five places**: tilt, tone curve, preset post filters, Suggested EQ, user EQ. They use different measurements, and a genre offset can fight the tone curve (read). |
| `edges.py` | Finds head/tail render glitches. | Focused, well tested. |
| `report.py` | Before/after/removed spectra, PLR, stereo correlation. | |
| `release.py` | Pass/warn/fail on loudness, true peak, clipping, format, silence, DC, mono, tags. | Reported true peak comes from a **mono mix** (`mastering.py:113`), so it reads low when L and R differ. The limiter itself is per channel, so the audio is safe. |
| `chain.py` | Builds the chain view from live settings. | Hard-codes several numbers and calls zero-phase IIR filters "linear-phase". |
| `tags.py` | Reads source tags, writes per format, adds a note per pass. | |
| `probe.py` | Old region analyser plus a one-line wrapper. | Dead except the wrapper. |

**Evidence-branch additions:**

| Module | Job | In the app? |
|---|---|---|
| `perceptual.py` | The BS.1387 (PEAQ) ear model: `missing` and `added` in sones, `lin_dist` for tilt. Level-matched, constants pinned by golden tests. | Yes — Analyze scores with it |
| `artifacts.py` | Known artifact models to inject into clean music (hash, fizz, tones, comb, sibilance). The author judged the hash model to be the real thing. | No (harness and training) |
| `budget.py` | Would cap cleaning to what the measured fault justifies. | No; fitted on four songs |
| `references.py`, `abtest.py` | Reference-library capture and the blind listening bench. | Dev pages only |
| `scripts/hash_learn/` | A small learned mask network (about 129k parameters) that removes hash. | No |

---

## 5. Entry points: six copies of one job

| Step | Single export | Live preview | Batch | Album | Remix render | CLI |
|---|---|---|---|---|---|---|
| Edge trim | ✓ | — | — | — | — | — |
| Resample for the 16-bit release copy | ✓ | — | ✓ | ✓ | ✓ | fixed 44.1 kHz |
| Static notches | ✓ | session scan | ✓ | ✓ | ✓ | ✓ |
| Tone curve from raw analysis | ✓ | ✓ | from the repaired signal | ✓ | ✓ | ✓ |
| Cleaning | ✓ | ✓ | ✓ | ✓ | if on | ✓ |
| User / Suggested EQ | ✓ | ✓ | ✓ | ✓ | **—** | **—** |
| Mastering gain | measured | estimated | measured | one shared gain | measured | off unless flagged |
| Codec-aware ceiling | ✓ | **— (always −1.0)** | ✓ | ✓ | ✓ | ✓ |
| Tags | ✓ | — | ✓ | ✓ | **—** | **—** |
| Release check | mastering on | — | ✓ | ✓ | **—** | no tag check |
| Removed-signal file | ✓ | ✓ | — | — | — | optional |

**Also read:**

- **Two-pass mastering runs in the browser.** It downloads pass 1, wraps it as
  a new file always named `.wav` (even when the export was MP3), uploads it
  again, and runs pass 2.
- **The file is uploaded again** for every Analyze, every tone re-plan and
  every export, although a server session already holds it.
- **Batch without album mode** writes `stem + ext` with no suffix. An output
  folder equal to the input folder overwrites the sources.
- **Preview vs export.** The preview differs from the export in trim,
  resampling, ceiling, how the mastering gain is found, preserve-volume and
  clip handling, padding and fades, cutoff source, repair-scan source, stage
  warm-up (1.5 s against the whole song), removed-signal normalising, and
  output format. It is also 16-bit with no dither.

---

## 6. Remix

**What it does (read).** Remix separates stems with Demucs or Mel-Band
RoFormer in a side environment (about 3 GB of torch, plus 80–915 MB of model
weights per tier). It then gives each lane gain, pan, mute and solo, and
formant, saturation, doubler and reverb. The lanes are summed, and the sum
can go through the same cleaner and mastering as a single file. A residual
lane makes the stems add back to the exact mix.

- **It is a second product (read).** It has its own routes, a 1,792-line UI
  with its own transport, A/B, mastering controls and report, and its own
  export. That export skips tags, the release check, user EQ, trim and
  save-to-folder.
- **The planned reason for stems was never built.** The plan was "clean each
  stem, then sum". What is built is "creative effects, sum, then the same
  cleaner". On the evidence branch, stem separation was measured as a route
  to removing hash, and rejected (recorded, checklist item 15).
- **Bugs (read):**
  - The doubler time-stretches the whole signal instead of modulating a short
    delay, so it drifts about 1.7 s out of time over a 4-minute song.
  - The last ~50 ms of the formant shifter output is silent.
  - The reverb has no damping or tail.
  - By default the loop preview does not clean, but the render does.

---

## 7. Frontend

- **Five tabs** (Master, Remix, Batch, Chain, Settings) plus Help. There is a
  persistent bottom bar for transport, monitoring and the loop.
- **`single.js` is one 3,218-line closure.** Every Master feature is a nested
  function in `initSingleTab()`.
- **The DOM holds the state.** A hidden `<select>` is the source of truth for
  the preset. Two-pass automation works by clicking the process button and
  waiting for an event.
- **About 180 controls across the app;** about 60 on Master, plus 15 in the
  Advanced drawer. Mastering, format and tone-family controls each appear two
  or three times.
- **Backend rules copied into JS.** At least 12, each a place to drift:
  - the strength whitelist
  - LUFS targets
  - format ceilings
  - EQ maths and limits
  - BS.1770 K-weighting
  - chain phases
  - the preset catalogue (Help knows 17 of 19)
  - stem tiers
  - download-name pattern
  - the A/B cap
- **The original plan was simpler.** The refactor steps aimed at a simple
  "finish my AI song" app with a few finish styles. The product drifted into
  a pro-style console (recorded, `docs/refactor/step10.md` against the
  current UI).

---

## 8. Presets

There are 19 visible presets and 8 hidden aliases. Each is a flat factory
over a 152-field `Params`. They use only **12 distinct combinations of
stages**. Every preset turns on narrow-tone kill. Many repeat defaults, or
repeat the mastering high-pass as `subsonic_hz=25` (read).

**Preset strength** (0–200 %) blends each "amount" key from the neutral
default toward the preset value. It zeroes positive shelves, so Dark Mix
Rescue loses its +2.5 dB air lift at any strength other than exactly 100 %
(read).

**Efficacy against known artifacts** (recorded, tabulated from
`docs/efficacy-harness.json` at 2.0 sones; cost = music removed from a clean
host):

| Verdict | Presets |
|---|---|
| Works | **Static notch plan** (not a preset, runs first): 96 % of a fixed tone, cost 0 |
| Small effect, cheap | Cymbal Sheen (27 % of a tone), Laser Whistle (28 % of a whistle), Brittle Air (28 % tone, 2 % fizz) |
| Works by taking the most | Vocal Glaze + Top (29 % hash, cost 0.106 — over the 0.10 limit); Deep Scrub (24 % hash, cost 0.164) |
| Does little on its own target | **Suno Hash 12 %**, Broadband Fizz 6 %, Presence Haze 7 %, Echo Sheen 5 %, Harsh Veil 4 %, Vocal Glaze 4 %, Phantom Cymbal 2 % |
| Harmful | **Checkerboard Grid** −1 % of a comb; **Sibilance Rattle** −2 % of centred sibilance, at real cost |
| Tone moves only | Muddy/Boxy, Dark Mix Rescue |
| No model yet | Reverb Flutter, Cymbal Chatter |

---

## 9. What the evidence branch established (recorded)

1. **The hash is the open problem.** "No treatment in the product today
   removes what the author hears as shimmer on a hashed render" (`GOALS.md`).
   - Four hand-built routes failed: per-bin subtraction, stem separation, and
     replacements for the flicker feature (checklist item 15).
   - The learned remover is the lead. Its third model removes 81 % of
     modelled hash on one held-out song but 17 % on another, at an acceptable
     cost (0.064 sones).
   - On real renders it takes only hash, but too little. Round 6 found it
     "harmless, mostly too gentle".
   - It is not in the app, and a test forbids ML imports in the cleaning
     path.
2. **The evidence tools are trustworthy and worth keeping.**
   - The hearing model: pinned, reproducible, level-matched.
   - The efficacy harness: ground truth, never uses the detector's own
     numbers.
   - The corpus check: it caught two mislabelled files that neither listening
     nor spectra revealed.
   - The blind bench.
3. **The decision rule** (`GOALS.md`), in order:
   - Does it remove the fault, measured independently?
   - What did it cost, in sones?
   - Where does it land against real records?
   - Does it sound better, level-matched and blind? **This one is final.**
4. **Still unjudged:**
   - Round 3 and round 7.
   - The `quiet-*` sets, which play the most exposed passage.
   - The `learned-*` sets.
   - The headphone tone re-check.
   - The chain after the tone revert, against untouched and the service.

---

## 10. Known bugs

| Bug | Confidence | Where |
|---|---|---|
| Preset shelves and bells apply at 2× their dB (−3 → −6.0, +1.5 → +3.0, −2 bell → −4.0) | measured | `dsp.apply_high_shelf`, `apply_peaking`: full-gain design run through `sosfiltfilt` |
| Mastering 25 Hz high-pass is −6.1 dB at 25 Hz (acts as 4th order) | measured | `dsp.apply_highpass` via `mastering.master` |
| Reported true peak uses a mono mix | read | `mastering.measure_true_peak_db` |
| Dark Mix Rescue's air lift vanishes at strength ≠ 100 % | read | `params.apply_preset_strength` clamp |
| CLI with no `--preset` runs bare `Params()`, prints "generic" | read | `cli.py:243`, `436` |
| "Show in folder" returns 500 (`sys` not imported) | read | `server.py:305` |
| OGG export asks libsndfile for 24-bit PCM in OGG, which it rejects ("Invalid combination of format, subtype and endian") | measured (the soundfile call; the route itself was not run) | `audio_io.py:54` |
| Uploaded originals are never deleted | read | `server.py:1553`, `preview_store.py:75` |
| Batch can overwrite sources when output = input folder | read | `server.py:1218` |
| Remix doubler drifts ~1.7 s over 4 min | read | `stem_effects.py:129` |
| Live preview ignores the codec ceiling (always −1.0 dBTP) | read | `/api/preview` |
| Learned remover flipped phase above strength 1 (fixed on branch) | recorded | `hash_learn/infer.py` |

---

## 11. Things done in more than one place

| Job | Places |
|---|---|
| Fixed tones | static notches, narrow-tone kill (every preset), de-resonator, the pre-analyze mask, Suggested EQ ringing cuts, Analyze's "try a notch" advice |
| Tone shaping | tone curve, tilt, preset post filters, Suggested EQ, user EQ, two EQ-only presets |
| Sibilance / harshness | fine-pass de-esser, de-harsh, Suggested EQ harsh cut, the tone curve's boost guard |
| Flicker | fine-pass flicker tamer, engine flicker tamer (dead), `detect._flicker` |
| Multi-pass | engine iterations, pre-analyze, browser two-pass, album two-pass |
| Spectrum measurement | seven separate implementations |
| RBJ biquad maths | three copies in Python, one in JS |
| Load → clean → save | six (§5) |
| Job runner and progress | four copies, two event formats |

---

## 12. What to carry into any rebuild

**Rules that came from mistakes** (from `PLAN.md` §0, `refactor/step0.md`,
`STYLE.md`, `PITFALLS.md`):

- Sound changes only at their proper point in the chain. Analysis measures
  and never alters.
- Fixed faults are repaired first, before anything that reacts to the signal.
- Master once, at the end. One static gain. No loop of gain and limiting.
- Codec-aware ceilings. True-peak detection per channel.
- Level-match every comparison, inside tools and in the app's A/B.
- A track with no fault comes out essentially untouched.
- A metric that cannot fail is not a metric. Test every measure on material
  where the answer is known.
- Listening, level-matched and blind, is final.

**Contracts the tests lock in, worth rewriting as tests first:**

- Crossover and Mid/Side rebuild the input exactly.
- Output length is preserved.
- A disabled stage is an exact bypass.
- The drawn EQ curve equals the applied curve.
- True peak ≤ ceiling on the file on disk, for every format.
- Preview gain equals export gain.
- Album mode keeps relative levels.
- Stems plus the residual null against the mix.
- A finished master gets no recommendation.

**Code worth porting rather than rewriting** (focused, tested, measured):

- `bands.py` (crossover, Mid/Side, width makeup)
- `repair.py` (notch plan, cutoff, de-click, which needs a faster fill)
- `eq.py`
- `edges.py`
- the true-peak limiter and shaper in `mastering.py`
- `perceptual.py` and `artifacts.py`
- the efficacy harness, the corpus check and the bench
- `release.py` and `tags.py`

**Assets:**

- the frozen corpus (`sources/`, `assets/reference/`)
- the listening records
- the reference library
- the learned remover's training pipeline

---

## 13. Review against the research

This section checks the product against the research already done:

- `PRESET_REVIEW.md` (2026-09-04, with sources)
- `BRIGHTNESS-ASSESSMENT.md` §4 and §6
- `GOALS.md`
- `IMPLEMENTATION.md` §6

### 13.1 Does it cover the faults AI music actually has?

`PRESET_REVIEW.md` §1 sorts the causes into five families. `GOALS.md` sets the
list by what users report: pops, crackles, shimmer, sheen.

| Family | What people hear | What the research says fixes it | What Shimmer has | Status |
|---|---|---|---|---|
| **A. Fixed tones, combs, imaging** (upsampling layers) | Whistles, "laser" lines, evenly spaced teeth, chirps that move with the music | Whole-file scan, then static zero-phase notches on both channels; a separate tracker for mirrored (imaged) content | Static notch plan | **Mostly solved.** Tones 96 %, combs 28 %, whistles 17 % (recorded). Nothing handles imaging. |
| **B. Hash, fizz, "shadow"** (codec quantisation loss) | Shimmer, flicker, fizz that rides cymbals and consonants | Per-bin work at a time resolution that can see 10–50 Hz flicker; a noise model tied to the music's own level; learned models | Fine-pass flicker compressor, spectral noise reduction, the shimmer stage; a learned remover (not shipped) | **Unsolved, and the reason the product exists.** Suno Hash preset 12 %; learned remover 17–81 % on modelled hash, too gentle on real renders (recorded). |
| **C. Phase smear** (decoder "swish") | Watery transients, grainy or fluttering reverb tails | Phase-coherence rebuilding in decays; adding a little real reverb to mask the grain | Random-phase resynth, which makes tails noisier, not coherent | **Not addressed.** No artifact model, so never measured. |
| **D. Timbre and mix faults** | Glassy vocals, harsh "sss", crackle on consonants, low-mid build-up, flat dynamics, fake width | Per-bin dynamic resonance control; split-band de-esser with lookahead; de-crackle; dynamic EQ for mud; clean the vocal stem alone | De-harsh (per-bin), fine de-esser, de-click, a static mud bell, Suggested EQ | **Partly.** Centred sibilance −2 %: Mid protection and the transient gate block the de-esser (recorded). Mud is static, not dynamic. No tool for dynamics or width. |
| **E. Bandwidth cutoff** (renders stop at 12–15 kHz) | Dull, no air | Measure the cutoff; never boost above it; bandwidth extension to restore it | Cutoff detection and boost guards | **Detection done.** Restoration is not attempted. Bandwidth extension would mean a learned model. |
| **Pops and crackles** (first on the user list) | Clicks, crackle | De-click / de-crackle with prediction-based fill | `repair.declick` | **Unmeasured.** The artifact models have no click or crackle type (`artifacts.py`), so the harness has never judged the de-clicker. |

**In short:** the one family that is solved (fixed tones) is not the one users
complain about most. The top complaints — shimmer, sheen, pops and crackles —
are unsolved (hash) or unmeasured (clicks).

### 13.2 Too many presets? What is truly needed

**Yes, too many.** The evidence is unusually clear:

- **Few distinct tools.** 19 visible presets use only 12 stage combinations.
  Several are the same stages with different band edges (read).
- **Few winners.** On 26 renders, 4 presets won almost everything and 9 rarely
  or never won (`PRESET_REVIEW.md` §2.9).
- **Few that work.** Against known artifacts, one repair clearly works, three
  presets have a small effect, and two do harm (§8).
- **Named by ear.** "The presets were named by ear" (`PRESET_REVIEW.md` §1).
  Each name promises a separate fix that the engine does not have.

**What is truly needed** is one module per fault family that has a real tool,
not a catalogue of named recipes:

| Module | Industry term | Comes on when | Evidence today |
|---|---|---|---|
| Tone and comb removal | Notch filter | The scan finds fixed tones | Works |
| Click and crackle repair | De-click / de-crackle | Clicks are found | Needs a click model and a measurement |
| Hash reduction | Spectral noise reduction (or a learned remover) | Analyze finds hash | The open problem; one module, whichever method wins |
| Sibilance and harshness | De-esser / dynamic resonance control | Its own detector fires | Needs rebuilding so centred vocals are reachable |
| Mud | Dynamic EQ | Low-mid build-up is measured | Static today |

Each module has one amount control. Analyze decides which modules come on and
shows the number behind each decision. Deep Scrub, Checkerboard Grid,
Sibilance Rattle and the other catalogue names have no role in this layout. A
module is added only when it passes the `GOALS.md` decision rule.

### 13.2a What replaces presets

**Why the old presets go.**

- **They have nothing left to run on.** Each preset was a recipe for the old
  nine-stage cleaner, and that cleaner is retired.
- **They didn't work when measured.** Most removed little of their own fault,
  two did harm, and their names promised fixes the engine didn't have (§8).

**What stays is the one-click idea.** It works in two ways:

1. **Automatic (the default).** Analyze turns on only the tools this song
   needs and shows why, with the number. For example: "Fixed tone at
   17.7 kHz, 12 dB above the music → notch filter on."
2. **By ear.** The same preset browser, with the same "what do you hear"
   groups. Picking a group turns on the tool that fixes it, with one amount
   slider.
Mastering choices (loudness target, tone tilt) stay as they are. A "save my
settings" preset was considered and dropped (2026-09-12): the app already
remembers your last settings.

| What you hear (browser group) | Old presets | New tool | Where it stands |
|---|---|---|---|
| Whistles, fixed tones | Generic, Cymbal Sheen, Laser Whistle, Brittle Air | Notch filter | Proven: 96 % of a fixed tone |
| Comb teeth ("grid") | Checkerboard Grid | Notch filter (comb) | 28 %, against the preset's −1 % |
| Shimmer, hash, fizz | Suno Hash, Broadband Fizz, Presence Haze, Echo Sheen, Cymbal Chatter, Phantom Cymbal, Vocal Glaze + Top, Deep Scrub | Hash reduction | Open. Filled when a method passes; until then Analyze says so plainly. |
| Harsh "s", glassy vocals | Sibilance Rattle, Vocal Glaze, Harsh Veil | De-esser (split-band) | To rebuild; the old one removed −2 % of centred sibilance |
| Clicks, crackle | none (part of Sibilance Rattle) | De-click | To measure first (Step 2) |
| Mud, boxy | Muddy / Boxy | Dynamic EQ | To rebuild as dynamic |
| Dull, no air | Dark Mix Rescue | Mastering tone (tone target, tilt, reference match) | Part of mastering, not cleaning |
| Grainy reverb tails | Reverb Flutter | None yet | No tool; needs research |

Old saved settings are carried over using this table: each old preset name
maps to its new tool.

### 13.3 Audio language

`STYLE.md` says: industry term as the label, plain description underneath, and
never a third-party service's name. The current names break both rules in
many places.

**One rule fixes most of it:**

- Name a **fault** in the words users use: shimmer, sheen, hiss, clicks,
  harshness, mud, dull.
- Name a **tool** in the words a plugin manual uses: notch filter, de-click,
  de-esser, spectral noise reduction, dynamic EQ, multiband compressor,
  limiter.

| Current name | Problem | Industry term |
|---|---|---|
| Suno Hash, and "Suno" in 31 places in presets, help and the page (read) | Names a service | Hash / shimmer reduction |
| Vocal Glaze, Echo Sheen, Phantom Cymbal, Harsh Veil, Presence Haze, Laser Whistle, Checkerboard Grid, Deep Scrub | Invented names | Retire with the catalogue (§13.2) |
| Narrow-tone kill | Invented | Notch filter (adaptive) |
| Shimmer suppressor, Flicker tamer | Invented | Spectral noise reduction; dynamic EQ on flicker |
| De-harsh | Invented | De-esser / dynamic resonance control |
| De-checker | Invented | Comb notch |
| Noise resynth | Invented | Spectral repair (phase) |
| Tone match / tone curve | Fine | Tone target / tonal balance EQ |
| Side width compensation | Fine for code | Stereo width makeup |

### 13.4 Mastering best practice

Sources are the ones recorded in `BRIGHTNESS-ASSESSMENT.md` §6 and
`IMPLEMENTATION.md` §6 unless marked *believed*. By `STYLE.md`, anything
*believed* must be fetched from a source before it drives a design.

| Practice | Source | Shimmer today |
|---|---|---|
| Fix problems before mastering; master last | `PRESET_REVIEW.md` §1 practitioner list; iZotope repair order | ✓ |
| Compare at matched loudness | TD1008 context; `PITFALLS.md` | ✓ in the app's A/B |
| True peak ≤ −1 dBTP at the codec input | AES TD1008 | ✓ (−1.0 / −1.5). Reported peak is from a mono mix. |
| Loudness: −14 LUFS playback on most services; high peak-to-loudness ratio sounds clearer than heavy limiting | AES TD1008; iZotope platform table | ✓ as the default. **But** released references of the same songs are −9.1 to −11.2 LUFS (recorded), so outside a normalising player Shimmer plays 3–5 dB lower. Settled 2026-09-12: the user picks the level from the Loudness target list, and every choice must reach its level cleanly. |
| Tonal balance against genre-matched targets with tolerance ranges | iZotope Tonal Balance docs | One curve for every genre; the tolerance is defined but unused |
| 1–3 genre- and era-matched reference tracks | iZotope reference guide | **Missing** (deferred on the checklist) |
| A compression stage for glue and density before the limiter | *believed* — standard in mastering chains; fetch a source before designing | **Missing, and not proven needed.** The service masters' peak-to-loudness ratio matches Shimmer's (§3), so their extra loudness is mostly gain. |
| Low end in mono; stereo width checked | *believed* | **Missing.** Cleaning narrows the top by about 1 dB (recorded, never investigated). |
| Dither whenever bit depth drops | *believed* | ✓ for WAV/FLAC 16-bit; MP3/M4A are encoded from an undithered 16-bit temp file (read) |
| Album: keep relative levels | TD1008 album normalisation | ✓ (album mode) |
| Leave what is not broken alone | `GOALS.md` anti-goal | ✓ on the evidence branch (no recommendation on finished masters); ✗ on `main` |

**Mastering gaps, in order of what the author hears:**

1. Clean loudness at every Loudness target choice. At −14 LUFS Shimmer
   leaves about 4 dB of headroom unused next to released music, and the
   louder choices lean on the limiter alone.
2. Tone — the service master still wins when levels are matched.
3. Reference-track matching.
4. Genre targets with a deadband.
5. Width and low-end mono.
6. A compression stage, only if the bench shows it is needed.

### 13.5 Textbook recipes, checked against the evidence (2026-09-12)

A common recipe for AI-music repair suggests three tools:

- a fixed notch
- spectral subtraction
- a sidechain de-esser

Its sources are a Reddit thread and a vendor blog. The pages were not opened,
so the settings below are not confirmed there.

| Recipe | Verdict | Why |
|---|---|---|
| **Notch filter** at 3 kHz, Q 30–40 (`scipy.signal.iirnotch`), for "piercing resonances at 2–4 kHz" | **Keep notching; reject the fixed frequency.** | Shimmer finds each tone's frequency per song (4.3 kHz and 16–19.9 kHz on the corpus). Its notch is already narrower — about 47 Hz wide, Q ≈ 64 at 3 kHz — and it is depth-capped at 30 dB and zero-phase. A fixed 3 kHz cut takes presence from songs that have no fault there, and the blind tests *preferred* about +1.6 dB in 2–4 kHz. **Fixed tones at 2–4 kHz do occur.** The app's own tone scan searches from 2 kHz, and on the 30-second test clip used for the UI mockup it found and notched a fixed line at 3.51 kHz (measured, 2026-09-12). An earlier note here said the scan only searched 4–18 kHz. That limit belongs to an old diagnostic file (`testing/diag/source_tones.csv`), not to the app. Below 3 kHz, the notch plan needs a line ≥ 10 dB above its surroundings and present ≥ 90 % of the time. Step 2 counts how often such lines appear across the corpus. Resonances that move with the music need dynamic EQ, not a notch. |
| **Spectral subtraction**: noise profile from a quiet section, floor clipped at 0 | **Rejected for hash.** | Already measured (checklist item 15): 52–61 % of the hash removed for 0.19–0.47 sones of music, against a 0.10 limit. Every guard that cut the cost also cut the effect, down to 2 %. Hash only exists while music plays, so a quiet section holds the wrong profile. A zero floor causes musical noise (watery, twinkling). Presets built on noise reduction measure 5–7 %. |
| **De-esser**: high-pass sidechain at 6.5 kHz, 20 ms window, turns down the whole track | **Keep the tool; change the recipe.** | Make it split-band, so it lowers only the sibilance band and not the whole mix. Cover 4–10 kHz; the sibilance model spans 5–9 kHz, so 6.5 kHz misses part of it. Add lookahead. Run it on the full signal, not scaled down in Mid, and not gated by the transient guard. Today's de-esser removes −2 % of centred sibilance because of where it sits, not how it is designed. |

---

## 14. Gaps in the plan to start over

The plan is: document everything, then rebuild from scratch on the concept
and what was learned. These are the gaps, most important first.

1. **A rebuild does not solve the hash.** It is the product's reason to
   exist, and no method removes enough of it yet (§9). New code with the same
   methods will fail the same blind test. **But the rebuild should not wait
   for it.** Build hash reduction as one replaceable module, ship the rest
   without claiming to fix hash, and fill the slot when a method passes the
   decision rule. If the winner is the learned remover, the promise of "no
   machine learning in the cleanup path" has to change, and the test that
   enforces it has to go.
2. **Loudness — settled 2026-09-12.**
   - **The complaint:** masters sounded quiet in Windows Media Player next to
     Spotify, on the same computer.
   - **The list stays.** The user already picks the level from the Loudness
     target list (Streaming −14, Loud −11, CD / Club −9).
   - **The job is to make every choice reach its level cleanly:** gain into
     the headroom Shimmer leaves unused first, then gentle limiting (§3). A
     compressor is added only if the bench asks for one.
   - **Tone is the other half,** because the service master still wins when
     levels are matched.
3. **"Done" is not defined by listening.** Write the acceptance tests before
   the code:
   - Blind bench rounds against the untouched render and against released
     references, on quiet passages as well as choruses.
   - Headphones as well as speakers.
   - A second listener before any default changes.

   `docs/listening/README.md` on the evidence branch already asks for this.
4. **"From scratch" should mean the product, not the evidence.** Keep:
   - `perceptual.py`, `artifacts.py`
   - the efficacy harness, `corpus_check`, the bench
   - the corpus and the listening records
   - GOALS / PITFALLS / STYLE

   They are the only parts of the project that have been right under test.
   Rebuilding them wastes the most expensive work.
5. **Port the parts that measure well** (§12):
   - crossover and Mid/Side
   - notches and cutoff
   - parametric EQ
   - limiter
   - edge detection
   - release check and tags

   Rewriting them risks new bugs in solved problems.
6. **Settle the cheap open questions first:**
   - Judge the unjudged sets (`quiet-*`, `learned-*`, `tonecheck-*`, round 7).
   - Re-test the current chain after the tone revert.

   That is a few hours of listening, and the answers change the design.
7. **Keep a baseline to beat.** Render the corpus through today's app (tag
   `main` as the reference) so the rebuild is judged blind against it, not
   against memory.
8. **Faults with no measurement:**
   - Pops and crackles: no click model.
   - Phase smear: no model.
   - Stereo narrowing: never investigated.

   Add artifact models before building tools, or the rebuild repeats "named
   by ear".
9. **One render path is a design rule, not a clean-up.** Single, preview,
   batch, album, remix and CLI should call one function with one settings
   object, and preview should be that function on a window. That removes most
   of §5 and every preview-vs-export difference by construction.
10. **Scope — settled 2026-09-12.** Everything ships in the first release
    and works as it does today:
    - Master
    - Remix
    - Batch, with album mode
    - the chain view
    - Settings
    - Help
    - the CLI
11. **The tone target is still one listener's choice** — one speaker setup,
    8-second clips, and a vendor-derived curve that conflicts with
    `GOALS.md`. Do not build it in as a constant; keep it a measured,
    replaceable input.
12. **Compatibility.** The repo is public (AGPL). Existing saved settings,
    remix projects and CLI flags will break. Decide whether that matters and
    say so in the changelog.
13. **The work to keep is on an unmerged branch.** Everything worth keeping
    lives only on `fix/tone-target-and-measurement`, not on `main`:
    - the hearing model, artifact models, harness, corpus check and bench
    - GOALS, PITFALLS and STYLE

    Start the rebuild from that branch, or merge it first. Its two
    sound-path changes (the vendor-median tone target, and the 2 dB boost cap
    in 5–12 kHz) should then be decided again in the rebuild, not carried in
    unexamined.
14. **The goals disagree with each other.** Remix was built to make a render
    "recognisably yours — especially vocals", an earlier stated goal.
    `GOALS.md` lists "not a creative effects box" as an *inferred* anti-goal.
    Only the author can settle which holds, and the answer decides whether
    Remix belongs in the product at all.
    *Settled 2026-09-12:* Remix stays. `GOALS.md` is corrected.
15. **No parity check for ported code.** When a module is ported, run the old
    and new code on the corpus with the same settings and null them. Anything
    that does not null is a change and needs its own reason and measurement.

---

## 15. The rebuild plan

**In plain words.**

- The screens you use today stay the same.
- Everything that processes the sound behind them is built new.
- **Nothing that failed comes along.** These are all left behind:
  - the 19 pre-made presets (replaced by the "What do you hear?" cards; see
    §13.2a)
  - the nine-stage cleaner
  - the old Analyze scoring
  - the old tone targets
  - the six copies of the processing steps
- A few pieces were tested and proven to work. They are copied in, and they
  must pass the same tests as new code or they are not used. For example:
  - the notch filter that removes 96 % of fixed tones
  - the limiter that keeps peaks under the ceiling
- Every new piece proves itself before it goes in. It must:
  1. remove the fault it is for
  2. not take music with it
  3. sound better in a blind listening test
- §17 lists each past failure and the check that keeps it out.

**Words used in this plan.**

- **Baseline:** today's app, frozen, kept only so the new one can be compared
  with it.
- **Port:** copy a piece that was *proven to work* into the new engine, fix
  its known bugs, and test it again.
- **Null test:** play the old and new output against each other with one
  flipped upside down. If they cancel to silence, nothing changed by
  accident.
- **Seam:** the connection between the screens and the engine (the `/api`
  routes).
- **Bench:** the blind listening page, where two versions are compared at
  the same loudness without knowing which is which.

**Scope (decided 2026-09-12): keep the current UX/UI; rebuild the engine.**

- **The engine is everything behind the `/api` routes:** upload and
  sessions, Analyze, cleaning, mastering, export, jobs and progress.
- **The frontend stays.** Its layout, look and workflow are kept. Only the
  parts that mirror engine ideas are re-wired.

**Where the two sides meet.** The browser talks to the engine only through
the HTTP routes. That is the seam. Wherever an idea survives, the new engine
keeps the route path and the response fields the UI reads. Some ideas are
retired:

- the 19 presets
- preset strength
- the routine second pass
- the 15 stage sliders

Where that happens, the route changes and the matching panel is re-wired in
the same place with the same look. Every change a user can see goes to the
author for sign-off before it is built.

**What "rebuild" means for the code.**

- **New:** design, orchestration, settings and modules.
- **Ported:** about ten pieces that tested well are copied in (§16.1). Each
  one:
  1. has its known bugs fixed
  2. passes the new contract tests
  3. is null-tested against the baseline, so nothing changes by accident

  A ported piece that fails any of these is rewritten instead.
- **Never copied:** nothing listed under "Retire" in §16 — the parts that
  measured badly or never got measured.
- **Not part of the engine:** the measurement tools. They stay as the
  instruments that judge it.

**Where the work happens.** See §18:

- a separate branch
- a separate folder and port
- final file names from day one
- a 2.0.0 release only when every check passes

Nothing reaches existing users before that. The baseline is today's `main`
(`c1d18e0`), run from its own folder.

Each step ends in something that can be checked. A step starts only when the
one before it is done.

### Step 1 — Decide (no code) — done 2026-09-12

1. **Goals.** `GOALS.md` is corrected in the author's words:
   - Remix stays.
   - Loudness is the user's choice from the Loudness target list, reached
     cleanly.
2. **Loudness.** The existing list stays. Every choice must reach its level
   cleanly and hold up next to released music in an ordinary player (§14
   item 2).
3. **Scope.** Everything ships, working as it does today (§14 item 10).
4. **Branch.** The `rebuild` branch and its folder exist (§18.1).

*Done when:* `GOALS.md` states these in the author's words. ✓

### Step 2 — Settle the evidence (listening and measurement)

1. Render the corpus through the baseline.
2. On headphones, judge the sets never judged: `quiet-*`, `learned-*`,
   `tonecheck-*` and round 7.
3. Check that the louder Loudness target choices are clean. Play the same
   baseline master at Streaming, Loud and CD / Club, all at one level, and
   blind: which sounds cleanest?

   This replaces a planned round on level versus tone. The service masters
   already won 16 of 16 at matched level, so tone is known to matter. What
   isn't known is whether the louder choices damage the sound.
4. Count how often fixed tones at 2–4 kHz appear across the corpus. The
   app's scan already searches from 2 kHz; the test clip had one at
   3.51 kHz (§13.5).
5. Add artifact models for clicks and crackle (and phase smear, if it can be
   modelled), then measure today's de-clicker.

*Done when:* each result is written into the checklist, with its limits.

### Step 3 — Contracts and the route map — in progress (started 2026-09-12)

Contract tests are written in `tests/core/` and `tests/api/`. They are marked
"expected to fail" until `shimmer.core` and `shimmer.api` exist, so the rest of
the suite stays green. The route map goes in `docs/API.md`.

1. Write the contract tests (§12) against the new interface, before the
   engine exists.
2. List every route the UI calls, with the fields it reads (start from
   §16.3). Mark each one: keep as is, keep the path with new fields, or
   retire.
3. Move the rules the UI copies into one server route that the UI reads,
   so they cannot drift again:
   - LUFS targets
   - formats and ceilings
   - EQ limits
   - the module list

*Done when:* the tests run (and fail), and the route map is signed off.

### Step 4 — The new core

1. Build these, each once:
   - one settings object
   - `render(source, settings, window=None)`
   - one export stage
   - one job runner, with cancel

   The live preview is `render` on a window, so it matches the export by
   construction.
2. Port the measured-good modules (§16.1), fixing on the way:
   - one biquad design for every EQ-type filter (ends the 2× shelf bug)
   - a per-channel true-peak meter
   - a faster de-click fill
   - OGG export
   - MP3/M4A dither
   - "Show in folder"
3. Null each port against the baseline (§14 item 15).
4. Move the Master tab's routes to the new core one at a time, and check the
   UI after each.

*Done when:* the contract tests pass, the ports null, and the Master tab runs
end to end on the new core.

### Step 5 — Mastering (the main complaint)

1. Fetch the sources first (the `STYLE.md` rule), then build:
   - every Loudness target choice reaching its level cleanly: gain into
     unused headroom first, then gentle limiting, as measured
   - **Proposed 2026-09-12, needs a mockup and sign-off.** New names for
     the Loudness target choices, each with a plain sub-label:

     | Label | Sub-label | Level |
     |---|---|---|
     | Commercial (default) | As loud as most released songs | -9 LUFS |
     | Balanced | A little quieter, with more punch left in | -11 LUFS |
     | Streaming standard | The level streaming apps play songs at; sounds quiet in other players | -14 LUFS |

     The choices would show as three cards, not a dropdown. The "distortion
     risk" warning would be dropped: the author hears no damage at -9
     (checklist 18).

     Why: the goal is to master at the level most studios deliver. A
     314,876-track study puts the median at -9.5 LUFS (pop -9.5, electronic
     -9.3). Every earlier export sat at -14 because "Streaming" read as the
     right choice for a streaming release.
   - the tone target as a replaceable input, with a deadband
   - reference-track matching
   - genre targets
   - low-end mono and width checks
   - a compressor, only if the bench asks for one
2. Judge it on the bench against the service masters, released references
   and the baseline, on headphones and speakers.

*Done when:*

- it beats the baseline blind
- it does not lose to released references at matched loudness
- a Loud master played in Windows Media Player holds up next to released
  music on Spotify, on the same computer

### Step 6 — Cleaning modules, one at a time

In this order:

1. Notch filter (ported; it already reaches down to 2 kHz)
2. De-click
3. De-esser (split-band, 4–10 kHz, lookahead, full signal, not gated by the
   transient guard)
4. Dynamic EQ for mud
5. The hash reduction slot

Each module ships only when it passes the `GOALS.md` decision rule:

- It removes its fault on ground truth.
- Its cost in sones is acceptable.
- It wins or ties in a blind round.

A module that fails stays out. As each module lands, its UI controls are
re-wired in the existing panels (§16.2), with sign-off.

### Step 7 — Finish and switch over

1. Move Batch and album mode, then the Remix render, onto `render`. Remix
   keeps working as it does today. Its known bugs (the doubler drift and the
   silent formant tail) are fixed.
2. Rewrite the CLI as a thin layer over `render`.
3. Migrate old saved settings: old preset names map to new module settings.
4. Delete the retired modules and their tests (§16).
5. Rewrite the README, `docs/README.md`, `FEATURES.md` and the help text.
   Write a new architecture doc for the new engine.
6. List the breaking changes in the changelog, add update instructions to
   the README, then release 2.0.0 (§18.4).

---

## 16. What happens to each file

Fates, used in every table below:

- **Keep** — unchanged.
- **Port** — copied into `shimmer/core/` with its known bugs fixed, then
  nulled against the baseline.
- **Rewrite** — new code for the same job.
- **Retire** — the job goes away, and the file is deleted after the switch.
- **Instrument** — kept as a measuring tool, outside the engine.
- **Keep (Remix)** — Remix code that stays and works the same. Only its
  render moves to the new engine, and its known bugs are fixed.

### 16.1 Engine (Python, `shimmer/`)

| File | Lines | Fate | Notes |
|---|---:|---|---|
| `__init__.py`, `__main__.py`, `_winfix.py` | 60 | Keep | |
| `settings_store.py` | 71 | Keep | Add a migration for old saved settings |
| `bands.py` | 257 | Port | Crossover, Mid/Side, width makeup |
| `eq.py` | 223 | Port | Its biquad design becomes the only one |
| `edges.py` | 405 | Port | |
| `repair.py` | 471 | Port | Notch plan, cutoff, de-click (faster fill) |
| `tags.py` | 473 | Port | |
| `release.py` | 344 | Port | Uses the shared per-channel meter |
| `report.py` | 174 | Port | Shares one spectrum function |
| `dsp.py` | 224 | Port, in part | The shelf, bell and high-pass designs are replaced (2× bug) |
| `mastering.py` | 617 | Port, in part | Port the limiter, shaper, loudness meter and ceilings. Rewrite the gain policy and tone target. |
| `audio_io.py` | 481 | Rewrite | Keep the ffmpeg handling; fix OGG and MP3 dither; drop the legacy full-mix path |
| `trim_silence.py` | 90 | Rewrite | Becomes part of the export stage |
| `pipeline.py` | 321 | Rewrite | Becomes `render()` |
| `params.py` | 436 | Rewrite | Becomes the new settings object |
| `server.py` | 2,392 | Rewrite | Thin routes over the core; same paths where ideas survive |
| `jobs.py`, `preview_store.py` | 220 | Rewrite | One job runner with cancel; sessions reused by Analyze and export |
| `chain.py` | 560 | Rewrite | Generated from the module list, with numbers from real constants |
| `detect.py` | 1,409 | Rewrite | Analyze becomes each module's own detector plus the net-benefit score. Port `scan_fixed_lines`. |
| `autoeq.py` | 782 | Rewrite | One tone planner replaces the tone curve and Suggested EQ, and still returns the moves the Suggested EQ card shows |
| `cli.py` | 508 | Rewrite | Step 7 |
| `engine.py` | 1,231 | Retire | The nine stages are replaced by modules |
| `finepass.py` | 241 | Retire | The de-esser is rebuilt; the flicker compressor returns only if it earns the hash slot |
| `presets.py` | 1,456 | Retire | Leaves behind a small table that maps old names for migration |
| `probe.py` | 274 | Retire | Dead |
| `stems.py`, `stems_runner.py` | 1,241 | Keep (Remix) | Separation stays as it is |
| `stem_effects.py`, `projects_store.py` | 420 | Keep (Remix) | Works the same; the doubler drift and the silent formant tail are fixed |
| `perceptual.py`, `artifacts.py` (evidence branch) | — | Instrument | The hearing model and artifact models |
| `budget.py`, `references.py`, `abtest.py` (evidence branch) | — | Instrument | Budget stays unwired; dev pages stay |

About 5,300 lines are retired, 6,800 rewritten, 3,700 ported, and 1,700
kept for Remix (read, from the line counts in §1).

### 16.2 Frontend (`static/`)

| File | Fate | What changes |
|---|---|---|
| `index.html`, `css/*.css` | Keep | Layout and look stay. Card text changes only where the engine idea changes. |
| `visualizer.js`, `trim.js`, `progress-chain.js`, `recents.js`, `palette.js`, `main.js`, `master-view.js`, `settings.js`, `report.js` | Keep | |
| `eq.js` | Keep | Limits come from the server instead of copies |
| `api.js` | Keep | Endpoints updated to the route map |
| `preset.js`, `preset-browser.js` | Re-wire | Same browser, same "what do you hear" groups; each item turns on the tool that fixes it (§13.2a). |
| `controls.js` | Re-wire | The 15 stage sliders become one amount per module |
| `chain.js` | Re-wire | Reads the new chain description |
| `batch.js` | Re-wire | Preset choice becomes module choice |
| `help.js` | Re-wire | The preset quiz and control reference are rewritten |
| `single.js` | Re-wire, in part | Four sections change: the Advanced drawer (lines ~300–429), the two-pass flow (~1186–1521, retired if the routine second pass goes), Tone and Suggested EQ (~1523–1979), and Analyze results (~2065–2334). Its copies of engine rules move to the server. The rest stays. |
| `remix.js` | Keep (Remix) | Works the same; its render and export use the new engine |

### 16.3 Routes the UI calls (the seam)

| Route | Fate |
|---|---|
| `/api/upload`, `DELETE /api/upload/{sid}`, `/api/envelope/{sid}` | Keep path and fields |
| `/api/preview` | Keep path and the binary format; now `render` on a window |
| `/api/process`, `/api/progress/{id}`, `/api/metrics/{id}`, `/api/result/{id}` | Keep paths; the export reuses the session instead of a new upload |
| `/api/settings`, `/api/browse-folder`, `/api/reveal` | Keep (fix `reveal`) |
| `/api/batch` | Keep path; move to the job runner |
| `/api/suggest`, `/api/tone`, `/api/chain` | Keep paths; new fields (modules, not presets) |
| `/api/presets` | Replaced by a module list plus the engine rules |
| `/api/stems/*`, `/api/remix/*`, `/api/project/{digest}` (POST) | Keep; the remix render moves to `render` |
| `/api/analyze`, `/api/projects`, `GET /api/project/{digest}`, `/api/stems/status/{sid}` | Retire (no caller) |

### 16.4 Tests

| Fate | Files |
|---|---|
| Keep | `test_eq`, `test_edges`, `test_repair`, `test_tags`, `test_release_check`, `test_delivery_format`, `test_stems`; evidence-branch `test_perceptual`, `test_perceptual_golden`, `test_efficacy`, `test_references_gate`, `test_abtest_guards`, `test_budget` |
| Adapt to the new core | `test_master_loudness`, `test_batch_album`, `test_preview_match`, `test_chain`, `test_pipeline_stages`, `test_auto_save`, `test_remix_master`, `test_report` |
| Retire with their modules | `test_finepass`, `test_autoeq`, `test_detect`, and the engine parts of `test_shimmer`. Its crossover, Mid/Side and limiter contracts move to the new contract tests first. |

### 16.5 Docs and other files

| Fate | Files |
|---|---|
| Keep | `GOALS.md`, `PITFALLS.md`, `STYLE.md`, `HANDOFF-CHECKLIST.md`, `BRIGHTNESS-ASSESSMENT.md`, `PRESET_REVIEW.md`, `STEMS_MODELS.md`, `DEPLOYMENT.md`, the listening records, the evidence scripts, the launchers |
| Rewrite at the end | `README.md`, `docs/README.md`, `FEATURES.md`, and this file (it becomes the record of the old engine) |
| Archive | `PLAN.md`, `docs/refactor/*` — history, not instructions |
| Untouched | Local working files (`diag_*.py`, `testing/`, `sources/`, `hash_data*`); they are gitignored |

---

## 17. Past failures, and what keeps each one out

Each row is something that went wrong in the last two months. The right
column is the rule or check in the rebuild that blocks it. A check marked
*test* runs automatically on every change. One marked *bench* is a blind
listening round.

| # | What went wrong | Why | What blocks it in the rebuild |
|---|---|---|---|
| 1 | Masters sounded too quiet next to released music | −14 LUFS left about 4 dB of headroom unused; the louder choices lean on the limiter alone | The Loudness target list stays, and every choice must reach its level cleanly. *Bench:* level-matched rounds against the service masters, and a Loud master in Windows Media Player next to released music on Spotify. |
| 2 | Masters sounded dull | Cleaning took presence; preset filters cut twice as hard as written; wrong tone targets | One filter design for every EQ-type filter. *Test:* for every filter, the dB you set is the dB you get. *Test:* a finished master comes out essentially unchanged. |
| 3 | Presets that did nothing, or took music | 19 presets named by ear, never measured against the fault | No module without three proofs: removes its fault on known material, cost in sones under the limit, wins or ties on the *bench* (the `GOALS.md` rule). |
| 4 | Analyze wanted to clean finished commercial masters | Its score (`purity`) could not fail, so it always looked right | *Test:* a finished master gets no recommendation. Every new measure is tried first on material where the right answer is known. |
| 5 | The tone target changed four times | Each version was believed, not tested | The tone target is one replaceable input, chosen on the *bench*, from music outside the tool. |
| 6 | Preview did not match export (13 differences) | Preview and export were separate code | One `render`; preview is `render` on a window. *Test:* preview and export of the same section match. |
| 7 | The same steps written six times, drifting apart | Each tab grew its own copy | One `render`, one export stage, one job runner. *Test:* server routes may call only the core, never DSP code directly. |
| 8 | Remix export skipped tags, EQ and the release check | Its own export path | Every tab uses the one export stage. |
| 9 | Settings copied into the browser drifted from the server | Rules typed twice | The browser reads the rules from one server route. |
| 10 | Features stacked on features: five tone layers, six tone fixers, two flicker tamers | New work was added beside old work, not in place of it | One job, one place. A new module replaces the old one; it never sits beside it. §11 is the list to keep empty. |
| 11 | Centre protection blocked faults in the centre | One rule applied to every stage | Each module's placement is chosen and measured on its own. Fixed tones and clicks get no centre protection. |
| 12 | Claims in comments and docs that were not true | Numbers stated from memory; docs not updated | Sources fetched before design (`STYLE.md`). The chain view is built from the code. Docs are rewritten at the end, with each claim marked measured, cited or read. |
| 13 | Bugs in export formats (OGG fails, MP3 not dithered, batch can overwrite sources) | No test per format | *Test:* write and re-read every format. Refuse an output folder equal to the input folder. |
| 14 | Big changes judged by measurement alone | Measurement was wrong in both directions | Blind listening is final (`GOALS.md` rule 4), with headphones as well as speakers, and a second listener before any default changes. |
| 15 | Work planned but never finished, or dropped quietly | Checklist items removed when they slowed things down | The checklist stays append-only. Each step in §15 has a "done when" line, and the next step does not start until it is met. |

---

## 18. Running the rebuild without touching what users have

**In plain words.**

- **Your users can't get the rebuild by accident.** They get Shimmer from
  GitHub only, by pulling `main` or downloading a release. Either way they
  only get what is on `main`. So the rebuild happens on its own branch and
  reaches nobody until it is finished, checked, and merged.
- **Your own Shimmer keeps working.** The rebuild runs from a separate
  folder, on a separate port.
- **No file is copied and renamed later.** Every new file gets its final
  name on day one.

### 18.1 Three layers of safety

| Layer | How | Who it protects |
|---|---|---|
| `main` | Nothing from the rebuild lands on `main` until it is finished and every §15 check passes. | Everyone who pulls from GitHub |
| One branch | All rebuild work goes on one branch, `rebuild`. Pushing it to GitHub backs it up. It is not the default branch, so nobody gets it by accident. | Everyone |
| A second folder | The branch is checked out in its own folder (a git worktree) and runs on port 7870. Your everyday Shimmer keeps its own folder and port 7860, so you can use both side by side. | You, day to day |

### 18.2 Names: final from day one

- **No version words in names.** No "v2", "new", "old", "test" or dates in
  any file, folder, route or setting name.
- **Nothing is copied and renamed.** `static/index.html` is edited in place
  on the branch. The mockup was a throwaway file (`static/tmp/`, ignored by
  git) and is not part of the build.
- **Route paths stay the same** (`/api/upload`, `/api/preview`, …). New code
  takes over a path; it never sits at a second address.
- **`shimmer.server:app` stays the entry point.** `start.bat` and `start.sh`
  on every user's machine start the app by that name.
- **File-name style:**
  - Python files use lowercase `snake_case` (PEP 8).
  - JS and CSS files use lowercase `kebab-case`, like the files already in
    `static/`.
- **The one place a version belongs is the release number** — 1.1.1 today,
  **2.0.0** for the rebuild. The changelog already follows Semantic
  Versioning, where a new first number tells users a big change is coming.

### 18.3 New structure, next to the old files

```
shimmer/
  server.py              stays the entry point; hands each route group to api/
  core/                  the engine: sound and measurement. No web code.
    __init__.py          public: render, analyze, export, Settings, catalog
    settings.py          one Settings object, with defaults and limits
    catalog.py           the "What do you hear?" cards: fault, label, icon, tool, band
    render.py            render(source, settings, window=None)
    export.py            format, dither, tags, release check, file name
    audio/
      io.py              decode, encode, resample
      filters.py         the one biquad design every EQ-type filter uses
      meters.py          LUFS, per-channel true peak, spectrum — one of each
    analyze/             measures only; never changes audio
      findings.py        what Analyze reports, card by card
      tones.py           fixed-tone and bandwidth-cutoff scan
      edges.py           head and tail glitches
    repair/              one file per tool
      notch.py
      declick.py
      deesser.py
      dynamic_eq.py
      hash.py            the open slot
    master/
      loudness.py        gain to the chosen Loudness target
      tone.py            tone target
      limiter.py         peak shaper and true-peak limiter
  api/                   the web layer. Calls core only.
    sessions.py          upload, envelope
    analyze.py           suggest, tone, catalog
    render.py            preview, process, result
    jobs.py              one job runner: progress stream, cancel
    settings.py          saved settings, with migration from 1.x
  (the existing modules stay where they are until Step 7)
static/
  index.html             the same file, edited in place
  js/fault-picker.js     the "What do you hear?" card
  css/fault-picker.css
tests/
  core/                  contract tests for the engine
  api/                   route tests
```

**Rules for this layout:**

- **Each layer talks to one other.** `core` knows nothing about the web.
  `api` calls only `core`'s public functions. `static` talks only to
  `/api`. A test enforces the first two (§17 row 7).
- **Old modules stay untouched until Step 7.** Only two existing files are
  edited along the way:
  - `server.py`, to hand each route group to `api/`
  - `static/index.html`, to put the new cards where the old ones were
- **Routes move in groups that share state,** so the app works after every
  commit:
  1. sessions (upload, envelope)
  2. Analyze (suggest, tone, catalog)
  3. render and export (preview, process, progress, result)
  4. batch
  5. remix render

### 18.4 Releasing to your users — don't break anything

1. **Until it's done,** nothing changes for users. They keep getting what is
   on `main` today.
2. **On release day,** `rebuild` is merged into `main` as version 2.0.0, and
   the changelog says in plain words what changed for them.
3. **Nothing breaks when they update:**
   - **Their saved settings carry over.** Settings live in
     `%APPDATA%\Shimmer` (`~/.config/shimmer` on Mac and Linux), outside
     the install folder, and old preset names map to the new cards
     (§13.2a).
   - **They start it the same way.** `start.bat` and `start.sh` stay the
     same, and so does the entry point they call.
   - **The README says what to expect.** Today it only covers the first
     install. The first start after updating may take longer while the
     Python environment updates.
