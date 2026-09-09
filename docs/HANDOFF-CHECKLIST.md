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

- [ ] **2. Re-measure the tilt gap on the MediumNeutral pairs.**
      *Done when:* one number with a spread, measured against a
      settings-consistent reference, replacing "11 dB against a mixed
      reference." 30 pairs available. **This was dropped once; it is needed
      because the documents will quote it.**

- [ ] **3. Preset harness — all 19.**
      *Done when:* a script produces the full damage matrix, a committed
      cached result, and tests asserting *relations* (clean material damages
      less than hashed; monotonic in strength; surgical group below broadband
      group) rather than invented thresholds. **Also dropped once.** It is the
      acceptance criteria the next model builds against, and it is what would
      have caught the two hand-found defects.

- [ ] **4. One listening round.**
      *Done when:* current chain vs fixed chain vs reference, level-matched
      and blind, judged by the author. Only he can close this. Both previous
      rounds changed the diagnosis.

- [ ] **5. Fix the verified score. (Highest-value single change.)**
      *Done when:* a preset can no longer score well by removing a lot.
      `final = 0.8 x verified + 0.2 x prior`, and `verified = benefit x purity`
      where purity is a mask-location ratio, not a measurement. This one
      function is the root of: Deep Scrub being selected (its *evidence* prior
      is median 0.28 and never the highest on 25 tracks — it wins on the
      score), the "97% was noise" claim, and the detector recommending
      cleaning for finished commercial masters at 80% confidence. Fix it and
      Deep Scrub demotes itself with no policy needed.

- [ ] **6. Measure efficacy, not just cost. Then re-judge every preset.**
      *Done when:* the harness reports BOTH "did the artifact drop" and "what
      did it cost", for all 19 presets, using an artifact measure that is not
      the detector's own prior. `scripts/preset_harness.py` does the shape of
      this but currently measures efficacy with `priors_from_evidence`, which
      is the component already shown to be miscalibrated — so the numbers are
      circular. **Everything built before this measured cost alone**, which is
      backwards for a repair tool and made the presets look surgical when
      several are inert.

- [ ] **7. Composite preset: handle 3+ artifacts in one pass.**
      *Done when:* a track showing several artifacts gets one `Params` built
      from the specific stages those artifacts need, instead of either two
      sequential presets or Deep Scrub. **56% of tracks (14/25) fire three or
      more artifacts; the median is 3 and the max is 8.** The tool runs at
      most two presets, and its designed answer for "many" is Deep Scrub —
      the most damaging preset measured. Check first whether stages compose
      cleanly; Deep Scrub also widens bands and runs two iterations, which
      suggests a simple union was found insufficient.

- [ ] **8. Retire the routine second pass.**
      *Done when:* the automated flow is one pass by default. Measured: on
      three multi-artifact tracks, cleaning revealed **no new artifacts**
      (one marginal hit at exactly the 0.40 threshold), but it **raised other
      priors** — suno_hash 0.80 -> 0.90, laser_whistle 0.70 -> 0.85. These
      priors are relative measures, so removing energy in one band inflates
      the others. The second pass is therefore partly responding to a number
      the first pass created. Any genuine need for iteration belongs inside a
      preset (`iterations`), where it is covered by one damage measurement.

- [ ] **9. The four documents.**
      - `GOALS.md` — goal, anti-goals, decision rule, frozen corpus
      - `IMPLEMENTATION.md` — the PRD: what to build, in order, with
        executable acceptance criteria
      - `STYLE.md` — the house rules currently scattered in docstrings
      - `PITFALLS.md` — every wrong turn taken here, so it is not retaken

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
- The per-section budget envelope.
- UI implementation against the settled labels, including four existing bugs
  the naming panel found.
- Re-master the catalogue from source, verified against the corpus.
