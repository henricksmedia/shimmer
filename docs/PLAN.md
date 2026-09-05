# Shimmer plan: presets, stems, signal chain

Status: proposal for discussion, written 2026-09-04. Nothing in this
plan has been executed. It follows from
[PRESET_REVIEW.md](PRESET_REVIEW.md) and from measurements taken on
Jeremy's Suno corpus the same day.

---

## 0. Ground rules

These are non-negotiable and every task below is written to respect
them.

1. **Every sound change sits at its proper stage.** The chain order
   exists to avoid damaging the song. New stages are placed by
   restoration order: deterministic repairs first (edits, clicks, fixed
   lines), then adaptive cleaning (temporal before spectral), then
   tonal moves, then loudness, then export. Nothing adaptive runs before
   the deterministic repairs, so detectors always see the cleanest
   possible signal.
2. **Analysis measures, never alters.** Analyze and the stem quality
   report only read the signal and feed existing inputs (preset,
   strength, notch list, cutoff).
3. **Master once, at the end.** Any multi-pass path (preset chains,
   per-stem cleaning) applies the tone curve before the first pass and
   mastering after the last.
4. **Definition of done for every phase:** tests pass, the verified
   corpus report is re-run and compared, Jeremy signs off by ear at
   matched loudness, and the Signal Chain view and docs are updated in
   the same change.

---

## 1. Where we are today

### 1a. Is the Signal Chain view accurate?

The lane order matches the code: tone curve → crossover → M/S →
expander → denoise → de-resonator → shimmer → de-harsh → flicker →
de-checker → tone kill → resynth → width comp → recombine → post
filters → EQ → HP → LUFS gain → soft clip → limiter. That part is
right.

What is stale or missing:

| Item | Status |
|---|---|
| Trim (head/tail cut) | Missing. It runs first, before the tone curve. |
| Pre-analyze mask and Iterations | Missing. Deep Scrub runs a full-file mask and two passes. |
| Preserve volume + clip protect (mastering off) | Missing, between EQ and export. |
| Export stage (silence trim, format ceiling, dither) | Missing; only the ceiling appears, on the limiter badge. |
| Crossover badge "4500 Hz" and the chip "low band < 4.5 kHz bypasses cleaning entirely" | Stale. Presets set 300, 2500, 3500, 4000 or 4500 Hz. Vocal Glaze sends everything above 300 Hz through the engine. |
| M/S badge "Mid 0.2×" | Stale. Deep Scrub uses 0.45×, the Vocal Glaze pair 0.5×. |
| Denoise badge "1.5–16 kHz", Flicker "4.5–12 kHz" | Preset-dependent; shown as fixed. |
| "Gates" drawn as a module in the lane | Misleading. The gates ride alongside every stage; they are not a stop on the line. |

Verdict: accurate in order, stale in numbers, incomplete at both ends.
Every phase below changes it, so Workstream C makes it data-driven
rather than hand-maintained.

### 1b. Does Remix cover all stems?

No. Remix runs the base `htdemucs` model: four stems (vocals, drums,
bass, other), no fine-tuned variant, no ensemble, no sub-stems. On the
standard benchmark that model averages about 9 dB SDR across the four
stems; the best open ensembles average 13.7 dB, and single Roformer
models reach 12.3 dB on vocals. That is a 4 dB gap, which is audible
as bleed and watery edges.

Measured on two cached stem sets from earlier Remix sessions: the
vocal stem came out free of steady tones, the generator's fixed lines
landed in drums and other, and the bass stem carried sustained peaks
at 4–7 kHz where a bass stem should hold almost nothing. The separator
is dumping generator residue into whichever stem is least protected.

### 1c. Suno's stems versus what we would build

Suno rebuilt stems around *regeneration*: the model re-synthesises each
part from its internal representation instead of splitting the mix.
Up to 12 stems in Auto Split, close to 100 instrument choices in
Advanced Split, cloud-only, paid tiers, no API. The stems are clean and
spill-free because they are new renders; they are not faithful to the
mix, they do not sum back to it, they carry the generator's own
artifacts, and Suno itself lists acoustic guitar, piano, strings and
backing vocals as weak.

What Shimmer can build is the opposite product: **faithful, offline,
artifact-aware separation** where the stems plus a residual sum back to
the mix exactly, the residual is where the generator's junk goes, and
every stem's bleed is measured and shown. "Better than 125 % of the
tools" is then a number, not a slogan: match the best open ensemble on
real music (13.7 dB average) and beat it on an AI-music benchmark that
does not exist yet and which we would create (Section 4).

---

## 2. Target signal chain

Proposed order. New stages are marked NEW; each has a placement note.
This is the part that needs sign-off before anything is built.

```
Input
 → Trim (head/tail cut)                              existing, first
 → De-click / De-crackle                              NEW  ①
 → Static repair: fingerprint notches                 NEW  ②
 → Tone curve (when mastering is on)                  existing
 → Crossover (preset-dependent, shown live)           existing
     ├─ low band: bypass
     └─ high band → M/S  (Mid × preset scale, Side × 1)
          → Fine-grid dynamic pass, 1024/256          NEW  ③
              flicker tamer (moved here)
              spectral de-esser (new, own detector)
              chatter-rate tamer (new, Phase 6)
          → Coarse-grid spectral pass, 4096/1024      existing registry
              expander → denoise → de-resonator (per-bin) → shimmer
              → de-harsh (per-bin) → de-checker → tone kill
              → phase-coherence repair (new, Phase 6) → resynth
              (× iterations, with pre-analyze mask when set)
 → Side width comp → Recombine + wet/dry → Post filters + fades
 → Parametric EQ
 → Preserve volume + clip protect (mastering off)     existing, now shown
 → Mastering: HP/DC → LUFS gain → soft clip → true-peak limiter
 → Export: silence trim → format ceiling → dither     existing, now shown
```

Stem-aware path (Remix, and optionally Master):

```
Input → Trim → De-click → Static repair
 → Separation (Workstream B)
     → per stem: crossover / M/S per stem preset
                 (Mid 1.0 on stems with no vocal)
                 → fine pass → coarse pass
 → Sum stems (+ residual policy) → EQ → Mastering → Export
```

Placement notes:

- ① **De-click first.** Impulsive noise is the first step in every
  restoration order (clicks, then crackle, then hum, then noise),
  because every adaptive detector downstream reads a click as a
  transient and backs off. Time-domain, full band, both channels.
- ② **Static repair before the tone curve and before the crossover.**
  The generator's fixed lines and combs are deterministic and known
  from the whole-file scan. Removing them first means the crossover,
  the noise-floor trackers, the separator and the verification all see
  a cleaner signal, and the notches apply to L and R at full depth with
  no Mid protection, which a fixed 17.7 kHz line does not deserve. Zero
  phase, narrow (about two bins), depth equal to the measured excess.
- ③ **Fine pass before the coarse pass.** Flicker, sibilant bursts and
  chatter are temporal artifacts; a 23 ms window catches them without
  smearing. The coarse pass then handles spectral residue (floor,
  peaks, combs, tones) on a steadier signal. This moves FlickerTamer
  and the sibilance tool earlier than they sit today, and gives the
  fine pass its own transient detector so the de-esser is no longer
  gated off by the coarse hold.
- Alternative considered: run everything on one 2048/512 grid. It
  halves the problem, does not solve it, and costs the tone killer
  frequency resolution. Rejected.

---

## 3. Workstream A: presets and engine

### A1. Static repair (fingerprint notches)  — chain stage ②

- Extend the whole-file scan in `detect.py` with a comb fit: peak
  spacing from the long-term residual autocorrelation, plus the
  individual line list it already produces.
- New stage `static_repair` applied to the full-band L/R signal:
  cascaded zero-phase notches (`sosfiltfilt`), bandwidth about 25 Hz,
  depth = measured excess capped at 30 dB, both channels. Lines are
  eligible only when their 25th-percentile excess over the whole file
  is at least 6 dB (persistence rules out musical partials); below
  3 kHz only with duty ≥ 0.9 and excess ≥ 10 dB.
- Analyze lists the lines it will notch; the user can untick any.
- Preset impact: Generic, Cymbal Sheen, Laser Whistle, Brittle Air and
  Checkerboard Grid gain the stage; `tone_kill` stays as the adaptive
  backstop at lower strength.
- Acceptance: corpus tone removal ≥ 80 % on centered lines (22 %
  today); null test on a synthetic clean track; nothing changes below
  3 kHz unless a qualifying line is there.

### A2. De-click / de-crackle  — chain stage ①

- Detector: linear-prediction residual with an adaptive threshold
  (clicks) plus a density rule (crackle = dense micro-clicks), scoped
  to the high band so bass transients cannot trigger it. Repair by AR
  interpolation over the flagged samples.
- Analyze adds evidence: click rate per second, concentrated on vocal
  and cymbal frames.
- Preset impact: Sibilance Rattle gains it; a new "Crackle" entry
  point in the catalog.
- Acceptance: synthetic click injection detected ≥ 95 %; false
  positives on clean drums ≤ 1 per minute; listening on v5.5 renders.

### A3. Fine-grid dynamic pass  — chain stage ③

- 1024/256 STFT per M/S channel, overlap-added back before the coarse
  pass. Stages: FlickerTamer (moved), spectral de-esser (per-bin
  excess over the smoothed envelope during sibilant frames; sibilance
  detector = 4–10 kHz vs 1–4 kHz ratio plus flatness), fine transient
  detector for its own hold.
- Acceptance: synthetic 20–40 Hz flicker reduced ≥ 10 dB (about 0
  today); sibilance burst test; drum attack energy loss < 0.5 dB.

### A4. Per-bin DeHarsh and dense-band DeRes

- DeHarsh keeps its band-level trigger but applies gain per bin
  against the reference-scaled envelope, so a glazed overtone is cut
  and its neighbour is not.
- DeRes on dense bands: persistence-only detection, replacing the
  density gate the docstrings admit fails there.
- Acceptance: vocal glaze test cuts the overtone with < 1 dB broadband
  loss across 2–8 kHz; corpus purity rises.

### A5. Cutoff detection and bandwidth-aware shelves

- Analyze finds where the long-term spectrum drops more than 30 dB
  below trend ("top end ends at 13.2 kHz") and reports it.
- Dark Mix Rescue, Brittle Air and the tone curve cap boosts below the
  cutoff; the band above it is treated as noise-only.

### A6. Catalog consolidation and preset chains

- Families that map to real tools: Lines & Combs; Hash & Fizz;
  Sibilance & Crackle; Wash & Tails; Vocal Glaze; Balance. Existing
  names stay as entry points so nothing the user knows disappears.
- Preset chain in one job: an ordered list of (preset, strength), tone
  curve before the first, mastering after the last. Analyze's second
  pass becomes one click; Batch applies chains per file.
- Muddy / Boxy gets a dynamic low-mid bell in the post-filter slot
  (same place as today's static bell; the engine never sees the low
  band).
- Acceptance: corpus win distribution no longer dominated by four
  presets; chain output equals two sequential runs bit-for-bit.

### A7. Analyze follow-through

- Evidence for clicks and cutoff; family-level scoring; chains
  verified the same way single presets are today.

---

## 4. Workstream B: stems

### B1. Engine

- Replace the bare `htdemucs` call in `stems.py` with a model-zoo
  runner in the existing side venv: `audio-separator[gpu]` (Roformer,
  MDX, Demucs, ensembles, CUDA on Windows) or ZFTurbo's inference
  scripts. Cache by content hash *and* model set.
- Tiers: Fast = `htdemucs_ft`; Best = SCNet XL IHF + BS-RoFormer 4-stem
  ensemble with a Mel-RoFormer vocal model. Check each checkpoint's
  licence before shipping (see [STEMS_MODELS.md](STEMS_MODELS.md)).
- Acceptance (corrected 2026-09-05): the 13.7 dB figure quoted before is
  MVSep's *proprietary* ensemble and is not downloadable. Open weights
  top out near 10 dB on the 4-stem average and 11–13 dB on vocals. Best
  tier target on MUSDB18-HQ test: 4-stem average ≥ 10.0 dB (about 9.2
  today), vocals ≥ 11.0 dB (8.2 today), drums ≥ 11.5, other ≥ 7.5.

### B2. Stem tree (12 faithful stems)

- vocals → lead / backing (karaoke model), optional de-reverb
- drums → kick / snare / toms / hats / cymbals (DrumSep)
- bass
- other → guitar, piano, remainder (keys, synth, strings, wind)
- **residual = mix − Σ stems**, always kept, so the sum is exact.

### B3. Artifact-aware separation

- Trim, De-click and Static repair run *before* separation, so the
  separator sees a cleaner mix and fixed lines stop landing in the bass
  stem.
- After separation, measure artifact residue per stem (same evidence
  scan as Analyze) and report it; the residual stem shows how much
  generator junk it holds, and the user chooses to keep, attenuate or
  drop it.

### B4. Quality report and an AI-music benchmark

- Per-stem bleed and fullness metrics, a null-test badge (sum exact),
  and time taken.
- Benchmark set: MUSDB18-HQ stems mixed, then passed through a neural
  codec (DAC or Encodec) so the mix carries real generator artifacts
  while the ground-truth stems stay known. This is the only way to
  measure "better on AI music" with numbers. Targets: ≥ 10 dB average
  on real music with open weights; ≥ +1.5 dB over the best single open
  model on the codec set, from the artifact-aware pipeline (static
  notches before the split, residual stem) plus the ensemble.
- Own models (Decision 3): the same codec-degraded set doubles as the
  specialisation training set. Data sources must be cleared for the
  use (MUSDB18-HQ and MoisesDB are research licences; check before
  training anything we ship). Suno's regenerated stems are *not*
  ground truth (they do not sum to the mix) and are not used as
  targets. Compute: one RTX 4070 (12 GB) fine-tunes or trains a compact
  Roformer in days; datasets and checkpoints live on D:.

### B5. Stem-aware cleaning path

- Per-stem Analyze and preset (Mid 1.0 where there is no vocal), sum,
  master once. Remix UI: stem tree, per-stem cards, solo/mute,
  residual policy. Decide whether Master gets the same path.

### B6. Cost

- Best tier on the RTX 4070: roughly 1–3 minutes per four-minute
  track; CPU fallback on the Fast tier. Models and cache stay on D:.

---

## 5. Workstream C: Signal Chain view

- Serve the chain from the server for the active preset and options:
  stages enabled, bands, crossover, Mid scale, iterations, pre-analyze,
  fine pass, notch list, stem branch. `chain.js` renders that instead
  of a hand-written list; gates become an overlay, not a module.
- Add the missing stops: Trim, De-click, Static repair, Fine pass,
  Preserve/Clip, Export.
- Rule: no phase closes without its chain definition updated.

---

## 6. Sequencing

| Phase | Content | Size |
|---|---|---|
| 0 | C (data-driven chain view), docs — **done 2026-09-04** | S |
| 1 | A1 static repair, A2 de-click, A5 cutoff — **built 2026-09-05, awaiting listening sign-off.** Corpus: 83 fixed lines notched across 26 tracks, mean tone removal 0.98 on the 7 tracks with lines (target ≥ 0.8 met on 7/7); cutoff found on 6 tracks (15.6–19.0 kHz). De-click ships at 40 % in Sibilance Rattle and Deep Scrub because dense hi-hats register as clicks on some tracks; needs ears before going higher. | M |
| 2 | A3 fine pass, A4 per-bin DeHarsh — **built 2026-09-05, awaiting listening sign-off.** Corpus (26 tracks, verified Analyze): mean purity of ranked picks 0.82 → 0.83, six distinct winners, Analyze time 10.6 → 13.2 s per track (the fine pass adds about 2.5 s to the 28 trial cleans). The Flicker Tamer needed two fixes, not one: the fine grid *and* a floor reference (a half-duty flicker sits only 3 dB above its running mean, so the old design could never cut more than 1 dB). DeRes persistence-only detection deferred: static notches now handle its main target (fixed lines). | L |
| 3 | A6 catalog + preset chains, A7 Analyze | M |
| 4 | B1–B4 engine, stem tree, artifact-aware, benchmark — **started 2026-09-05.** Shipped: quality tiers in the existing side venv (Fast `htdemucs`, Best `htdemucs_ft`, 6 stems `htdemucs_6s`), a worker with real progress, float32 stems with no clipping or rescaling, cache by hash *and* model, the residual as a first-class lane (B2), the null test and per-stem level/share report (B4), stems export, and the lane mixer UI. Measured on the 20 s test clip: residual −29 dB rel. mix at Fast, −20 dB at Best (four specialists agree less about the sum). Still open: the Roformer/SCNet "Best" ensemble and the sub-stem tree (drums, lead/backing), both waiting on the licence checks in STEMS_MODELS.md; B3 (repairs before the split); the codec benchmark. | L |
| 5 | B5 stem-aware cleaning path and Remix UI (residual as a first-class stem with its own cleaning slot) | M |
| 6 | B4 own models: data pipeline, codec-degradation set, training and benchmark runs on the 4070 | L, runs in the background across phases |

Phase 4 touches only `stems.py`, its side venv and the Remix UI, so it
can run alongside Phases 1–3. Phase 6 is mostly machine time.

Standing test bed: a fixed reference set of five or six tracks Jeremy
knows well, with before/after exports kept per phase, so every listening
sign-off compares the same material.

---

## 7. Decisions

1. **Chain placements (Section 2).** Approved by Jeremy, 2026-09-04:
   de-click first, static repair before the tone curve, fine pass
   before the coarse pass.

2. **Residual stem: keep it turned down, or drop it?**
   The residual is the song minus all the stems. It holds small real
   details (reverb tails, room) and most of the AI junk (fixed tones,
   fizz). Dropping it sounds cleaner but thinner; keeping it makes the
   stems add back to the exact original, junk included.
   *Decision (Jeremy, 2026-09-04):* keep it at full level. It is a
   normal stem with mute, solo and a fader, like any DAW or Suno
   Studio; the user manages it per song. Because it is a stem, it also
   gets its own Analyze and cleaning slot, defaulting to the
   Lines & Combs / Hash family, so the junk it holds can be cleaned in
   place instead of muted away.

3. **Model licenses: what may we ship?**
   The best splitter models are free to download, but each has its own
   rules and some forbid commercial use. Jeremy releases music, so a
   "personal use only" model on a released song could break those
   rules.
   *Reconsidered 2026-09-04* once it was clear that "own models" means
   training. Three options:
   - **A. Use the best open models as they are (recommended).** Run
     BS-RoFormer / Mel-RoFormer / SCNet and the sub-stem models as an
     ensemble in our side venv. No training; matches the best tools
     (about 13.7 dB average). Our edge is the pipeline around the
     model: static repair before the split, the residual stem,
     per-stem cleaning, quality report. Licences checked per
     checkpoint; ship open-licence ones, offer the rest as optional.
   - **B. Fine-tune an open model for AI music (later, if the benchmark
     asks).** Days on the 4070 with the codec-degraded data set; gain
     of perhaps 0.5–1.5 dB on AI tracks; licence follows the base
     model. Only after A runs and the benchmark shows a gap.
   - **C. Train from scratch (no).** Weeks on multi-GPU racks for the
     top models; a single 4070 yields a compact model about 1 dB
     below the best. Months to end up behind.
   The AI-music benchmark (B4) stays regardless: it needs no training
   and is how models are chosen and claims are proven.
   *Decision (Jeremy, 2026-09-04):* **A.** Use the best open models as
   they are, in our side venv, with licences checked per checkpoint.
   B stays on the table only if the benchmark shows a gap; C is off
   the table. Execution started the same day with Phase 0.

4. **Cymbal Chatter and Reverb Flutter: rebuild or retire?**
   Both presets promise fixes the engine cannot do today. Chatter needs
   a tool that finds the repeat rate and smooths it; flutter needs a
   tool that lines up the timing of the tail so it fades as one smooth
   wash. Both are new tools with unknown payoff.
   *Decision (Jeremy, 2026-09-04):* drop the presets that are pointless
   now. Cymbal Chatter and Reverb Flutter are removed from the catalog
   in Phase 3 and kept only as hidden aliases so saved settings and
   scripts keep working (cymbal_chatter → suno_hash, reverb_flutter →
   broadband_fizz, the nearest working family). The other rarely
   winning presets are folded into families in Phase 3 rather than
   dropped, because their tools do work. Phase 6 is removed; the
   chatter-rate and phase-coherence tools return to the plan only if
   later corpus data shows real demand.

5. **Stem-based cleaning: Remix only, or Master too?**
   Master is the fast path (seconds); Remix is the deep path (minutes,
   GPU). Stem-based cleaning belongs to the deep path: split, clean each
   stem with its own preset, sum, master once. Remix-only keeps Master
   fast; adding a "Deep clean using stems" switch to Master (and Batch)
   gives the better result without changing tabs.
   *Decision (Jeremy, 2026-09-04):* Remix only. Master stays the fast
   single-file path with no stems; a Master/Batch switch can be added
   later if needed. Note that Phase 1's static repair runs full-band
   before the crossover, so the worst centered-artifact case (fixed
   tones the Mid scaling could not reach) is fixed in Master anyway.

---

## 8. Risks

- Fine and coarse passes both attenuating the same energy: the
  verification harness reports removed energy per pass; guard with a
  shared budget if it shows up.
- A static notch on a musical drone: persistence and excess thresholds
  plus the untick list in Analyze.
- Separation time, VRAM and model drift: tiers, cache, pinned model
  versions.
- Scope: every phase is gated by its acceptance list and a listening
  sign-off; nothing moves to the next phase on a promise.

---

## Sources

- MVSep algorithm scores (ensemble 13.67 dB average; htdemucs_ft 8.33 /
  12.05 / 11.24 / 5.74): <https://mvsep.com/en/algorithms>
- ZFTurbo pretrained models and metrics:
  <https://github.com/ZFTurbo/Music-Source-Separation-Training/blob/main/docs/pretrained_models.md>
- BS-RoFormer: <https://arxiv.org/abs/2309.02612>; Mel-Band RoFormer:
  <https://arxiv.org/abs/2310.01809>
- audio-separator (Roformer/MDX/Demucs runner, CUDA, ensembles):
  <https://github.com/nomadkaraoke/python-audio-separator>
- Suno stem separation (regeneration, modes, limits):
  <https://suno.com/blog/stem-separation-updates>,
  <https://alphasignal.ai/news/suno-rebuilds-stem-separation-from-scratch-hitting-90-accuracy>
- Restoration order of operations:
  <https://www.izotope.com/en/learn/order-of-audio-repair-operations.html>
- Artifact causes: see [PRESET_REVIEW.md](PRESET_REVIEW.md) sources.
