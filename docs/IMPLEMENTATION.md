# Instructions for the next model

You are picking up work on Shimmer, a local mastering tool for AI-generated
music. This document is self-contained: you do not have the conversation that
produced it, and you do not need it.

Read this whole file before changing anything. Then read
`docs/HANDOFF-CHECKLIST.md`, which is the live list of what is done and what
is not.

**Another agent may be working in this repository.** Before you start, run
`git log --oneline -5` and `git status` and check the branch. If the state
does not match §3, trust the repository over this document and say so. Do not
begin by re-doing work that is already committed — the commit messages record
what was done and why.

---

## 1. What the tool is for, and what it got wrong

Shimmer detects artifacts in AI music renders (Suno, Udio), removes them with
presets, and masters the result. **Artifact repair is the product.** No
competitor does it; the mastering half is table stakes.

An investigation found the tool was shipping dull masters. Measured against
commercial reference masters of the same songs, output sat about **10 dB out
of tilt** across 800 Hz to 6.3 kHz, on every track tested. Four causes, in
descending size:

1. The tone target was a 1950–2010 average used as a present-day target, so
   every contemporary master read as too bright and every automatic decision
   came out a cut. **Fixed.**
2. The detector's self-check (`purity`) measures nothing. **Fixed
   2026-09-08** — see §4 and checklist item 5. Two follow-ups it exposed
   are checklist items 10 and 11.
3. Presets over-reach relative to how much artifact is actually present.
4. Cleaning narrows the stereo image by 1–4 dB. **Not investigated.**

Full evidence, with numbers: `docs/BRIGHTNESS-ASSESSMENT.md`.

---

## 2. Non-negotiables

These are not style preferences. Each one exists because breaking it caused a
real defect in this codebase.

**Never patch a symptom.** Find the cause, fix that. If the proper fix is
large, say it is large and do it. Do not offer a reduced-scope version as a
fallback, and do not offer the user a manual workaround — both read as
band-aids and will be rejected.

**Never assert a standard from memory.** Fetch it. Every incorrect claim made
during the investigation came from stating a standard, a best practice, or an
industry norm without checking. The reference documents you will need are
named in §6.

**Label your confidence.** Distinguish *measured* (a script was run, numbers
shown, command re-runnable), *cited* (a document was fetched and quoted),
*read* (code was read), and *believed*. Present them differently. Believed
claims are where every error came from.

**The checklist is append-only.** `docs/HANDOFF-CHECKLIST.md` — never delete
an item, never strike one through. Change its status and give a reason. Items
that were silently dropped were, both times, the ones that would have slowed
the work down.

**Measure before and after every change.** Not "this should help" — run it,
show the numbers, on the corpus.

---

## 3. State of the tree

**All of this is committed and pushed** to the branch
`fix/tone-target-and-measurement`, five commits, not yet merged to `main`.
Start from that branch, not from `main` — `main` does not have any of it.

```
git checkout fix/tone-target-and-measurement
cd <repo> && ./.venv/Scripts/python.exe -m pytest tests/ -q      # 272 pass
```

The commit messages carry the reasoning behind each change and are worth
reading before altering anything they touch:

| | |
|---|---|
| `65621cf` | marketing kit and its claims tests |
| `6370094` | export-note provenance, two defects that wrote false data |
| `97609c0` | the tone target swap — the actual dullness fix |
| `77164be` | the damage measurement, tooling, de-branding |
| `e9daf27` | documentation |

**New modules (research code, zero callers in the product):**
- `shimmer/perceptual.py` — ITU-R BS.1387 damage model. Audited; critical-band
  table matches published values to three decimals; reproducible across
  processes. Measures how *audible* a change is.
- `shimmer/budget.py` — caps cleaning at what the measured artifact justifies.
  **Do not wire this into the pipeline yet**; preconditions in §5.

**Changed and verified:**
- `shimmer/mastering.py` — the tone target is now measured from 135 real
  masters. Caps lifted so the curve can reach it.
- `shimmer/params.py`, `server.py`, `tags.py` — export-note provenance, plus
  two fixed defects that wrote false data into shipped files.

**Data that ships:**
- `docs/tone-reference.json` — 309 labelled masters, per-track rows, so the
  target can be re-derived without the audio.
- `docs/preset-harness.json` — preset efficacy and cost.

**Tooling:**
- `scripts/corpus_check.py` — call `require_valid_corpus()` before any
  measurement. It caught two bad corpus files that were invisible to both
  listening and spectra.
- `scripts/preset_harness.py`, `build_tone_reference.py`,
  `artifact_stability.py`, `verify_tone_fix.py`, `make_ab_round.py`,
  `listening_scores.py`.

---

## 4. Your first job: fix the verified score

> **Status: DONE 2026-09-08.** Kept as written so the reasoning survives.
> What shipped: `detect.verified_score(meas, prior, tone_weight)` returns
> `max(0, (2p - 1) x M - L)` with `M = ramp(missing, 0, 0.10)` and
> `L = ramp(lin_dist, 0, 3.0)`; the two full-scale points are
> `budget.MAX_BUDGET_SONES` and `budget.MAX_LIN_DIST`, reused rather than
> newly fitted. The 0.8/0.2 prior blend is gone. Numbers, before and after,
> are in `docs/HANDOFF-CHECKLIST.md` item 5. What it did *not* settle: the
> priors still read high on clean music (item 10) and the actionable
> threshold and confidence scale were set for the old score (item 11).

This is the highest-value single change in the codebase. Do it first; three
other items depend on it.

**What is wrong.** `detect.py` ranks presets with
`final = 0.8 * verified + 0.2 * prior`, where
`verified = benefit(artifact_db) * purity` and

```
purity = G / (G + B)      G = energy removed from `eligible` cells
```

`eligible` means: above 2 kHz, not inside a transient frame, and not a
narrowband partial — and above `PARTIAL_MAX_HZ = 10000` nothing can be a
partial at all. On finished commercial masters that mask covers **84–95% of
all energy above 2 kHz and 98–100% above 10 kHz**. So purity is near 1.0 for
any preset confined to the sustained top end, whether it removed hiss or a
cymbal.

Measured: **purity correlates −0.003 with actual audible damage** across 16
presets. Not weakly — it carries no information. Its dynamic range is 1.36x;
the damage model's is 488x.

**What it causes.** The detector recommends cleaning finished commercial
masters at 80% confidence. Deep Scrub gets selected despite its *evidence*
prior being median 0.28 and never the highest on 25 tracks — it wins on the
score, because the score rewards removing a lot. The user-facing sentence
"97% of what it removed was noise, not music" is a restatement of where the
preset operates, not a finding about the audio.

**What to do.** Replace `purity` with a real measure of whether the removal
was audible and whether it was music. `shimmer/perceptual.py` already provides
this: `measure_damage(reference, test, sr)` returns `missing` (audible content
removed) and `lin_dist` (spectral tilt damage) in sones. Score a preset as
**benefit minus cost in the same unit**, not as a ratio of mask locations.

**Done when:** a preset can no longer score well by removing a lot; the
detector returns no recommendation on a clean commercial master; and the
user-facing purity sentence is gone from the UI.

**Verify with:** `assets/reference/*.wav` are finished masters. Any preset
recommended on them at high confidence is a failure.

---

## 5. The rest of the work, in order

Full detail with numbers is in `docs/HANDOFF-CHECKLIST.md`. Summary:

**6. Measure efficacy, not just cost.** Everything built so far measures what
presets *remove*. Nothing measures whether the artifact went away — which is
backwards for a repair tool. `scripts/preset_harness.py` has the right shape
but measures efficacy using the detector's own priors, which are the
component already shown to be miscalibrated. That is circular. Find an
independent artifact measure first.

**7. Composite preset for 3+ artifacts.** 56% of tracks fire three or more
artifacts (median 3, max 8). The tool runs at most two presets, and its
designed answer for "many" is Deep Scrub — the most damaging preset measured.
Build one `Params` from the specific stages the detected artifacts need.
Check whether stages compose cleanly before assuming they do.

**8. Retire the routine second pass.** Cleaning revealed no new artifacts on
three multi-artifact tracks, but *raised* other priors (0.80→0.90,
0.70→0.85), because those priors are relative measures. The second pass
partly responds to a number the first pass created.

**Then, and only then, the budget.** `shimmer/budget.py` limits cleaning by
measured artifact. Preconditions before wiring it in:
- `S0_LINDIST` is 0.5 and the reference says 1.0 for AvgLinDist. Fix, then
  re-run `scripts/calibrate_budget.py`, because `LIN_DIST_BASE` was fitted
  against the current scale.
- Eight mutations to standard-mandated PEAQ constants currently leave the
  test suite green. Add golden-value tests.
- `measure_damage` does not level-match its inputs; Kabal's own experiments
  do. Level differences leak into `lin_dist`.
- The budget limits removal without checking what survives. A budget that
  holds a preset back until the artifact remains would pass every test.
- Its constants are fitted on four songs judged by one listener. The file
  says so. Do not trust them to two significant figures.

---

## 6. Reference documents

Fetch these rather than recalling them.

- **ITU-R BS.1387 (PEAQ)** — the damage model. Kabal's canonical
  interpretation with reference MATLAB:
  <https://www.mmsp.ece.mcgill.ca/Documents/Reports/2002/KabalR2002v2.pdf>
- **Delgado & Herre, arXiv:2212.01467** — why to use PEAQ's individual model
  outputs and not its composite grade. For music, linear distortion is the
  strongest single predictor.
- **AES TD1008** — loudness. Says explicitly that a high peak-to-loudness
  ratio sounds clearer than heavy limiting.
  <https://aes.org/technical-council/technical-document-aestd1008/>
- **Pestana et al., AES 135 (2013)** — the spectral study the old tone target
  came from. Useful for understanding what was wrong with it.

---

## 7. Traps

Each of these caught someone during the investigation.

**A metric that cannot fail is not a metric.** `purity` scored ~1.0 for
everything and nobody noticed for a long time, because the number looked like
evidence. When a measurement always agrees with you, test it against material
where the right answer is known — a finished master should score as needing
nothing.

**Cost-only views cannot tell surgical from inert.** Six presets were praised
as "surgical, they do nothing when there is nothing to repair." They also fix
nothing. You need both axes or you will recommend inert presets.

**Residual listening cannot detect air loss.** Removed air sounds like *shhh*
in isolation, never like music, so a listener correctly says "no music in
there" while several dB of openness has gone. Judge magnitude by comparing
masters, not by listening to what was removed.

**Level-match every A/B.** The entire investigation started because a
reference master sounded better while being 2.8 LU louder. Any comparison
that skips this measures loudness.

**Verify corpus files before measuring them.** Two files were wrong: one
labelled as a reference master was not one, and one pair was not the same
performance. Both were invisible to listening and to spectra; metadata and an
envelope correlation caught them. Run `corpus_check.py`.

**Do not fit constants to four songs and believe them.** Several in
`budget.py` are, and the file says so. Widen the corpus before tightening
a threshold.

**Self-referential tests drift.** A test that builds its input from the
constant it tests against will silently change meaning when that constant
changes. One did exactly that when the tone target moved; the detector was
fine and the stimulus had shifted.

**Statistics over duplicate files are wrong.** The same master is often filed
in several places. Deduplicate by content before taking a median.

---

## 8. When you are uncertain

Say so, and say what evidence would settle it. Do not pick the plausible
option and move on — that is how the original defect was created. Several
questions in this codebase are genuinely open, and they are marked as open
rather than resolved by guessing.

If a change would make two errors cancel — for example, correcting a tone
target to compensate for over-cleaning — do not make it. Errors that cancel on
average diverge on individual tracks, and they hide the defect underneath.
