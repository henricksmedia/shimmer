# Pitfalls

Every wrong turn taken on this codebase, so it is not taken again. Each
entry says what happened, how it was caught, and the rule that follows. The
rule is only as good as the evidence, so the evidence is named.

This file is append-only in the same sense as the checklist: add a pitfall,
never delete one. If a rule turns out to be wrong, say so under it and why.

---

## Measurement

**A metric that cannot fail is not a metric.** `purity` (the share of
removed energy outside a transient/partial mask) read 0.95-1.0 on finished
commercial masters and on Suno renders alike, and it correlated -0.003 with
the hearing model's damage over 16 presets. Nobody noticed for months because
the number looked like evidence and always agreed. *Caught by:* running the
detector on finished masters, where the right answer is "nothing to do", and
finding it recommended cleaning at 56-69 % confidence.
*Rule:* before trusting a self-check, run it on material where the answer is
known. `tests/test_detect.py::test_finished_master_gets_no_recommendation`
does this on every run.

**Cost-only views cannot tell surgical from inert.** Six presets were praised
for doing nothing to clean material. Measured against ground truth
(`scripts/efficacy_harness.py`), four of them also do nothing to their
target: Checkerboard Grid removes -1 % of a comb, Sibilance Rattle -2 % of
centred sibilance, Broadband Fizz 6 % of fizz, the residue presets 2-7 %.
*Rule:* report both axes, efficacy and cost, or you will recommend inert
presets. An inert preset scores exactly zero on both.

**Judging efficacy by the detector's own prior is circular.** The first
harness scored "fixed" as the drop in a preset's own prior after cleaning.
Against ground truth that figure correlates +0.22 with the truth, and the
priors barely register a 16 kHz line the static notch plan removes at 96 %.
*Rule:* an efficacy measure must not share components with the thing under
test. Ground truth here means a clean host plus a modelled artifact
(`shimmer/artifacts.py`), with the level set by the hearing model.

**Relative measures inflate when their neighbours are cut.** The evidence
priors compare bands against each other, so removing energy in one band
raised other presets' priors (0.80 → 0.90, 0.70 → 0.85) and the routine
second pass partly answered a number the first pass had created.
*Rule:* do not iterate on a relative measure. Iteration a preset needs
belongs inside it, under one damage measurement.

**Level-match every comparison.** The whole investigation began because a
reference master sounded better while being 2.8 LU louder. Inside the
hearing model the same thing happened: a pure -3 dB gain with no spectral
change read 13.6 of linear distortion, more than half of what a -6 dB shelf
reads, because the level adaptation rescales the reference and the tilt
measure then compares it with the raw one. *Caught by:* computing golden
values on a pure-gain case. *Rule:* `measure_damage` level-matches its
inputs; any A/B outside it must too.

**Residual listening cannot detect air loss.** Removed air sounds like
*shhh* on its own, never like music, so a listener correctly says "no music
in there" while several dB of openness has gone. *Rule:* judge magnitude by
comparing masters, not by listening to what was removed.

**The artifact's own masking looks like cost.** With 2 sones of hash
injected, the *un-cleaned* render already read 0.6 sones "missing" against
the clean host: the artifact masks host content and tilts the spectrum. A
cleaner that removed nothing would have been charged for it. *Rule:* cost
is net of the un-cleaned baseline; the harness keeps the raw figure
alongside.

**A cleaner's own alterations look like artifact residue.** Comparing the
cleaned render with the clean host counted the FlickerTamer's modulation of
the music (0.07 sones on a clean master) as artifact left behind, giving
negative efficacy. *Rule:* compare the cleaned render with the cleaned
clean host, so the cleaner's own behaviour cancels.

**Verify corpus files before measuring them.** One "reference master" was
not one, and one pair was not the same performance (envelope correlation
0.21). Both were invisible to listening and to spectra. Two "references"
in the catalogue turned out to be service masters *of Shimmer exports*.
*Rule:* run `scripts/corpus_check.py`; pair by envelope correlation; reject
any reference whose provenance passes through the tool under test.

**Statistics over duplicate files are wrong.** The same master is often
filed in an album folder, a distribute folder and a download folder.
*Rule:* deduplicate by content before taking a median.

**Nine files is a small clean sample.** The prior ramps' lower edges are
the 84th percentile of nine finished masters, which is the second-highest
file. *Rule:* widen the clean sample before tightening any edge, and say
the sample size next to any constant it produced.

---

## Standards and constants

**Never assert a standard from memory.** Every incorrect claim in the
investigation came from stating a norm without checking. In this session
alone: a Kabal equation number and two section numbers were written from
memory and were wrong, and three pinned spreading values were typed before
being computed. All were caught by re-reading the text and running the
code before commit. *Rule:* cite by fetching; pin by computing.

**A pinned constant needs a test that fails when it moves.** Eight
mutations to standard-mandated PEAQ constants survived a green suite. The
relation tests checked that the model behaved like *a* hearing model, not
that it was *this* one. *Rule:* `tests/test_perceptual_golden.py` pins each
constant to its citation and the outputs on fixed signals to 0.2 %.

**A constant fitted against one scale drifts when the scale changes.**
`S0_LINDIST` was 0.5 against the reference's 1.0, and the budget's tilt
ceiling had been set on the wrong scale. The score's cost term would have
been fitted on it too. *Rule:* correct the instrument before fitting
anything to its readings; then re-measure the anchors.

**Do not fit constants to four songs and believe them.** Several in
`budget.py` are, and the file says so. *Rule:* widen the corpus before
tightening a threshold; never trust such a constant to two significant
figures.

**Self-referential tests drift.** A test that builds its stimulus from the
constant it tests against changes meaning silently when the constant moves.
*Rule:* stimuli come from fixed, seeded signals, not from the constant.

---

## Design

**A tone target derived from the tool's own material is not a commercial
reference.** The 309-master target was one service's masters *of AI
renders*, which are bright before anything touches them; the data file said
so about itself and it was used as a general target anyway. It runs 7-9 dB
hot above 2 kHz against contemporary commercial music
(`BRIGHTNESS-ASSESSMENT.md` §7). Note the warning sign that read as
confirmation: `autoeq` flipping sign on *everything* is what a moved target
does, not evidence the target is right. *Rule:* a reference must come from
outside the pipeline whose output it judges.

**Errors that cancel on average diverge on individual tracks.** Correcting
a tone target to compensate for over-cleaning would hide the defect
underneath. *Rule:* never make two errors cancel.

**"Many artifacts" was the priors firing, not the music.** 56 % of tracks
read three or more artifacts because presence-band priors read 0.7-1.0 on
finished masters. After recalibration no corpus file fires more than one
preset. *Rule:* count artifacts only with priors that can read zero.

**A union of stages that each remove nothing removes nothing.** Deep Scrub
runs every stage at high strength and is the most damaging preset measured;
its efficacy comes from taking the most. *Rule:* build composites from
stages that have measured as effective, not from stage lists.

**The Mid channel protection fights centred artifacts.** Centred sibilance
is cleaned at 0.2x and the de-esser's depth is scaled down by the transient
weight the burst itself trips, so Sibilance Rattle removes -2 % of it.
*Rule:* an artifact that is not music does not deserve the protection
music gets; measure before assuming a stage reaches its target.

**Silent scope drops are not neutral.** Twice, the items dropped from the
checklist were the ones that would have slowed the work down.
*Rule:* the checklist is append-only; status changes carry a reason.

---

## Process

**Do not report a number you have not measured.** Two lines in this
session's write-up were drafted before the measurement returned and were
wrong (one cost figure, one phrase about excerpt choice). Both were caught
on re-reading before commit. *Rule:* write the sentence after the number
exists, and re-read every quantitative claim against its source before
committing.

**Another agent may be in the tree.** Files changed under this session
that it had not touched (`references.py`, the handoff document, the
checklist). *Rule:* check `git status` before every commit, commit with an
explicit pathspec, and never revert a change you did not make — say so
instead.
