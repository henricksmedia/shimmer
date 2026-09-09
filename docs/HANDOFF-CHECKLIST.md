# Handoff checklist

The single source of truth for what has to be true before this work passes to
another model. It lives here rather than in a conversation because the list
drifted twice when it did not: items were completed, items were silently
dropped, and the version quoted depended on when you asked.

**This file is append-only.** Items are never deleted and never struck
through — only their status changes, with a reason. A removed line is
indistinguishable from a line that was never written, and it is exactly the
item nobody re-examines. Note the direction of the drift when it happened:
both silently dropped items were ones that would have slowed the work down.
That bias is not neutral, which is why removal is not allowed.

**Statuses:** `TO DO` · `DONE` · `DEFERRED` (decided against for now, reason
required) · `HANDED OFF` (specified here, built elsewhere).

**Rule for DONE:** an item moves to Done only when its *done-when* is
satisfied and verifiable by someone else. "I think that's finished" does not
count.

---

## Done

- [x] **Diagnosis, validated out-of-sample.** *Done when:* the finding
      reproduces on tracks not used to form it. 8/8 on the reference house
      curve; 5/6 on the tilt gap (kindling excluded — its pair is not the same
      performance). See `BRIGHTNESS-ASSESSMENT.md` §1.1–1.2.
- [x] **A trustworthy damage instrument.** `shimmer/perceptual.py`, BS.1387
      Basic ear model. Audited by 43 agents; critical-band table matches the
      published values to three decimals; magnitude now pinned by tests after
      a mutation survived 22 green tests.
- [x] **Reproducibility of that instrument.** *Done when:* identical input in
      separate processes gives identical output. 12 processes, identical to
      six decimals. This was the audit's highest-risk open question.
- [x] **Corpus integrity.** `scripts/corpus_check.py` — provenance, pairing,
      identity, duplicates, manifest. Caught two bad files that were invisible
      to both listening and spectra.
- [x] **A tone target from real data.** `docs/tone-reference.json` — 309
      labelled masters, 135 Neutral, per-track rows stored so it survives the
      catalogue moving.
- [x] **The artifact-measure question.** *Done when:* we know whether the
      variation is noise or signal, because the two need opposite fixes. It is
      signal (median lag-1 0.44, 84% of tracks above 0.3), so a robust
      track-level statistic is the wrong fix and the budget must be
      time-varying.
- [x] **Two shipping defects in the export note.** `cutoff_hz` reported as a
      user tweak; batch/album diffing against a rounded strength. Both
      reproduced, fixed, and covered by regression tests.
- [x] **Third-party naming removed.** 0 references in code, 0 in docs. Only
      remaining mentions are literal metadata strings in a provenance lookup.
- [x] **Control naming.** Tone correction (Light/Medium/Strong), Tilt
      (Crisper…Rounder), Tone target + target range. FK 4.7–5.9.
- [x] **The tone target swapped, and it reaches every flow.** `_REF_SHAPE_DB`
      now holds the measured curve; `_HARSH_MAX_BOOST_DB` 0.5 -> 2.0 (94% of
      5-12 kHz bands asked for more than 0.5 under the new target, median ask
      +2.3); high-shelf slider range `(-12, 0)` -> `(-12, +6)`. Verified: the
      curve is applied at one site (`pipeline.py:211`) that single, batch,
      album, preview, remix and CLI all funnel through. Measured effect,
      isolating only the target change: **mean tilt gap 8.88 -> 6.58 dB,
      26% closed**, capped by the 2 dB bound on four of eight tracks.
      Independent confirmation: `autoeq` flipped from prescribing -2.0 dB air
      trims on everything to +1.0 dB boosts on genuinely dark tracks, with no
      change to `autoeq` itself.
- [x] **The sibilance detector investigated.** It fires on 40% of tracks.
      Driven by genuine `sib_burst` on 10 of 12, not by the de-clicker — but
      two tracks are the documented hi-hat false positive (43 and 95
      clicks/second, which is a hi-hat pattern, not crackle). Whether the
      0.05->0.25 ramp is calibrated right needs non-AI control material.

---

## To do before handoff

- [x] **2. Re-measure the tilt gap on the MediumNeutral pairs.**
      *Done when:* one number with a spread, measured against a
      settings-consistent reference, replacing "11 dB against a mixed
      reference." 30 pairs available. **This was dropped once; it is needed
      because the documents will quote it.**
      **DONE 2026-09-08.** `scripts/tilt_gap.py`, cached in
      `docs/tilt-gap.json`. 88 MediumNeutral masters in the catalogue, 129
      Shimmer exports, 38 paired by song stem, 3 rejected: one is not the
      same performance (envelope correlation 0.21, the corpus check's own
      test at its own threshold) and two "references" are service masters
      made *from* Shimmer exports, so not independent. **n = 35: mean
      6.34 dB, median 6.06, sd 2.88, 16th-84th percentile 4.42 to 9.65,
      range -1.7 to 13.0, 34/35 positive.** Tilt is the 1/3-octave level at
      6.3 kHz minus 800 Hz, middle 90 s, the tone reference's own analysis.
      The quotable sentence is therefore "about 6 dB, not 11": the six-song
      figure was measured on six songs against references on mixed
      settings. These Shimmer masters are what earlier
      versions of the chain shipped (20 of 35 carry a Shimmer tag note
      naming the pass); the current chain's gap is `verify_tone_fix.py`'s
      question and stays at the 6.58 dB measured after the target swap on
      its 8 sources.

- [x] **3. Preset harness — all 19.**
      *Done when:* a script produces the full damage matrix, a committed
      cached result, and tests asserting *relations* (clean material damages
      less than hashed; monotonic in strength; surgical group below broadband
      group) rather than invented thresholds. **Also dropped once.** It is the
      acceptance criteria the next model builds against, and it is what would
      have caught the two hand-found defects.
      **DONE 2026-09-08**, together with item 6 and by the same script:
      `scripts/efficacy_harness.py`, cached in `docs/efficacy-harness.json`
      (1470 rows: 5 clean hosts x 7 modelled artifacts x 2 levels x 19
      presets + the static repair) and `docs/efficacy-strength.json` (7
      presets at 50/100/200 %). `tests/test_efficacy.py` asserts relations:
      Generic reads as inert (0 efficacy, 0 cost); the static repair removes
      a fixed line; for each modelled artifact some aimed preset beats
      Generic; Deep Scrub costs more than every surgical preset; the
      artifact does not make a preset take more music than it takes from a
      clean host; tilt on the clean host rises with strength. Three of those
      relations are false for named presets and are recorded as *strict*
      expected failures with the measured reason, so a fix flips them:
      Sibilance Rattle, Reverb Flutter, Checkerboard Grid (see item 6).
      "Clean material damages less than hashed" was not asserted: net of the
      artifact's own masking, every preset costs *less* on the render than
      on the clean host, because the artifact absorbs part of what the
      preset removes — the relation that holds is the one above.

- [ ] **4. One listening round.**
      *Done when:* current chain vs fixed chain vs reference, level-matched
      and blind, judged by the author. Only he can close this. Both previous
      rounds changed the diagnosis.

- [x] **5. Fix the verified score. (Highest-value single change.)**
      *Done when:* a preset can no longer score well by removing a lot.
      `final = 0.8 x verified + 0.2 x prior`, and `verified = benefit x purity`
      where purity is a mask-location ratio, not a measurement. This one
      function is the root of: Deep Scrub being selected (its *evidence* prior
      is median 0.28 and never the highest on 25 tracks — it wins on the
      score), the "97% was noise" claim, and the detector recommending
      cleaning for finished commercial masters at 80% confidence. Fix it and
      Deep Scrub demotes itself with no policy needed.
      **DONE 2026-09-08.** `verified_score` is now net audible benefit:
      `(2p - 1) x M - L`, with `M` the hearing model's `missing` ramped to 1
      at `budget.MAX_BUDGET_SONES` (0.10), `L` its `lin_dist` ramped to 1 at
      `budget.MAX_LIN_DIST` (3.0), and `p` the evidence prior. The prior is
      no longer blended in separately; unverified runs still rank on it.
      `purity` is gone from the code, the CLI table, the API and the reason
      sentence, which now reports audible loss and tone shift against those
      two limits. Measured before/after on the detector's own hot windows,
      16 presets per file (`scripts/score_probe.py`; cached rows in
      `docs/score-probe.json`): the old score fired on
      **9/9** finished masters (7 mastering-service masters + 2 references)
      at 0.69-0.92; the new one fires on **0/2** references and **2/7**
      service masters, both at ≤ 0.12 net benefit — one of them on Suno Hash
      where the master's own flicker excess reads +2.4 dB, which the
      assessment documents as expected for a service master. Of 7 Suno
      renders, 2 get a recommendation (Suno Hash 0.15, Sibilance Rattle
      0.06) and 5 get none. Synthetic hashed bed picks a hash preset.
      Regression test: `test_finished_master_gets_no_recommendation` runs
      the full product path on `assets/reference/*.wav`. Deep Scrub scores
      0 everywhere (tilt 12-26 against a ceiling of 3) with no policy.
      *Not settled by this:* see items 10-11 below.

- [x] **6. Measure efficacy, not just cost. Then re-judge every preset.**
      *Done when:* the harness reports BOTH "did the artifact drop" and "what
      did it cost", for all 19 presets, using an artifact measure that is not
      the detector's own prior. `scripts/preset_harness.py` does the shape of
      this but currently measures efficacy with `priors_from_evidence`, which
      is the component already shown to be miscalibrated — so the numbers are
      circular. **Everything built before this measured cost alone**, which is
      backwards for a repair tool and made the presets look surgical when
      several are inert.
      **DONE 2026-09-08.** *The independent measure:* ground truth. A
      finished master with no measurable hash (5 hosts: 4 service masters
      and the reference "Hey", loudest 8 s) plus a modelled artifact
      (`shimmer/artifacts.py`: hash, fixed line, intermittent whistle, comb,
      steady fizz, signal-following residue, centred sibilance), scaled by
      the hearing model to inject 0.5 or 2.0 sones of audible content.
      Efficacy = 1 - added(preset(host), preset(render)) / added(host,
      render): the artifact's audible footprint after cleaning, relative
      to the cleaned clean host so the cleaner's own alterations cancel.
      Cost = music removed from the host, net of the artifact's masking.
      The detector is not consulted. *The re-judgement, at 2.0 sones, mean
      over hosts, efficacy on the artifact each preset is aimed at, then
      cost on the clean host:*
      - Static repair: line **96 %**, comb 28 %, intermittent whistle 17 %.
        Cymbal Sheen line 27 %, Laser Whistle whistle 28 %, both at ~0
        cost. The tone killer does a quarter of what the notch plan does.
      - Vocal Glaze + Top End: hash **29 %** at 0.106 sones on a clean host,
        the best on hash. Deep Scrub: hash 24 %, fizz 27 %, line 89 %,
        residue 12 %, at 0.164 and tilt 2.0 — it works by taking the most.
      - **Suno Hash: hash 12 % (9 % at 0.5 sones), inert on its own
        target.** Measured at every modulation rate from 8 to 40 Hz and in
        both 4.5-12 and 5-9 kHz: 7-22 %. The FlickerTamer flattens the
        flicker; the added noise stays and the hearing model still hears it.
      - Inert on their targets: Broadband Fizz 6 % of fizz; Air Brittle 2 %
        of fizz; Checkerboard Grid **-1 %** of comb while taking 0.146 sones
        of music (0.004 on the clean host); Sibilance Rattle **-2 %** of
        centred sibilance at the highest cost of any single preset (0.120
        on a clean host, tilt 1.3); the four residue presets Echo Sheen 5 %,
        Presence Haze 7 %, Harsh Veil 4 %, Vocal Glaze 4 %, Phantom Cymbal
        2 %. Reverb Flutter and Cymbal Chatter have no model (phase
        incoherence, periodic chatter) and are *not covered*, not inert;
        Reverb Flutter does take 0.089 sones from renders against 0.008
        from a clean host. Muddy/Boxy and Dark Mix Rescue are static EQ
        with no artifact aimed at them; as expected of a tone move they
        register as tilt (11.1 and 8.6) and 0.167 / 0.231 sones on a clean
        host, and ~0 efficacy on every model.
      - *The old harness's efficacy was noise:* over the 125 aimed rows
        where the prior saw the artifact, the drop in the preset's own
        prior correlates **+0.22** with ground-truth efficacy. And the
        priors barely see a 16 kHz line (Cymbal Sheen 0.04 -> 0.04 when one
        is injected) that the static scan removes at 96 %.
      *Scope, stated plainly:* these are models of the artifacts built
      from PRESET_REVIEW.md §1, on five hosts. A preset that fails the
      model has failed the model; a listening round (item 4) is what ties
      the model to the real thing. What this settles regardless: the
      product's answer for a hashed track is not the preset named for it.

- [ ] **7. Composite preset: handle 3+ artifacts in one pass.**
      *Done when:* a track showing several artifacts gets one `Params` built
      from the specific stages those artifacts need, instead of either two
      sequential presets or Deep Scrub. **56% of tracks (14/25) fire three or
      more artifacts; the median is 3 and the max is 8.** The tool runs at
      most two presets, and its designed answer for "many" is Deep Scrub —
      the most damaging preset measured. Check first whether stages compose
      cleanly; Deep Scrub also widens bands and runs two iterations, which
      suggests a simple union was found insufficient.
      **Status 2026-09-08: still TO DO, with two preconditions found while
      doing items 5 and 6.** (a) The "3+ artifacts on 56 % of tracks" count
      is the priors firing, and item 10 shows the same priors read 0.7-1.0
      on finished masters: the number of artifacts a track "has" is not
      known until the priors have a nothing-is-wrong state. Under the
      net-benefit score, 5 of 7 Suno renders get *no* recommendation, not
      several. (b) Item 6 measured the stages a composite would be built
      from: on their own targets Suno Hash removes 12 %, Checkerboard Grid
      -1 %, Sibilance Rattle -2 %, the residue presets 2-7 %; only the
      static notch plan (96 % of a line) and, at a price, the broadband
      presets do measurable work. A union of stages that each remove
      nothing removes nothing. Build the composite after item 10 and after
      at least the hash stage measures as effective; until then the honest
      product answer for "many artifacts" is the notch plan plus one
      preset, which is what the score now produces.

- [x] **8. Retire the routine second pass.**
      *Done when:* the automated flow is one pass by default. Measured: on
      three multi-artifact tracks, cleaning revealed **no new artifacts**
      (one marginal hit at exactly the 0.40 threshold), but it **raised other
      priors** — suno_hash 0.80 -> 0.90, laser_whistle 0.70 -> 0.85. These
      priors are relative measures, so removing energy in one band inflates
      the others. The second pass is therefore partly responding to a number
      the first pass created. Any genuine need for iteration belongs inside a
      preset (`iterations`), where it is covered by one damage measurement.
      **DONE 2026-09-08.** `detect.suggest_array(follow_up=False)` is the
      default; the server, batch and remix paths pass nothing, so the
      automated flow is one pass. The check can still be asked for
      (`follow_up=True`), and when it runs it is gated on net audible
      benefit measured against the winner's output, not on purity.
      Measured with the new score on 8 corpus files (2 references, 5 Suno
      renders, 1 service master): the second pass fired on **0/8**, and
      turning it off saves 4 of the 28 pipeline runs per Analyze. The
      Single File tab's "Second pass" tile now always reads "Not needed"
      and its pass-plan flow is dead code; removing them is a UI change
      against the approved design and is listed under "UI implementation"
      below rather than done here. Test:
      `test_the_automated_flow_is_one_pass_by_default`.

- [ ] **9. The four documents.**
      - `GOALS.md` — goal, anti-goals, decision rule, frozen corpus
      - `IMPLEMENTATION.md` — the PRD: what to build, in order, with
        executable acceptance criteria
      - `STYLE.md` — the house rules currently scattered in docstrings
      - `PITFALLS.md` — every wrong turn taken here, so it is not retaken

- [ ] **10. Give the prior a real "nothing is wrong" state.** (Added
      2026-09-08 while doing item 5; it is the assessment's recommendation
      2.) *Done when:* on artifact-free music the priors read near zero.
      Measured on the hot windows of the 9 finished masters: `vocal_glaze`
      reads 0.71-0.83, `presence_haze` up to 1.00, `harsh_veil` up to 0.93,
      `deep_scrub` up to 0.92; on the synthetic clean bed `echo_sheen` reads
      1.00. The new score holds these off a finished master only because
      their tilt cost exceeds their credit, which is the right outcome for
      the wrong reason: a preset whose evidence is "this is music" should
      earn nothing before cost is counted. The ramps in
      `priors_from_evidence` were set from 26 Suno renders with no clean
      control. Recalibrate against the labelled corpus (9 finished masters
      are available in `sources/` and `assets/reference/`).

- [ ] **11. Re-examine the actionable threshold and the confidence
      scale.** (Added 2026-09-08.) `MIN_ACTIONABLE_SCORE = 0.05` and the
      confidence formula `score x (0.5 + 0.5 x margin) x 1.5` were set for
      the old score, whose range on real material was 0.7-1.0. The new
      score's range on the corpus is 0-0.29 (synthetic hash 0.21-0.29,
      real renders ≤ 0.15), so confidences now read 0.1-0.3. That is honest
      about the evidence but the UI copy ("20% match") was written for the
      old scale. Decide, with listening, what a 0.15 net benefit is worth
      before moving either number; do not rescale to make the bars look
      like they used to.

---

## DEFERRED — the 80% stake

Decided against for this pass, with the reason. These stay on the list so they
can be revisited deliberately rather than rediscovered.

- **DEFERRED — Per-section budget envelope.** The scalar cap gets most of the
  benefit; the time-varying version is a refinement. Revisit if the scalar cap
  proves too blunt in listening.
- **DEFERRED — Reference-track matching.** No automated mastering service does
  this; a single well-derived target shipped with the app is the category
  norm. Revisit if users across genres report the target fits them badly.
- **DEFERRED — References capture section.** Follows from the above: not
  needed once the target ships as a constant.
- **DEFERRED — Full beginner-first UI pass.** The visibility fix (show EQ and
  mastering only once a file is loaded) covers the reported problem. Revisit
  if first-run users from social posts report confusion.

---

## Handed off, with preconditions

These are specified but not built here. The audit lists preconditions that
must be met **before `budget.py` is wired into the pipeline**; they are not
blockers for the items above, because the 80% plan does not wire it.

- Wire the budget in. Preconditions: `S0_LINDIST` → 1.0 and recalibrate
  (contradicts the reference at 0.5); golden-value tests pinning the PEAQ
  constants (eight mutations currently survive); level-match inputs in
  `measure_damage`.
  - `S0_LINDIST` **DONE 2026-09-08**, done first because item 5 fits a
    cost term on `lin_dist` and a later change of scale would have moved
    it. Cited: Kabal 2002 eq. 105-106 (p. 39) gives AvgLinDist alpha 1.5,
    T0 0.15, S0 1; the Basic-model MATLAB's S0 0.5 belongs to RmsNoiseLoud
    (H.2, p. 87). Measured effect on the anchors `LIN_DIST_BASE` was set
    from (25 s loudest excerpts, 4 Suno sources + the clean control):
    Cymbal Sheen 0.047-0.081 → 0.042-0.072, Suno Hash 0.40-0.79 →
    0.35-0.71, Deep Scrub 12.5-20.4 → 11.9-19.4; shelf tests -3/-6/-12 dB
    5.23/22.1/49.4 → 4.64/20.6/49.9. Ratios 0.88-1.01. The ceiling's own
    rule ("passes the two accepted presets, stops the one ranked last")
    still gives 1.0, so `LIN_DIST_BASE` is unchanged and the pinned
    magnitude test still holds. `SONES_PER_DB` does not involve
    `lin_dist` and was not re-fitted. The other two preconditions stand.
  - The ear model was vectorised the same day (`_spread_frames`,
    `_band_matrix`, cumulative-sum neighbour means in `_adapt`); output is
    identical to the loop form to 3e-15 relative on real audio and
    `measure_damage` on a 5 s clip went from 0.70 s to 0.11 s, which is
    what makes measuring every trial clean affordable (about 3 s per
    Analyze on top of the trial cleans themselves).
- The per-section budget envelope.
- UI implementation against the settled labels, including four existing bugs
  the naming panel found.
  - Added 2026-09-08: remove the Single File tab's "Second pass" tile and
    its pass-plan flow (`single.js`: `ensurePlan`, `lastFollowUp`, the
    `ctx.followUp` gating of the tone auto-apply), which are dead now that
    item 8 made the flow one pass. Also the "match %" copy, which item 11
    says was written for the old score's range.
- Re-master the catalogue from source, verified against the corpus.
