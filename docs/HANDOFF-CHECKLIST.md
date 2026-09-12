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
      **Status changed to TO DO 2026-09-08 — reason:** the data is real but
      it is not a commercial reference. All 309 are one automated service's
      masters *of AI renders*, which the file's own metadata says
      ("a target for this tool's material, not a general commercial
      reference"). It was used as a general target regardless. Superseded by
      item 12; see `BRIGHTNESS-ASSESSMENT.md` §7.
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
      **Status changed to TO DO 2026-09-08 — reason:** everything measured
      here still holds — the curve does reach every flow, and it did close
      26% of the tilt gap. The target it reaches is the problem. It runs
      ~6.7 dB hot in the presence band and ~8.5 dB hot in the air band
      against contemporary commercial music, so closing the gap to it moved
      output *away* from real records. `_HARSH_MAX_BOOST_DB` 0.5 → 2.0 and
      the high-shelf range extension to +6 exist to let the curve reach that
      target, so they are in scope for the same fix. Note the warning sign
      that was there at the time and was read as confirmation: `autoeq`
      flipping sign on *everything* is what a moved target does, not
      evidence the new target is right. See item 12.
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
      its 8 sources. *Later on 2026-09-08 another agent recorded in
      IMPLEMENTATION.md §1 that the swapped target is itself measured
      about 6.7 dB hot in the presence band against contemporary
      commercial music; the 6.58 dB current-chain figure is therefore
      against a disputed target and should not be quoted until that is
      settled. The 6.34 dB catalogue figure above does not depend on the
      target: it compares two masters' own spectra.* *And, read against
      §7.3: the yardstick here is the mastering service, which §7 measures
      about 6 dB above contemporary commercial masters in presence and 8 dB
      in air. So "6.3 dB duller than the service" is not "6.3 dB duller
      than commercial music"; §7.3's own zone table puts Shimmer output
      2.9 dB* above *commercial in presence and 1.2 dB above in air. Item
      12's done-when re-measures this gap against captured commercial
      masters; until then this number describes distance from the service,
      nothing more.*

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
      *2026-09-08, built, not judged.* `listening-test/round-4/blind`, made
      by `scripts/make_round4.py`. It tests the scorer change (items 5 and
      10), which alters *which preset the automatic flow applies*: per song
      the untouched file, what the purity-based scorer applied (Sibilance
      Rattle at 50-100 % on four files including the reference "Hey", Harsh
      Veil at 125 % on the reference "Leave The World Behind", Vocal Glaze +
      Top End, Suno Hash) and what the net-benefit scorer applies (Generic on
      six files, Suno Hash on the two `the-little-things` files). Cleaning
      only, no mastering, so the retracted tone target (item 12) plays no
      part. Loudest 30 s, -18 LUFS, blind; `ANSWER-KEY.json` names the picks.
      Eight songs, 22 files. The "fixed chain vs reference" comparison this
      item also asks for waits on item 12, because the chain's mastering
      half is what item 12 changes; `round-3` is that comparison against
      the now-retracted target.
      **Judged 2026-09-08** (`round-4/blind/SCORES.json`). Author's
      overall remark: "the differences seem slight." Preferred letter per
      song: new scorer's pick 2 (Suno Hash on the service master of
      the-little-things; Generic on the reference "Leave The World
      Behind"), old scorer's pick 2 (Sibilance Rattle on algorithms-lure and
      couldve-been-stories), **untouched 3** (alive-again, falling-for-you,
      and suno-the-little-things where the only cleaned option was Suno Hash
      at 100 %), no preference 1 (reference "Hey"). Two files "still have
      shimmer" after either treatment. What this settles: on finished
      masters the old picks did not win, so item 5's removal of those
      recommendations cost nothing audible; the untouched render beating
      Suno Hash on a hashed track agrees with the harness (12 % efficacy at
      a cost); and no treatment in the product today removes what the
      author hears as shimmer, which is the hash-stage work. What it does
      not settle: Sibilance Rattle winning twice on Suno renders where the
      harness calls it inert — the next round should put that preset
      against Generic and untouched on those two tracks with the de-esser
      isolated from its tilt, so the preference can be attributed. Item 11
      follows from "slight": scores of 0.1-0.5 describe differences a
      careful listener calls slight, so the copy should say so rather than
      be rescaled.
      **JUDGED 2026-09-09 on the listening bench — 36 sets, 40 rounds, all
      blind (`revealed_first` false everywhere), verdicts in each set's
      `SCORES.json`.** Letters are randomised per set and the winning
      letter varies, so these are not a fixed-button bias; labels were
      decoded against each set's own `ANSWER-KEY.json`. One probe verdict
      on `tone-kindling` is marked "ignore" and is excluded, which leaves
      kindling with no tone verdict.

      | Comparison | Songs | Result |
      |---|---|---|
      | `service` — chain today vs the service master | 8 | service **8-0** |
      | `r8` — chain today / service / chain before / untouched | 8 (+1 repeat) | service **8**, chain-before 1, chain today **0**, untouched 0 |
      | `chain` — full chain vs untouched render | 4 | untouched **3**, tie 1, chain **0** |
      | `clean` — untouched vs cleaned | 4 (5 rounds) | **all ties** |
      | `tone` — derived target vs retracted service curve | 8 | retracted **7**, tie 1, derived **0** |
      | `era` — derived / 1950-2010 / retracted | 4 | retracted **3**, tie 1, derived **0** |

      **The chain as it ships won nothing, on any comparison, on any
      song.** Three findings, in order of how much they cost.
      (a) *Cleaning is inaudible.* The `clean` sets put untouched against
      cleaned directly and every one is a tie. This is the same verdict the
      harness gives (item 6: most presets 0-7 %) and the same one item 15
      keeps reaching; it is now heard, not just measured.
      (b) *The chain is a net negative.* The untouched render beat the full
      chain 3 of 4, the fourth noted "sounds too similar". So the mastering
      half is taking something away that cleaning is not putting back.
      (c) *The tone target is backwards* — see item 12.
      The service master beat Shimmer **16 times out of 16** across
      `service` and `r8`.
      **Full record with its conditions and limits: `docs/listening/`,
      rebuilt by `scripts/listening_report.py`.** Read that before citing any
      number here. Two conditions in it change how much weight this round
      carries. The listener wrote the tool and knew what each outcome would
      mean — blind to the arms, not blind to the hypothesis. And everything
      was heard on **one system, the listener's everyday computer speakers**.
      That is a real consumer-playback check this project had never done, and
      it is also the only system tested, so the round cannot separate "this
      curve is better" from "this curve suits these speakers". It also means
      the +0.6 dB above 12.5 kHz was probably never audible: small speakers
      give up below that, so the preference was most likely carried by the
      2-8 kHz lift and the 1.2 dB low-mid cut. **The cheap test that would
      settle it is three of the same songs judged again on headphones.** If
      the direction holds the target is right; if it flattens, the target is
      bending to fit one pair of speakers.
      *Limits of this round, so it is not over-read:* one preferred pick
      per round, no rankings, so "the chain never won" is known but its
      placing is not; auditions were short on the tone sets (4-9 s on six
      of eight), which favours whichever arm reads brighter first; and no
      set carries an ABX run, so nothing here has a stated audibility
      p-value. None of that touches the direction, which is one-sided in
      every group.

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
      Later on 2026-09-08: item 10 is done, and with the recalibrated
      priors no corpus file fires more than one preset above the actionable
      score. Precondition (b) stands: the stages are the blocker now.

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

- [x] **9. The four documents.**
      - `GOALS.md` — goal, anti-goals, decision rule, frozen corpus
      - `IMPLEMENTATION.md` — the PRD: what to build, in order, with
        executable acceptance criteria
      - `STYLE.md` — the house rules currently scattered in docstrings
      - `PITFALLS.md` — every wrong turn taken here, so it is not retaken
      *2026-09-08:* `PITFALLS.md` drafted from the assessment's traps and
      this session's own wrong turns, each with the evidence that caught it.
      `GOALS.md` and `STYLE.md` not written: the goal and the decision rule
      are the author's to state, and the house rules need a pass over the
      docstrings that this session did not make. `IMPLEMENTATION.md` is
      being maintained by whoever is in the tree.
      **DONE 2026-09-09.** `GOALS.md` written from the author's own
      statement: clean up the artifacts AI generators leave — pops,
      crackles, shimmer, sheen, the faults the Suno and AI-music communities
      report — and master to the same standard as a modern mastering tool
      using better algorithms. It carries the anti-goals, the decision rule
      (efficacy, then cost in sones, then distance from real records, then a
      level-matched blind listen, which outranks the other three), the
      frozen corpus, and the open questions. FK grade 6.8.
      `STYLE.md` written, FK 7.2. It was a **missing file, not a missing
      decision** — the house rules were already settled and already followed,
      just scattered across docstrings, commit messages and conversation,
      which is why they kept being asked about rather than looked up. Asking
      the author to restate them was the error; collecting them was the work.
      **One thing needs the author's eye:** the anti-goals in `GOALS.md` are
      inferred from decisions made, not stated. They are marked as inferred.
      Correct them rather than assume they were agreed.

- [x] **10. Give the prior a real "nothing is wrong" state.** (Added
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
      **DONE 2026-09-08.** `scripts/prior_calibration.py` prints, per
      feature, its range on the 9 finished masters, on the 5 clean hosts
      with each modelled artifact injected (from the efficacy harness), and
      the edges one rule gives: **lo = the clean 84th percentile, hi = the
      median with the model injected at 2.0 sones** (no model: old width
      above the new lo; tone bands keep their old edges, lo raised to the
      clean 84th, because clean reads exactly 0 there and the model is a
      pure sine). What the table showed: `presence_db` reads -4.5 to -1.6
      on clean masters against a ramp from -14; `flat_3_8` 0.44-0.55 on a
      ramp ending at 0.55; `umid_db` -8 to -4 on a ramp from -16;
      `upper_db` -12 on a ramp ending at -10. Those four are why
      Vocal Glaze, Presence Haze, Harsh Veil and Broadband Fizz read
      0.5-1.0 on finished masters. The flicker feature is weaker than
      assumed: hash injected at 0.5 sones reads *below* the clean median
      (0.23 vs 0.61), and the real corpus overlaps (masters median 0.34,
      renders 0.83). Applied in `priors_from_evidence` with the rule in its
      docstring. Measured after, `score_probe.py` over the corpus: finished
      masters firing 2/9 -> **1/9** (the service master whose own flicker
      excess is +2.4 dB; Suno Hash at 0.48); references 0/2; the synthetic
      clean bed 0.46 -> 0.03 (no longer fires); the synthetic hash now
      picks Suno Hash (0.23) instead of Echo Sheen; renders firing 2/7
      (Suno Hash 0.36, Sibilance Rattle 0.11). Per-file maximum prior:
      finished masters median 0.40 (was 0.7-1.0 for the presence presets),
      renders 0.53. Nine masters is a small clean sample — the 84th
      percentile of nine is the second-highest file — so widen it before
      tightening any edge. Test suite 323 passed.

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

- [x] **12. Derive the tone target from contemporary commercial music.**
      (Added 2026-09-08. Supersedes the two Done items restatused above.
      Evidence: `BRIGHTNESS-ASSESSMENT.md` §7.) `_REF_SHAPE_DB` is ~6.7 dB
      hot in presence (2–5 kHz) and ~8.5 dB hot in air (6.3–12.5 kHz).
      Bass, low-mid and mid are within ~2 dB and need no change.
      *Not* a hand-edited curve, and not a swap to the published mean
      either — that corpus is folk- and classic-rock-weighted CD masters and
      is demonstrably wrong in the bass for contemporary material (every real
      master measured reads +5 to +8 dB at 100 Hz where it reads −0.6).
      The blocker is sample size: per-track standard deviation in the
      2.5–12.5 kHz mean is 3.7 dB, so **≈55 captures gets the standard error
      under 0.5 dB, ≈150 under 0.3 dB**. There are 13. Item 14 has to land
      first or the corpus will be contaminated.
      *Done when:* the target is regenerated by a script from a captured
      corpus of ≥55 validated contemporary masters, the script and the
      per-track rows are committed, item 13's invariant passes, and the tilt
      gap is re-measured against **captured commercial masters** rather than
      against the service's curve. Do not merge `97609c0` before this.
      **Rewritten 2026-09-08 — the construction above is wrong, and the
      sample-size blocker is not real.** Two problems with it. First, "derive
      the target from captures" repeats the mistake that caused this, in a
      new direction: it replaces one small convenient corpus with another.
      The reason `97609c0` went wrong was abandoning published research for
      whatever data was to hand — the pre-`97609c0` curve came from Pestana
      et al., 772 published recordings, and the right answer to "that study
      is dated" was a newer study, not a vendor's output. Second, ≈55 assumed
      the captures must fit all 29 band values. They must not. The **shape**
      comes from Elowsson & Friberg, 12,345 tracks, at 60 bins/octave, and
      §7.2 verified their published quadratic against their own measured
      curve to 0.26 dB. Captures supply only the contemporary offsets in the
      zones where that corpus is demonstrably era- and percussion-shifted.
      *Measured* (`is_13_enough.py`), correction and its standard error at
      n=13 against the error being fixed: bass +6.28 ±1.17 (target off
      +3.04); low-mid +1.54 ±0.35 (−0.80); mid +0.39 ±0.49 (+0.42);
      presence +0.57 ±0.97 (**+7.07**); air +5.17 ±1.22 (**+7.76**). The
      correction is **6–7× larger than its own uncertainty**, so 13 captures
      already settle it; ≈50 would move the worst zone from ±1.2 dB to
      ±0.5 dB while the live error is 7.8 dB. Do not let that block the fix.
      **Revised done-when:** `_REF_SHAPE_DB` is regenerated by a committed
      script that takes the published curve as the shape and applies
      zone offsets measured from validated captures, with the offsets, their
      confidence intervals and n recorded in the output; the mid and presence
      zones are left at the published shape unless the captures disagree by
      more than their CI; and the tilt gap is re-measured against captured
      commercial masters rather than the service's curve. Item 14 still lands
      first, so the capture set stays clean as it grows. More captures remain
      **DONE 2026-09-08 — but measured only, not heard. Read the last
      paragraph before quoting this.** `scripts/derive_tone_target.py` builds
      `_REF_SHAPE_DB` and `_REF_TOL_DB` from the published shape plus a
      measured correction, writing `docs/tone-target.json` with every band's
      correction, standard error and shrink weight. Verified against captured
      commercial masters by `scripts/tilt_vs_commercial.py`, running the real
      chain over 8 sources twice with only the target changed:
      **mean gap +3.10 → −0.03 dB, absolute mean 4.62 → 2.43 dB, median
      +4.71 → +0.46.** The chain is now unbiased against real records where
      it used to sit 3 dB bright. Target is also smoother than the one it
      replaces (largest step between bands 12.30 → 6.63 dB) and falls
      monotonically above 315 Hz where the old one rose again nine times.
      Two things this exposed, both open. *One:* three sources that were
      already darker than commercial got darker still
      (`couldve-been-stories` −0.70 → −3.46). The bright target had been
      masking how much high end the cleaner removes; with an honest target
      that loss is visible, and it belongs to the cleaning side, not here.
      *Two:* the percussion-invariant slope moved −4.28 → −5.53 against a
      published −4.53. Within the honest ±1.5 dB/oct tolerance and inherited
      from the captures, which read −5.31, but it is the one number that went
      the wrong way.
      **The goal is not met yet.** This item's evidence is entirely spectral.
      The complaint that started the whole investigation was that masters
      *sounded* dull, and nobody has listened to a master made with this
      target. The measurement says Shimmer was 3 dB brighter than commercial
      music while sounding dull, which most likely means the comparison was
      against the service's masters — 7 dB bright — rather than against
      records. That is an explanation, not evidence. **Item 4 is now the
      blocking item, not a nicety:** a level-matched blind listen against
      commercial references decides whether any of this worked.
      More captures remain
      welcome — a handful of non-electronic tracks as a **hold-out test** of
      the finished target is worth more than another twenty inputs.
      **OVERTURNED BY LISTENING 2026-09-09 — see item 4.** Blind, level
      matched, the derived target lost to the retracted service curve on
      **7 of 8 songs** (1 tie), and in the three-way era test the retracted
      curve beat both the derived target and the 1950-2010 average on 3 of
      4 (1 tie). The derived target won nothing. GOALS.md rule 4 says
      listening is final and outranks measurement, so this item is no
      longer done: the target that ships is the one that lost. Do not
      re-derive it from a better corpus before establishing why the
      measured-best curve is the least preferred one.
      **REVERTED 2026-09-09** in `shimmer/mastering.py`; 402 tests pass.
      `_REF_SHAPE_DB` is the curve that won. Read the size of the result
      correctly, because the curves overstate it: the chain applies only
      part of a target, so the ~8 dB gap between these two curves through
      presence and air delivered about **2 dB** of audible change. Measured
      from the judged bench files themselves, the preference is 250 Hz-1 kHz
      **-1.2 dB**, 2-4 kHz **+1.6**, 4-8 kHz **+2.0**, 8-12.5 kHz **+1.7**,
      12.5-20 kHz **+0.6** — less low-mid, modestly more presence and air.
      An earlier reading of this session claimed 7-10 dB; that was the gap
      between the target curves, not the gap heard, and it is withdrawn.
      *Internal check on the verdicts:* the song whose two arms measure most
      alike (the-little-things) is the one scored a tie, so the scores track
      the audio.
      *The conflict this creates, recorded rather than hidden:* GOALS.md
      lists "not a clone of any service's house sound" as an anti-goal and
      this curve is one service's median. Reaching the preferred delivered
      sound from the derived curve needs roughly this much correction
      through the top anyway, so what ships is the measured preference, not
      an endorsement of the vendor. **The open job is a target that earns
      this shape from evidence.** Do not treat the revert as that job done.
      *What the audit found so far:* the derivation takes its shape from the
      published curve and corrects it toward 13 captures. The published
      curve is much darker at the top than the captures are (8 kHz -14.4 vs
      -10.3; 10 kHz -16.6 vs -10.6), and the correction that would close
      that gap is smoothed over an octave before it is applied, which
      systematically under-corrects at the top band, where there is no
      higher neighbour to average with and the raw correction is largest
      (10 kHz raw +5.93 applied +4.74; 12.5 kHz raw +6.01 applied +4.38).
      The shape is therefore inherited from the paper and the captures are
      only allowed to move it part of the way. That is the mechanism to
      examine first when the target is rebuilt.
      *Second defect, found by the revert and fixed the same day:*
      `make_bench_set.py` defined `DERIVED = M._REF_SHAPE_DB.copy()`, so the
      name meant "whatever ships today" rather than a fixed curve. The
      moment the shipping target changed, the tone and era sets began
      comparing a curve against itself — a verification run measured
      **0.00 dB in every band** between the two arms. Any round built after
      a target change would have been a null test that looked like a real
      one. The three historical curves are now pinned literals and a
      separate `SHIPPING` constant carries the live target; arms that mean
      "as it ships" use that. Verified after the fix: the reverted chain
      delivers 250 Hz-1 kHz **-1.36 dB**, 2-4 kHz **+2.00**, 4-8 kHz
      **+2.76**, 8-12.5 kHz **+2.63**, 12.5-20 kHz **+1.13** against the
      derived curve — the preferred direction in every band.
      *A control worth keeping:* run a finished commercial master through
      the chain and require it to come out close to unchanged. Both targets
      currently pull its top end down relative to the mids, the shipping one
      by ~2.4 dB and the restored one by ~2.0 dB, so neither passes cleanly
      and this is a live defect independent of which curve is used.

- [ ] **13. Put the percussion-invariant slope in the test suite.**
      (Added 2026-09-08.) Elowsson & Friberg §4.2/§6.3: the PSD slope from
      89 Hz to 4.5 kHz is 4.53 dB/octave across all 11 percussion groups,
      between-group standard deviation 0.055 dB/oct. It is the one published
      figure that does not inherit its corpus's genre or era bias, so it is a
      free regression test on any target we ship. Current readings: target
      −4.28, service masters −4.47, captures −5.18, Shimmer output −4.90.
      Caveat to encode with it: it is a two-point slope and is **blind to a
      symmetric smile** — the current target passes it while being +7.4 dB at
      100 Hz and +1.1 dB at 4 kHz against the published curve. It checks
      tilt, not shape, and the test must say so or it will be over-trusted
      exactly the way `purity` was.
      *Done when:* a test asserts the invariant on `_REF_SHAPE_DB` with a
      stated tolerance, and its docstring states what it cannot catch.
      **Scope cut the same day it was written — reason:** seven independent
      reviews showed this test is far weaker than the caveat above admits,
      and as originally specified it would have shipped a metric that cannot
      fail. Two findings. (i) The ±0.055 dB/oct figure is **not a
      tolerance**: it is the SD between eleven group *means* of ~1122 tracks
      each, and it is the argmin of a 2-D endpoint search. Per-track SD
      measured here is 0.744 dB/oct on the service masters and 1.085 on the
      captures — 13 to 20 times larger. Against an honest tolerance the
      target (−4.281), the service masters (−4.404) and the paper (−4.412)
      are indistinguishable. (ii) The blindness is worse than "a symmetric
      smile": the target's error against the paper is +9.36 dB at 89 Hz and
      +10.10 dB at 4.5 kHz, so the secant sees 0.74 dB while the RMS
      residual across that span is 4.82 dB, and the *pre*-`97609c0` target
      scores −4.545 — closer to the paper than the current one — while
      sitting ~4.9 dB above it everywhere. This is `purity` again (§2.5).
      **Revised done-when:** keep it only as a coarse tilt check at ±1.5
      dB/oct, and only if the test name and docstring say it cannot detect a
      level or shape error. If that is not worth writing, do not write it —
      a test this weak is worse than none, because it will be cited.
      **DEFERRED 2026-09-09 — reason:** taking the revised done-when at its
      word, it is not worth writing. At an honest ±1.5 dB/oct the test
      passes the published curve (−4.41), the service masters (−4.40), the
      captures (−5.31), the retracted target (−4.28) and the derived target
      (−5.53) alike. It separates nothing in the range we care about, and
      the one thing it would catch — a wildly tilted curve — is already
      caught by `references.gate()`, which is derived from real masters and
      does discriminate. Shipping it would put a second metric-that-cannot-
      fail in the suite next to the one that cost this project months.
      Revisit only if a target is ever proposed whose tilt is in question;
      the check is three lines and lives in
      `scripts/tone-evidence/check_new_target.py` meanwhile.

- [x] **14. Make the References tool's report trustworthy.**
      (Added 2026-09-08.) It reported "8.4 dB darker" as a headline from a
      plain median over 15 captures, two of which were broken (−50.6 and
      −43.6 dB at 10 kHz, against a 1st-percentile of −29.1 across 317
      known-real masters). Three defects in `shimmer/references.py`:
      (a) no validity gate — derive one from the known-real distribution, not
      from agreement with the target, or it will reject captures for
      disagreeing; (b) capture level and per-band SNR are discarded, which is
      exactly the evidence needed to tell a broken capture from a dark one —
      the note says loudness is dropped because playback normalisation alters
      it, which is a reason not to trust it as *loudness*, not a reason to
      throw it away; (c) `report()` states a verdict with no uncertainty and
      no correction for the measured −1.35 dB short-excerpt bias (worst
      −4.45 dB; up to 5.71 dB spread between 30 s windows of one track).
      *Done when:* the report states n, a confidence interval and the
      excerpt-bias correction; broken captures are rejected with a reason
      shown on the page; and re-running it on the existing 15 reproduces the
      13/2 split.
      **DONE 2026-09-08.** `shimmer/references.py`, 12 tests in
      `tests/test_references_gate.py`, 367 pass. What shipped:
      `gate()` derives bounds from `docs/tone-reference.json` at run time —
      309 masters, 1st percentile: 10 kHz ≥ −29.2 dB, 16 kHz ≥ −40.2 dB,
      4–16 kHz slope ≥ −14.0 dB/oct — **not** from the tone target, and a
      test asserts a curve 8 dB darker than the target still passes, because
      a gate that rejects disagreement can only ever confirm the target.
      `rejection()` returns a plain-language reason, stored on the row at
      save time and shown on the page. Level is recorded (`rms_dbfs`,
      `peak_dbfs`, reset per track) — the missing evidence that would have
      diagnosed the two broken captures. The report gives n, se and a 95%
      interval, applies the −0.6 dB excerpt correction while carrying its own
      ±0.4 dB, and calls a difference "unclear" rather than a finding when
      the interval spans zero. *Verified on the live library:* 23 captured →
      **13 commercial, 8 controls, 2 rejected**, the same two, for the stated
      reason; −7.92 raw, −7.33 corrected, 95% CI [−9.51, −5.14].
      **Two defects this work found.** (a) *Controls were being pooled with
      evidence.* Captures of our own files played back — the chain check —
      are mostly masters from the service the target came from, so counting
      them dragged the difference from −7.9 dB to −4.7 dB. `is_control()`
      separates them by matching the label against `sources/`. (b) *The
      remove button would have deleted the wrong track.* Filtering the shown
      list while `delete(index)` indexes the file is silent and destructive;
      found in the browser, fixed by listing every row with a status, and
      pinned by a regression test.
      **Two corrections, same day.** (i) The −1.35 dB excerpt figure is weak
      — n=8, se 0.78, 95% CI [−3.19, +0.50], and the captures' brightness
      correlates with duration the *wrong* way (r = −0.362). Use
      **−0.6 ± 0.4 dB**, which is what the on-chain control measures.
      (ii) The capture path is now validated end to end and needs no further
      doubt: eight service masters that exist on disk were played through
      Spotify and captured, giving **−0.57 dB ± 0.38 over 2.5–12.5 kHz with
      a flat per-band difference** (`scripts/tone-evidence/spotify_control.py`).
      That closes the "maybe Spotify colours it" objection. Re-run that
      script after any change to the capture path — it is the regression test
      for this whole feature, and it costs one playback.

---

- [ ] **15. Make the hash stage remove hash.** (Added 2026-09-08 after
      round 4, where "still has shimmer" was the author's verdict on two
      files after either treatment, and the untouched render beat Suno Hash
      at 100 % on a hashed track.) *Done when:* the efficacy harness reads
      Suno Hash, or its replacement, above 50 % on the hash model at 0.5
      and 2.0 sones with net cost under the budget's ceiling, and a
      listening round on real hashed renders agrees.
      *Measured so far, 2026-09-08 (two clean hosts, hash at 0.5 sones):*
      - Stage ablation of Suno Hash: core ShimmerStage, denoise, DeHarsh and
        DeRes each read **0.00** efficacy alone and 0.01 together; the
        FlickerTamer alone 4-7 %, at maximum settings (threshold 0, slope 1,
        cap 40 dB) 6-10 %; with its transient gate forced open 4-17 % at
        seven times the cost. The gate is not the limiter.
      - The tamer's own diagnostics: with hash present the band-mean
        envelope's detrended spread is 2.2 dB against 1.8 without (one
        host) and unchanged (the other), so it barely sees the hash; on the
        reference "Hey" it already attenuates the host's own dynamics by
        2.8 dB mean, 18 dB peak. It ducks a sub-band when the sub-band's
        total moves, which is not what makes hash audible.
      - What real hash is, on the fine grid (1024/256, 4.5-12 kHz, the
        detector's hot 5 s): on the two `the-little-things` files
        (flicker excess +2.4 to +2.6) the band-mean envelope moves
        **2.0-2.6 dB rms in every rate band from 2 to 50 Hz**, with no
        peak in 10-50 Hz (modulation energy there sits *below* the 1-8 Hz
        level), sub-band coherence **0.78-0.81** and per-bin coherence
        0.49-0.53; the reference "Hey" reads 0.3-0.7 dB rms, coherence
        0.51 / 0.06. Side modulates as much as Mid. So real hash is a
        coherent, aperiodic movement of the whole band, not the fast
        periodic AM the stage was built for; the "10-50 Hz" premise in
        presets.py and finepass.py is not what the corpus contains. The
        harness's model (gated noise at 20 Hz) matches the real thing in
        rms per rate band (1.7-3.4) and coherence (0.89), so the tamer's
        failure on it should generalise; the model's periodicity does not
        match and should be replaced by an aperiodic gate before more
        design is done against it.
      - One replacement tried and rejected: a per-bin gain keyed on how
        much of the bin's envelope variance the band-coherent flicker
        explains. **2-18 % efficacy at tilt 0.6-22 and 0.03-0.29 sones on
        the clean host alone.** Music in that band moves with the band
        too (cymbals, transients), so coherence does not separate hash
        from music either.
      - Stem-split cleaning (the review's own recommendation) tried and
        rejected, same day: Demucs `htdemucs` on host and render, hash at
        0.5 and 2.0 sones, two hosts. The hash does not land in one stem:
        per-stem audible footprint on "Hey" at 2.0 sones is drums 6.5,
        residual 1.5, bass 1.3, other 1.0, vocals 0.4 against 2.0 injected
        — the separator reacts to the hash and redistributes music, so the
        drums stem alone carries more audible change than the whole mix.
        Cleaning the hash-bearing stems with the strongest existing
        cleaner and remixing: best **39 %** (Deep Scrub on drums, "Hey",
        tilt 7.4), Suno Hash at 200 % on drums 10-17 %, everything on the
        other host **≤ 8 %**. Stems are a route for *protecting* vocals
        while cleaning, not for finding the hash.
      - Per-bin spectral subtraction keyed by the band's coherent gate
        (off-phase floor per bin, on-phase excess subtracted in power),
        tried the same day on both the periodic model and an **aperiodic
        model** (band noise gated by a low-passed random envelope, the
        measured shape of real hash). It is the first route with real
        efficacy: **52-61 % of the aperiodic hash at 2.0 sones, 26-35 % of
        the periodic**, on both hosts. But it costs **0.19-0.47 sones on
        the clean host alone** (budget ceiling 0.10) with tilt 7-14 on the
        transient-rich master, because the on phases it subtracts are
        where drum hits live too. Every guard that cut the cost cut the
        efficacy with it: the fine pass's transient gate 0.47 -> 0.24
        sones but 61 % -> 17 %; a 31-bin median across bins (so partials
        are not subtracted past their neighbourhood) 0.47 -> 0.17 sones
        but 61 % -> 18 %; both together 0.07 sones and **2 %**. Efficacy
        and cost move together along this axis: the stage cannot tell
        hash from cymbals and hits by level, gate or spectral shape.
      *What follows:* four routes measured — band-envelope ducking (the
      shipped stage), per-bin coherence weighting, stem separation,
      per-bin gated subtraction — and none separates the hash from
      noise-like music with hand-designed statistics. The two share
      level, coherence and flatness. What is left is a learned separator
      trained on (clean host, host + hash) pairs, which the harness can
      now generate in bulk (88 MediumNeutral masters as hosts, the
      aperiodic model), judged by the same harness. Its validity rests
      entirely on the model being the real artifact, so the step before
      any training is a listening check: does the aperiodic model on a
      clean master sound like Suno hash to the author? If it does not,
      the model must be refit from real renders first (the modulation
      spectrum and per-bin coherence measured above are the constraints).
      This is the product's core problem and the largest open item.
      *Round 5 built for that listening check:* `listening-test/round-5`,
      `scripts/make_round5.py`, `KEY.json` gives each file's readings.
      Side finding from building it: on the reference "Hey", 2.0 sones of
      modelled hash reads **-2.6 dB** on `flicker_excess_db` (0.5 sones
      -1.8) while on "Alive Again" the same injection reads +3.5 / +0.9.
      "Hey" is transient-rich (the fine-pass gate is held 30 % of the
      time on it) and its own body flickers more than its brilliance, so
      the hash feature cannot see plainly audible hash on that kind of
      material. The prior for Suno Hash is therefore blind on some music,
      not just uncalibrated; item 10's edges do not fix that, and the
      feature itself needs a transient-aware measure before it can be
      trusted as evidence of absence.
      *Followed up the same day, and it is worse than a gate:* with
      2.0 sones injected on "Hey" the brilliance band's measured flicker
      **falls** (5.2 dB clean → 4.1 → 3.9), whatever transient gate is
      used (full-band 6 dB, high-band 6 or 9 dB, 150 ms hold; gated share
      0 → 0.40 makes no difference), because added noise fills the gaps
      in a band that already moves with the music and makes its level
      steadier. The feature is not monotonic in hash on dynamic
      material. Four replacement statistics were then tested for
      monotonicity on three hosts at 0.5 and 2.0 sones, both models
      (sub-band coherence, per-bin coherence, coherence excess over the
      body, 10-50 Hz modulation share): **none rises with hash on "Hey"**
      (all fall: its own drums drive the band's coherence to 0.90
      clean), all move only at 2.0 sones on the steadier hosts and drift
      the wrong way at 0.5, and on the real corpus coherence does not
      separate the hashed files (0.78-0.81) from clean masters (up to
      0.92). Hash *detection* on dynamic material is beyond hand-built
      envelope statistics for the same reason its removal is: the host's
      own noise-like content shares every statistic tried. The same
      learned model that would remove it is what would detect it, and
      both wait on round 5.
      **Round 5 judged 2026-09-08.** The author, on the mixed files and on
      the model alone next to what the prototype pulls out of two real
      renders: "yes, good examples of shimmer." The aperiodic model is
      accepted as the artifact for measurement and training purposes;
      the harness numbers above stand as measurements of the real
      problem. The next build is the learned remover and detector trained
      on clean-master-plus-model pairs, judged by the harness on held-out
      hosts and by a listening round on real renders.
      **First learned remover, 2026-09-08 evening.** `scripts/hash_learn/`:
      1462 pairs of 3 s from 43 catalogue masters that read hash-free
      (`docs/host-census.json`; 88 MediumNeutral masters, 43 below the
      0.5 dB floor), aperiodic model at band SNR -25 to -3 dB, a 129k-
      parameter convolutional mask over 2-16 kHz on the 1024/256 grid,
      30 epochs in 9 minutes. Training is capped and throttled after the
      first run coincided with a machine crash (peak 0.84 GB of GPU
      memory, ~57 % utilisation, 69 C max; the trainer's docstring lists
      the limits). *Harness on the two held-out hosts, aperiodic hash:*
      Alive Again **28 % / 18 %** at 0.5 / 2.0 sones, net music cost
      0.008 / 0.000; Hey **46 % / 69 %**, cost 0.060 / 0.016; control
      cost on the clean hosts 0.006 / 0.078, both under the 0.10 ceiling.
      On the periodic model it was not trained on: 37-57 % at 0.5 sones,
      but -7 % with tilt 10.9 on Alive Again at 2.0 — it does not
      generalise to a modulation it never saw, which is the argument for
      training on both. Against every prior route this is the first that
      removes a real share (Suno Hash 12 %) at an acceptable price (the
      subtraction prototype needed 0.19-0.47 sones of music for 52-61 %).
      *Round 6 built for the real test:* `listening-test/round-6/blind`,
      six Suno renders, untouched vs the network at 100 %, blind;
      `renders/*-removed.wav` is what it took. Hearing model on the real
      renders, cleaned vs untouched: missing 0.012-0.218 sones, tilt
      0.04-0.36 — the-little-things (the hashiest, +2.6 dB) has the most
      taken out (0.218), which is either the hash going or music going,
      and only the listener can say which. The weights (1.6 MB) are not
      committed until round 6 says they earn it; the plan if they do is
      inference in numpy/scipy so users install nothing.
      **Round 6 judged 2026-09-08** (`round-6/blind/SCORES.json`). Six
      renders: cleaned letter preferred on **1** (algorithms-lure:
      "shimmer reduced, music intact"); **4** "too close" to tell apart
      (falling-for-you, kindling, the-little-things, we-were-meant), music
      intact on all four, shimmer marked "gone" on two of them and
      "reduced" on two — read that as the difference being below what a
      careful listener resolves at 100 %, not as the hash being gone;
      **1** neither (leave-the-world-behind: "shimmer is so bad", the
      network changed 0.025 sones and did not touch it). Verdict: **does
      no harm on real renders; mostly too gentle to hear at 100 %.**
      Hearing model agrees: 0.012-0.054 sones taken on five of six. One
      note to chase: on kindling "a higher frequency sound sitting in the
      back" — either a fixed line the notch plan would take or a residue
      of the mask. Next: the same renders at 2-4x mask strength (the
      inference supports it), judged by the hearing model first and a
      round after; and training on both hash models and a wider level
      range, since the harness showed it does not generalise to the
      periodic one at high level.
      *Strength sweep, same evening:* the mask is not a knob. Scaling it
      2x, 3x, 4x on the held-out hosts sends harness efficacy to -0.06,
      -0.33, -0.68 (Alive Again) and -0.18, -1.04, -1.55 (Hey) with
      `added` rising — past its trained range it invents content rather
      than removing more; on real renders tilt climbs 0.09 → 0.44 on
      kindling. More removal has to come from training, not from scaling:
      both hash models mixed, louder hash (band SNR up to -1 dB), 2500
      pairs, 40 epochs. Kindling's "higher sound in the back" is a fixed
      16 kHz line (7.3 dB, 52 % duty) that the product's notch plan takes
      first; round 6 ran the network alone, so it stayed.
      **Second model, 2026-09-09 00:01** (`masknet2.pt`; 2494 pairs, 70 %
      aperiodic / 30 % periodic hash, band SNR to -1 dB, 40 epochs, one
      stop-and-resume at epoch 10, peak 0.84 GB, 69 C max). Held-out
      harness, aperiodic 2.0 sones: Hey **62 %**, Alive Again **9 %**;
      periodic 2.0 sones: Hey **67 %** (model 1: 57 %), Alive Again
      **-20 %** (model 1: -7 %). It takes more music: 0.150 sones on clean
      Hey (model 1: 0.078; ceiling 0.10). Bolder and better on the loud
      periodic case, costlier, and no better where it was weakest. *On the
      real renders* the two models take nearly the same amounts (round-6
      vs round-7 keys): the-little-things 0.22 → 0.33 sones, every other
      render within 0.015 — and **leave-the-world-behind, the render the
      author calls "so bad", 0.025 → 0.031**: neither model acts on it.
      Round 7 is built (`listening-test/round-7`) but not worth ears until
      that is understood; the next measurement is where that render's
      shimmer sits in frequency, since the network was only taught
      4.5-12 kHz.
      *Measured 2026-09-09:* flicker depth (dB rms, 2-50 Hz) per
      half-octave band, hot 5 s. **leave-the-world-behind: 3.6-5.1 dB in
      every band from 1 kHz to 16 kHz**, and its service master the same
      (3.0-4.6), so the service did not remove it either. the-little-things:
      3.8-4.3 below 4 kHz rising to **6.0-7.9 in 5.6-11.3 kHz** — the band
      the model was taught. kindling: 5.2-8.1 from 5.6 kHz up. Clean
      masters ("Hey", Alive Again): 1.1-1.6 above 2 kHz, 2.7-4.7 at
      1-1.4 kHz. So "shimmer" as the author hears it on that render is
      **broadband from 1 kHz up**, not the 4.5-12 kHz hash the presets, the
      detector's flicker feature and both learned models are built
      around; the model could not act on it because it never looks there.
      The third model widens the band to ~1.5-16 kHz with a broadband
      hash model in the training mix. The trade is the vocal region, so
      the clean-host cost is the guard, and a listening round on this
      render is the test.
      **Third model, 2026-09-09 00:39** (`masknet3.pt`; 2494 pairs on
      `hash_data3`, band 1.5-16 kHz, context 0.8-20 kHz, half the pairs
      carry the wide-band hash; 30 epochs, val 0.50 → 0.41, peak 1.13 GB,
      68 C max). Held-out harness, 2.0 sones: aperiodic Hey **81 %**
      (model 2: 62 %), Alive Again **17 %** (9 %); periodic Hey **82 %**
      (67 %), Alive Again **58 %** (-20 %); wide hash Hey 37 %, Alive
      Again 23 %. Control cost on clean Hey **0.064** (model 2: 0.150;
      ceiling 0.10), Alive Again 0.033. Best of the three on every synthetic
      case and under the ceiling. *But on leave-the-world-behind it still
      does nothing:* what it removes sits at -21 to -32 dB below the band
      from 4 kHz up and below -37 dB under 4 kHz; the band levels move by
      0.3 dB at most; flicker depth per half-octave band is unchanged to
      0.1 dB in every band from 1 to 16 kHz (model 2 was the same). The
      network now looks at 1.5-16 kHz and finds nothing hash-like there.
      So the wide band was not the missing piece. Whatever the author hears
      on that render is not what the aperiodic, periodic or wide-band hash
      models generate, at any band. Next: build the pair set from the
      render's own residual (the thing the flicker measurement finds),
      not from a synthetic hash, or listen to the render's 1-4 kHz
      residual first and describe it before modelling it. Model 3 is the
      right one for the round-8 renders regardless (efficacy up, cost
      down).
      **CORRECTION 2026-09-09 — the "it does nothing" reading above is
      withdrawn; the instrument was wrong, not the model.** Flicker depth is
      measured across a whole band the music dominates, so material 36-56 dB
      below the source cannot move it however audible it is. The residual is
      the instrument with power here, and by the bench's own
      song-correlation scale (0.001-0.115 = removed material; 0.16-0.52 =
      the song through a filter) every remover removes junk and only junk:

      | residual | correlation | below source | energy |
      |---|---|---|---|
      | leave-the-world-behind, model 3 | 0.084 | 36 dB | 95 % in 4.5-12.5 kHz |
      | leave-the-world-behind, model 2 | 0.078 | 38 dB | 100 % in 4.5-12.5 kHz |
      | the-little-things, model 2 | 0.009 | 50 dB | 100 % in 4.5-12.5 kHz |
      | kindling, model 2 | 0.009 | 56 dB | 100 % in 4.5-12.5 kHz |

      None has energy below 2 kHz, and the author confirms hearing shimmer,
      high-pitched sheen and pops when auditioning the removed part. The
      question is therefore not whether the stage removes hash — it does,
      cleanly — but whether it removes **enough**. That is under-removal,
      and it has different fixes than mis-removal.
      *The clean round's four ties are explained by this, not evidence
      against it:* material 37-56 dB down, in a masked band, judged on the
      loudest 30 s, is a test with no power. Rebuilt as `quiet-*` sets on
      the passage each song's own residual says is most exposed (+6.6 dB
      exposure on average, +20.1 dB on kindling), asking "which still has
      the shimmer" rather than "which sounds better".
      **Defect found and fixed 2026-09-09** in `hash_learn/infer.py`:
      `g = 1 - strength*(1 - g)` was unclamped, so any strength above 1
      drove bins negative wherever the mask read below `1 - 1/strength`,
      flipping their phase and writing the artifact back inverted instead of
      attenuating it. Every strength above 1.0 measured before this date
      carried it. Now clipped to [0, 1].
      *Strength sweep on model 3, clamped, measured by residual:* the model
      is very timid. On leave-the-world-behind it takes -24.3 dB of the
      4.5-12.5 kHz band at strength 1 and only -12.5 dB at strength 8, for a
      band-level drop of 0.15 dB and 0.70 dB; on kindling, -36.2 dB and
      -24.1 dB for a 0.01-0.07 dB drop. Strength is not the limiting factor
      and there is large headroom before the cost could be audible.

- [x] **16. Where fixed tones sit in the corpus.** *Done when:* every
      corpus file is scanned with the app's own tone scan and notch plan,
      and the counts are recorded by band.
      **DONE 2026-09-12.** `testing/scripts/tone_census.py` (local working
      script, gitignored, next to its data), run on `main` at c1d18e0 over
      all 24 files in `sources/` and `assets/reference/`. The scan flags 134
      candidate lines: 49 at 2-3 kHz in 22 files, 12 at 3-4 kHz in 11 files,
      18 at 4-8 kHz, 19 at 8-16 kHz, 36 at 16-24 kHz. The notch plan cuts
      13: 7 at 16-24 kHz, 4 at 8-16 kHz and 2 at 3-4 kHz — and those two are
      one tone, 3.51 kHz in *Alive Again*, present in the Suno render and in
      the service master made from it. Nothing is cut at 2-3 kHz. Both
      finished reference masters also produce 2-3 kHz candidates (3 of the
      49), so many candidates there are music, and the below-3 kHz rule
      (>= 10 dB, >= 90 % of the time) is doing its job.
      *What follows:* in this corpus, "piercing 2-4 kHz resonances" are not
      fixed tones. If they exist they move with the music, and the tool for
      them is dynamic EQ (ARCHITECTURE.md §15 Step 6), not a notch.
- [x] **17. Does the de-clicker remove clicks?** *Done when:* a click
      model and a crackle model exist that are not shaped to the
      de-clicker's own definition, and the de-clicker is measured alone
      against them on hash-free hosts.
      **DONE 2026-09-12 (measurement).** `shimmer/artifacts.py` gains
      `clicks` (isolated pops, 0.1-3 ms, broadband above 200 Hz, about 1.5 a
      second; some longer than the de-clicker's 2 ms limit and all with
      energy below its 2 kHz band, on purpose) and `crackle` (micro-clicks
      that follow the host's 4-10 kHz envelope, up to 80 a second).
      `tests/test_click_models.py` pins their shape.
      `scripts/efficacy_harness.py --declick 0.5,1.0` measures the
      de-clicker alone, as the pipeline calls it; results in
      `docs/efficacy-declick.json`, 5 hash-free hosts, 8 s clips.

      | de-clicker | pops 0.5 sones | pops 2.0 | crackle 0.5 | crackle 2.0 |
      |---|---|---|---|---|
      | amount 0.5 | 15 % | -15 % | 48 % | 37 % |
      | amount 1.0 | 7 % | -1 % | 43 % | 36 % |

      On a clean host alone it takes 0.104-0.107 sones of music, at the
      budget's 0.10 ceiling. Its own report on the first host counts 450-870
      "clicks" per 8 s clip (55-110 a second) where about 12 pops were
      injected: it treats ordinary transients as clicks and misses the real
      pops. The plain energy reading agrees on direction (pops at 2.0 sones:
      1.0-1.2 of the injected energy left, so nothing removed; crackle:
      0.64-0.82). At 0.5 sones it reads above 1, because the de-clicker's
      own changes to the music differ between the render and the clean host
      by more than the faint artifact.
      *Limits:* both are models, not captures; no real AI click is in the
      corpus yet. One listener has not yet heard any of this.
      *What follows:* the rebuild's de-clicker (§15 Step 6) must beat these
      numbers while taking under 0.10 sones from a clean host, before it
      ships.
- [ ] **18. Are the louder Loudness target choices clean?** *Done when:*
      the same baseline master at Streaming, Loud and CD / Club is judged
      blind, at matched level, on every song, with the listening check
      passed and the gear written down.
      **Built 2026-09-12, not yet judged.** Baseline = `main` at c1d18e0 with
      the Master tab's defaults (Generic preset, tone match Medium, tilt
      Neutral, WAV 24-bit, ceiling -1.0 dBTP), rendered by
      `testing/scripts/baseline_render.py`; files and numbers in
      `testing/baseline/` (local). Measured on the 8 bench songs, true peak
      read per channel:

      | target | LUFS reached | limiter | samples above the soft-clip knee | peak-to-loudness |
      |---|---|---|---|---|
      | Streaming -14 | -14.00 | 0.0 dB on 8/8 | 0-0.04 % | 10.1-12.8 dB |
      | Loud -11 | -11.00 to -11.07 | 0.0 dB on 6/8; -0.41 and -0.59 | 0.02-0.63 % | 9.3-10.1 dB |
      | CD / Club -9 | -9.01 to -9.25 | 0.0 to -0.94 dB | 0.5-2.3 % | 7.9-8.3 dB |

      The louder choices get there mostly through the soft peak shaper (a
      gentle clipper), not the limiter. At CD / Club it touches up to 2.3 %
      of samples; if the louder choices sound worse, that is the first
      suspect. For scale, the service masters measure about -10 LUFS with a
      peak-to-loudness ratio near 10 dB (recorded 2026-09-12, sample
      peaks), close to where Loud lands.
      Sets: `listening-test/ab/loud-*` (8), built by
      `testing/scripts/build_loud_sets.py`. The window is the loudest 30 s
      of the CD / Club render, where the shaper works hardest, and all
      three arms are cut from that same window. The bench matches their
      level (-11.2 to -13.5 LUFS).

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
  - Golden-value tests **DONE 2026-09-08**: `tests/test_perceptual_golden.py`
    pins all 24 standard-mandated constants to their cited values (Kabal
    section, equation or appendix function named per constant), the
    critical-band table, the spreading normalisation at three bands, the
    calibration tone's loudness (30.288 sones, a full-scale 1019.5 Hz sine
    at 92 dB SPL), and the model's three outputs on four fixed signals to
    0.2 %. Any of the eight mutations that survived before now fails.
  - Level matching **DONE 2026-09-08**: `measure_damage` scales the test
    to the reference's RMS (mono mix) before the ear model; the gain is
    reported as `level_gain_db`, and `level_match=False` restores the old
    behaviour. Cited: Kabal §2.4, the loudness mapping depends on absolute
    level; §G.1, the level adaptation rescales the reference toward a
    quieter test, and AvgLinDist compares that rescaled reference with the
    raw one; and his mean-removal experiment gain-aligns the test to the
    reference. Measured: a pure -3 dB gain read **13.6** on `lin_dist`
    before (a -6 dB shelf reads 20.6) and reads exactly 0 after; the shelf
    and noise cases move by under 6 %. `calibrate_budget.py` re-run after:
    implied SONES_PER_DB 0.093 / 0.083 / 0.015 per song, median 0.083,
    Suno Hash cost 0.060 / 0.036 / 0.038 / 0.039 — the same figures
    budget.py already documents, so the flat-allowance decision and its
    constants stand; the clean control still earns a zero budget.
    Remaining preconditions: the budget limits removal without checking
    what survives (item 6's harness is the instrument for that check), and
    its constants are fitted on four songs.
- The per-section budget envelope.
- UI implementation against the settled labels, including four existing bugs
  the naming panel found.
  - Added 2026-09-08: remove the Single File tab's "Second pass" tile and
    its pass-plan flow (`single.js`: `ensurePlan`, `lastFollowUp`, the
    `ctx.followUp` gating of the tone auto-apply), which are dead now that
    item 8 made the flow one pass. Also the "match %" copy, which item 11
    says was written for the old score's range.
- Re-master the catalogue from source, verified against the corpus.
