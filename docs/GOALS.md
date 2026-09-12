# What Shimmer is for

Written 2026-09-09 from the author's own statement of the goal. Where a line
is inferred rather than stated, it says so — correct those rather than
assuming they were agreed.

---

## The goal

**Two jobs, in this order.**

1. **Clean up the artifacts AI music generators leave behind.** Pops,
   crackles, shimmer, sheen — the faults people actually complain about in
   the Suno and AI-music communities, on Reddit and in blogs. These are the
   reason the tool exists. No other tool does this.

2. **Master to the same standard as a modern mastering tool, using better
   algorithms.** Not "good enough for AI music." The same standard, and the
   goal is a better result than the automated services reach, because the
   algorithms are better rather than because the material is easier.

Artifact repair is the product. Mastering is table stakes — but table stakes
still have to be met, and met properly.

## What that means in practice

**For the cleaning half.** The fault list is set by what users report, not by
what is convenient to detect. If people complain about a fault, it belongs on
the list whether or not there is a neat measurement for it. A preset that
measures well and removes nothing people can hear has not done the job.

**For the mastering half.** The reference is finished commercial music by
other artists — the material a listener hears next to a Shimmer master on a
streaming service. Not the output of any one automated service. A service is
a competitor's opinion, not a standard, and §7 of `BRIGHTNESS-ASSESSMENT.md`
records what happened when one was used as one.

## Anti-goals

*Inferred from decisions made so far. Correct anything here that is wrong.*

- **Not a DAW, mixer, or creative effects box.** Shimmer finishes a render.
  It does not replace the tools used to make one.

  *Corrected by the author, 2026-09-12:* Remix stays, and it works as it
  does now. Making a render recognisably yours is part of the goal.
- **Not loudness-first.** Streaming normalises, so winning on loudness wins
  nothing and costs dynamics. AES TD1008 is explicit that a high
  peak-to-loudness ratio sounds clearer than heavy limiting.

  *Corrected by the author, 2026-09-12:* the user picks the loudness from
  the Loudness target list, as today. Every choice on that list must reach
  its level cleanly. A master must also hold up next to released music
  played in an ordinary player, like Windows Media Player next to Spotify
  on the same computer. That is where masters were heard as too quiet.
- **Not a clone of any service's house sound.** Sounding like a particular
  vendor is not the target, even a good one.
- **Not aggressive by default.** A track with no artifact should come out
  essentially untouched. A tool that always finds something to fix is not
  measuring anything.

## The decision rule

When two versions of the chain disagree, this is how the argument is settled,
in order. A later test does not overturn an earlier one; they answer
different questions.

1. **Does it remove the fault?** Measured against material where the fault is
   known to be present, with an independent measure — not the detector's own
   priors, which is circular.
2. **What did it cost?** Audible content removed, in sones, from the BS.1387
   ear model in `shimmer/perceptual.py`. Benefit and cost in the same unit,
   so a preset cannot win by removing a lot.
3. **Where does it land against real records?** The captured commercial
   library, not a service's masters.
4. **Does it sound better?** Level-matched, blind, judged by the author.
   **This one is final.** Both listening rounds so far changed the diagnosis,
   and measurement has been wrong in both directions on the same question.

Rule 4 outranks 1–3 when they conflict. Measurements are how we find things
worth listening to; they are not the verdict.

## How we know it is working

- Artifact efficacy, per preset, against ground-truth material —
  `scripts/efficacy_harness.py`, cached in `docs/efficacy-harness.json`.
- Cost of every preset in sones — `scripts/preset_harness.py`.
- Tone against real records — `scripts/tilt_vs_commercial.py`. Currently
  mean gap −0.03 dB across 8 sources.
- No recommendation on a finished commercial master. A tool that wants to
  clean a released record is measuring its own mask, not the audio.

## The frozen corpus

Measurements are only comparable if the material does not drift.

| What | Where |
|---|---|
| Suno renders, service masters, Shimmer masters | `sources/` |
| Finished masters used as controls | `assets/reference/` |
| 309 service masters, tone curves only | `docs/tone-reference.json` |
| Captured commercial masters, tone curves only | `docs/reference-library.json` |

Run `scripts/corpus_check.py` before trusting any of it. It has already
caught two files that were not what their names said, and neither was visible
to listening or to a spectrum.

## Known open questions

Recorded so they are not mistaken for settled.

- **The hash.** No treatment in the product today removes what the author
  hears as shimmer on a hashed render. Checklist item 15.
- **How much correction is right.** The tone target now lands where records
  land on average, but "average" is not "this song," and the tolerance band
  that would create a deadband is derived and still unused.
- **Stereo width.** Cleaning narrows the high end by about 1 dB against a
  service master. Measured, never investigated, and the capture library holds
  no width data because it keeps only tone curves.
