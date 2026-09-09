# Why the automated flow ships dull masters

**Case study:** *The Treq — "Air Above, Bass Below"* (Leave The World Behind)
**Reference:** the reference master of the same file
**Date:** 2026-09-08
**Verdict:** The dullness is real and it reproduces on every track tested. On
four same-song triplets it measures **11.0 dB of tilt on average** across
800 Hz → 6.3 kHz (range 7.8–13.7). It is produced by the automated path
itself: Shimmer *adds* low-mid and *removes* presence on every one of the
four, driven by a detector that cannot tell an artifact from music in the top
end — it recommends cleaning finished commercial masters with 80% confidence,
and one preset it favours strips **6.5 dB out of 16 kHz** from a released
master that carries no artifact at all.

---

## 1. What was measured

| File | Stage |
|---|---|
| `suno with lyrics/Air Above, Bass Below (LYRICS) FINAL GOLIVE.wav` | Suno source (16-bit) |
| `shimmer/..._deep_scrub_processed_97cd875d.wav` | Automated pass 1 |
| `shimmer/..._deep_scrub_processed__vocal_glaze_processed_989f244f.wav` | Automated pass 2 |
| `distribute/Air Above Bass Below.wav` | Shipped master |
| `distribute/<reference master>.wav` | Reference A, same song |
| `assets/reference/reference-{b,c}.wav` | Two more Ref masters |

The shipped file is **byte-identical** to the pass-2 output (md5
`13b5edbf…`) — `distribute/` is a copy, nothing happened after Shimmer.

Analysis used Shimmer's own measurement code (`analyze_spectrum`,
`relative_band_levels`, `measure_loudness`) so every number below is on the
same scale the app makes its decisions on.

### Level

| | LUFS-I | True peak | PLR |
|---|---|---|---|
| Shimmer final | **−14.00** | **−3.94 dBTP** | ~10 dB |
| Reference A (same song) | −11.24 | −0.03 dBTP | ~11 dB |
| References B and C | −10.56 / −9.10 | +0.28 / +0.42 | — |

The master is 2.8 LU quieter and its limiter never engages. **This is not a
defect** — see §2.9 and §4 item 9. AES TD1008 recommends exactly this target
and states that a high peak-to-loudness ratio is *preferable* to heavy
limiting; every major platform normalises the louder file back down anyway.
The level difference matters only in an unlevel-matched A/B, which is where
the "dull" impression forms.

### Tone — the actual gap

Loudness-aligned 1/3-octave transfer, both derived from the same Suno source:

| Band | Shimmer did | Reference did | **Gap (Ref − Shimmer)** |
|---:|---:|---:|---:|
| 315 Hz | +0.2 | −2.5 | −2.6 |
| 400 Hz | +0.1 | −3.0 | −3.0 |
| 630 Hz | 0.0 | −3.1 | −3.1 |
| **800 Hz** | 0.0 | **−4.4** | **−4.4** |
| 1 kHz | 0.0 | −3.2 | −3.3 |
| 2 kHz | +0.1 | +0.6 | +0.5 |
| 3.15 kHz | +0.2 | +2.3 | +2.0 |
| 4 kHz | −0.6 | +2.3 | +2.9 |
| 5 kHz | −2.1 | +1.2 | +3.2 |
| **6.3 kHz** | **−3.5** | −0.1 | **+3.4** |
| 8 kHz | −3.8 | −0.6 | +3.2 |
| 10 kHz | −3.5 | −1.3 | +2.2 |
| 12.5 kHz | −3.0 | −2.0 | +1.0 |
| 16 kHz | −2.4 | −2.8 | −0.4 |
| 20 kHz | −1.7 | −2.3 | −0.6 |

Two things fall out of this table, and neither is the one people usually
assume:

1. **It is not about "air".** Above 12.5 kHz the two masters agree within
   1 dB — the reference *also* rolls the top octave off. The whole difference
   lives in **4–10 kHz**, the presence/brilliance band.
2. **Half the gap is low-mid.** the reference scoops 315 Hz–1.25 kHz by 3–4.4 dB.
   Shimmer leaves it untouched. A track can be dull because the top is gone
   *or* because the middle is in the way; here it is both, and they add:
   **800 Hz → 6.3 kHz tilt differs by 7.8 dB.**

Shimmer's own analyzer saw this before the run started. The detector's
evidence line for the source reads: *"The presence band (3–8 kHz) is −6 dB
compared with 1–3 kHz"* and, for `harsh_veil`, *"4–12 kHz is −8 dB compared
with 1–3 kHz"*. It measured a dark track and then prescribed two cleaning
passes in that same band.

### 1.1 It reproduces — four same-song triplets

Added after the first draft. Four songs, each with the Suno source, the
Shimmer master, and the reference master **of that same source**
(`sources/{suno,shimmer,reference}-*.wav`). Every chain measured
loudness-aligned against its own source, so each number is what that chain
*did*.

| Band | Shimmer (mean) | Reference (mean) | **Gap** | spread across songs |
|---:|---:|---:|---:|---:|
| 250 Hz | **+2.1** | −0.9 | −2.9 | 2.6 |
| 400 Hz | **+2.0** | −2.5 | −4.5 | 2.5 |
| 630 Hz | **+1.3** | −2.8 | −4.0 | 0.9 |
| **800 Hz** | **+0.9** | **−4.3** | **−5.2** | **1.0** |
| 1 kHz | +0.3 | −3.4 | −3.6 | 1.1 |
| 2.5 kHz | +0.1 | +0.4 | +0.3 | 0.8 |
| 4 kHz | −0.2 | +2.3 | +2.5 | 1.9 |
| 5 kHz | −2.2 | +2.4 | +4.6 | 4.0 |
| 6.3 kHz | −3.4 | +2.5 | +5.8 | 4.9 |
| **8 kHz** | **−4.3** | **+2.0** | **+6.3** | 5.2 |
| 10 kHz | −4.8 | +0.8 | +5.5 | 6.0 |
| 12.5 kHz | −3.7 | −0.4 | +3.3 | 4.2 |
| 16 kHz | −3.7 | −1.6 | +2.1 | 5.1 |

Per-song tilt gap, 800 Hz → 6.3 kHz: **12.5, 9.8, 7.8, 13.7 dB** (mean 11.0).

Three things this settles that one song could not:

1. **The single-song case in §1 was the mildest of the four.** 7.8 dB was the
   floor, not the typical result.
2. **Shimmer boosts the low mids** on these four — it *adds* +0.9 to +3.6 dB
   at 250–800 Hz, the tone curve correcting toward `_REF_DB` (§2.1). **This
   did not generalise; see §1.2.**
3. **The reference behaviour is a stable house curve, not noise.** It scoops
   400 Hz–1 kHz by 2.4–4.5 dB and lifts the presence band on every track.
   That consistency is what makes it a legitimate yardstick.

### 1.2 Held out: two more triplets, and a mechanism that did not survive

`kindling` and `falling-for-you` were measured *after* the above, as held-out
tests, with predictions written down first. Six triplets now.

| | tilt gap | Shimmer 250–800 Hz | Shimmer 6.3–10 kHz |
|---|---:|---:|---:|
| algorithms-lure | 12.5 | +0.6 to +0.7 | −4.1 to −5.1 |
| alive-again | 9.8 | +0.4 to +2.8 | −2.1 to −3.4 |
| leave-the-world-behind | 7.8 | +0.6 to +3.4 | −2.1 to −3.9 |
| we-were-meant | 13.7 | −0.6 to +1.4 | −5.1 to −6.6 |
| **kindling** (held out) | **10.2** | **−0.4 to +0.5** | **−1.1 to −1.7** |
| **falling-for-you** (held out) | **10.5** | **−0.2 to +0.6** | **−2.7 to −3.7** |

**What held, 6 of 6:** the tilt gap (7.8–13.7 dB, mean ~10.8); Shimmer landing
on exactly −14.00 LUFS; Shimmer narrowing the 6–20 kHz stereo image by
1.2–4.0 dB (§2.12); the reference scooping 400 Hz–1 kHz.

**What did not hold: the mechanism.** Point 2 above — "Shimmer adds low-mid" —
is true of the first four and **false of both held-out tracks**, where Shimmer
is tonally near-flat below 1 kHz. On `kindling` it removes only 1.1–1.7 dB of
presence as well, so the 10.2 dB gap there is almost *entirely* the reference's
doing rather than Shimmer's.

That is a real correction, and it cuts two ways:

- The **outcome** is robust and reproduces on every track measured.
- The **causal story** was over-fitted to four songs. How each side produces
  the gap varies enormously, which rules out any fixed corrective more firmly
  than the four-song data did.
- And it means the mastering half can produce the whole gap on its own. On
  `kindling` the cleaning was not the problem; the absence of the right tonal
  moves was. Fixing only the cleaning would not have helped that track.

**And one thing that argues against a fixed corrective.** The gap's spread
across songs is ~1 dB in the low mids but **4–6 dB from 5 kHz up**. Whatever
replaces the current behaviour has to measure each track, not apply a
constant. This is the strongest single argument for §4 item 4's
reference-matching over any global curve — including any global curve I might
have proposed.

---

## 2. Where the brightness goes — four subtractions, no additions

### 2.1 The reference curve is a sixty-year average used as a present-day target

`_REF_SHAPE_DB` in [mastering.py:47](shimmer/mastering.py:47) is the neutral
target every automated decision is measured against. Measured against it,
real masters read as far too bright:

| Band | Ref A (same song) | Reference C | Reference B | **mean** |
|---:|---:|---:|---:|---:|
| 2.5 kHz | +4.1 | +4.5 | +4.5 | +4.4 |
| 3.15 kHz | +6.3 | +6.2 | +6.0 | +6.2 |
| 4 kHz | +5.7 | +5.1 | +9.1 | +6.6 |
| 5 kHz | +4.9 | +7.0 | +8.6 | +6.8 |
| 6.3 kHz | +4.0 | +7.3 | +9.3 | +6.8 |
| 8 kHz | +6.9 | +9.1 | +11.4 | +9.1 |
| 10 kHz | +9.7 | +16.7 | +10.5 | +12.3 |
| 12.5 kHz | +7.8 | +15.5 | +8.3 | +10.5 |

**Corrected after research — the first draft had the mechanism wrong.** I
wrote "the reference is 6–10 dB too dark from 2.5 kHz up, the array does not
implement its own docstring." Checked against the literature it cites, that
is false. Fitting slopes properly (1/3-octave band power = PSD + 3 dB/oct,
because band width grows with frequency):

| | 100 Hz–4 kHz (PSD) | 4–16 kHz (PSD) |
|---|---:|---:|
| **`_REF_SHAPE_DB` (the code)** | **−4.50** | **−9.25** |
| Literature (Pestana 2013; Nyberg LTAS) | −4.5 to −5.0 | "steeper", unquantified |
| Suno source | −4.15 | −4.66 |
| Shimmer final | −4.39 | −5.43 |
| the reference same song | −4.07 | −7.11 |
| the reference "Hey" | −3.68 | **−10.81** |
| the reference "Leave The World Behind" | −3.50 | −5.36 |

Two things follow, and both cut against my first draft:

1. **Below 4 kHz the curve is right.** −4.50 dB/oct PSD is a near-exact match
   to the two independent corpora, and it does implement its docstring. The
   references are *shallower* (−3.5 to −4.15) — brighter than the literature
   average, not the reverse.
2. **Above 4 kHz the code's slope is inside the range the references span**
   (−5.36 to −10.81). Reference B is *steeper* than the code. So "the HF
   section is too dark" is not supportable as a slope claim.

So why did every reference measure +5 to +12 dB above `_REF_DB` at 8–12 kHz
(§2.1 table)? Because the levels are normalised to the 200 Hz–2 kHz median.
A track with a shallower *mid* slope is already several dB above the
reference by the time it reaches 4 kHz, and that offset carries upward. **The
excess is inherited from the mids, not created in the top.**

The real root cause is narrower and better supported: the cited study
averages **1950–2010**, and reports "a notable flattening of the spectral
distribution since the 2000s". The code took a sixty-year average as a
present-day target. Contemporary masters sit at the flat end of that range —
which is exactly the −3.5 to −4.15 dB/oct measured above.

The consequence for brightness is unchanged and still holds: measured against
this curve a contemporary master reads as "too bright", so every automatic
decision in §2.2 and §2.3 is a cut. But the fix is not "raise the HF section
by the measured offset" — see §4 item 4, which changed substantially as a
result.

### 2.2 The mastering tone curve cuts the top on every pass

`compute_tone_curve` ([mastering.py:217](shimmer/mastering.py:217)) at the
saved settings (`intensity: med` → strength 0.55, `tilt: neutral`) computes
this for the Suno source:

| | 5 k | 6.3 k | 8 k | 10 k | 12.5 k | 16 k | 20 k |
|---|---:|---:|---:|---:|---:|---:|---:|
| med / neutral (default) | −0.8 | −1.4 | −2.2 | −2.8 | −3.0 | −3.0 | −3.0 |
| high / **brightest** | +0.1 | −0.7 | −1.9 | −2.7 | −3.0 | −3.0 | −3.0 |

**There is no setting in the app that makes this curve stop cutting the top
octaves on this material.** "Brightest" tilt is only ±2 dB
([mastering.py:76](shimmer/mastering.py:76)) and it is applied *before* the
clip and the harshness guard, so it cannot escape them. And it runs again on
pass 2, on the already-dulled pass-1 output.

Two hard ceilings compound it:

- `_MAX_EQ_BOOST_DB = 2.0` / `_MAX_EQ_CUT_DB = 3.0` — asymmetric by 1 dB in
  favour of cutting.
- `_HARSH_MAX_BOOST_DB = 0.5` across **5–12 kHz**
  ([mastering.py:83](shimmer/mastering.py:83)) — the exact band the reference
  lifts by 3 dB is the one band the tone curve is forbidden to lift.

### 2.3 The auto Tone plan adds a *third* top-end cut

`tone.auto` is on in the saved settings and
[single.js:1302](static/js/single.js:1302) applies the plan without asking.
Run against the shipped master, `plan_tone` says:

```
Air        dev  +4.20  tol ±3.0  -> over
MOVE high_shelf 8000 Hz  -0.90 dB   "Air sits 4.2 dB above the Neutral range"
```

It wants to take *another* 0.9 dB off 8 kHz from a file already 3.8 dB down
there. On the raw source it asks for the full −2.0 dB. Same cause: "Neutral"
is `_REF_DB`.

Its boost ceilings are the mirror image of the problem:
`BOOST_MAX_HIGH_DB = 1.0` for presence and air
([autoeq.py:67](shimmer/autoeq.py:67)), and any boost gets halved or dropped
if peaks rise more than loudness ([autoeq.py:79](shimmer/autoeq.py:79)).
**Maximum brightening the Tone step can ever apply: +1 dB.**

For calibration: run against the reference masters, `plan_tone` calls them
"Air 8.8–13.6 dB above Neutral" and prescribes the maximum −2.0 dB air trim
on all three. When the tool wants to darken a reference master by the full
allowance, the target, not the track, is wrong.

### 2.4 The cleaning passes subtract in the same band, twice

This was a two-pass automated run (`Pass 1 · …`, `Pass 2 · … · clean &
master · suggested EQ`). Which preset ran on pass 1 cannot be read back: the
files carry no tags, because they were exported on 2026-09-04 and tag writing
landed on 2026-09-05 (commit `724d30e`). Nothing is broken — the round trip
works on current code. The real gap is what the note *records*: see §2.7.

The shape of the loss says the first pass was a **Suno Hash**–family config,
not stock Deep Scrub. Compare the relevant preset bands:

| | band | built-in shelf | flicker_tame | iterations |
|---|---|---|---|---|
| `suno_hash` | 4.5–12 kHz | none | 1.00, 4.5–12 k, ≤18 dB | 1 |
| `vocal_glaze_plus` | 2–12 kHz | −1.5 dB @ 10 k | 1.00, 4.5–12 k, ≤18 dB | 1 |
| `deep_scrub` | 3–18 kHz | −2.5 @ 12 k, −1.5 @ 6 k | 0.70, 4–12 k, ≤16 dB | 2 |

The measured source→final loss is a hole with edges near 4.5 k and 12 k
(−2.1 @ 5 k, −3.5 @ 6.3 k, −3.8 @ 8 k, −3.5 @ 10 k) that then *recovers* to
−2.4 by 16 kHz. That is the 4.5–12 kHz signature plus a small shelf. Stock
Deep Scrub would have kept falling above 12 kHz, and the pass-1 file sitting
in `shimmer/` does exactly that (−4.2 @ 12.5 k, −5.0 @ 16 k, −4.7 @ 20 k) —
which is also why that file cannot be the input the shipped master was built
from. It is a separate earlier run.

The saved settings match the Suno Hash reading: preset `vocal_glaze_plus`,
`start_hz 2000`, `end_hz 12000`, **`flicker_tame 1.0`** (maximum, ≤18 dB of
attenuation across 4.5–12 kHz), `deharsh 0.66`, `tone_kill 0.46`, and a
manual **`high_shelf_db: -1.5`**.

That makes the diagnosis sharper, not softer: **the cleaning was aimed
precisely at 4.5–12 kHz, and 4.5–12 kHz is exactly where the entire gap to
The reference lives.** FlickerTamer at 1.0 is the single largest subtraction in
the chain, and it operates in the band the tone stages are then forbidden to
give back (§2.2, §2.3). Whether pass 1 was Suno Hash or Deep Scrub changes
which stage took the 3.5 dB — it does not change that four stages took it and
nothing could return it.

Nothing anywhere totals this up. There is no ledger that says "this run has
removed 3.8 dB at 8 kHz across four stages".

### 2.5 The detector cannot tell artifact from music in the top end

*Added after the first draft, in answer to "why do I keep getting the Suno
Hash recommendation?" — the answer turned out to be bigger than that preset.*

**The control experiment.** Run the detector on the three finished the reference
masters. There is no AI artifact left in them, so the correct answer is
"nothing to do". Instead:

| Track | Verdict | Its stated reason |
|---|---|---|
| Ref A, same song | **Vocal Glaze**, confidence 0.80 | "97% of what it removed was noise, not music" |
| Ref A, same song | Deep Scrub ranked #2, prior **0.85** | "5 kinds of noise found at once" |
| Ref A, same song | Suno Hash, purity **0.998** | "100% of what it removed was noise, not music" |
| Reference B | Suno Hash ranked #2, score 0.72 | "flicker 1.3 dB vs 1.5 dB in the mids (**−0.2 dB more**)" |

That last row is the tell. The flicker signature Suno Hash exists to detect is
**absent** — the brilliance band flickers *less* than the mids, and the prior
(the actual evidence term) is **0.0**. It still ranks second, because the
evidence carries only 20% of the decision:
`final = 0.8 × verified + 0.2 × prior` ([detect.py:98](shimmer/detect.py:98)).

*Precision here matters.* On that file Suno Hash was the runner-up, not the
winner — Sibilance Rattle was applied. So the accurate claim is not "it was
applied with zero evidence"; it is that **a preset with zero evidence is a
live candidate**, and runner-ups are exactly what the follow-up logic tries
on the winner's output to build pass 2
([detect.py:1370](shimmer/detect.py:1370)). Your two-pass runs are selected
from this list.

**Why the verified score is not evidence.** It is
`benefit(artifact_db) × quality(purity)`, and `purity` is

```
purity = G / (G + B)
G = energy removed from `eligible` cells
B = energy removed from `protected_hi` (transient frames, narrow partials) + 3 × body
```

`eligible` is defined as: above 2 kHz, not inside a transient frame, and not a
narrowband line standing 6 dB above its neighbours — **and above
`PARTIAL_MAX_HZ = 10000` nothing can be a partial at all**
([detect.py:73](shimmer/detect.py:73)). So cymbal wash, hi-hat tails, reverb
tails, vocal air and breath — sustained, broadband, non-tonal high-frequency
*music* — are all classed `eligible` by construction.

Measured share of energy the mask calls artifact-eligible:

| Track | ≥ 2 kHz | ≥ 10 kHz |
|---|---:|---:|
| Suno source | 90.1% | 98.9% |
| Shimmer final | 86.8% | 98.6% |
| **Reference A, same song** | **87.9%** | **97.9%** |
| **The reference "Hey"** | **83.7%** | **100.0%** |
| **The reference "Leave The World Behind"** | **95.2%** | **100.0%** |

On a professionally mastered record, 84–95% of the top end — and effectively
*all* of it above 10 kHz — is fair game. So "97% of what it removed was noise,
not music" is **a restatement of where the preset operates, not a finding
about the audio**. Any preset confined to the sustained top end scores ~1.0.
The sentence reads to a user as reassurance and is a tautology.

That is the honest answer to "why Suno Hash keeps coming up": it is the
preset most precisely confined to the `eligible` mask (4.5–12 kHz,
FlickerTamer only), so it earns the highest purity of any preset — 0.998 —
on any track, artifact or not.

### 2.6 Which presets are actually destructive — a survey

Every artifact preset, run at 100% on a 30 s excerpt of a **finished
reference master**.

**A caveat the first draft got wrong.** I described this material as
artifact-free. It is not: the reference EQs and limits, it does not de-artifact,
so a reference master of a Suno render still carries the hash. Shimmer's own
detector confirms it — on `the reference master` it measures
"flicker 3.8 dB in 4.5–12 kHz against 2.9 dB in the mids (**+0.9 dB more**)",
the hash signature, still present. So on that file some of what a preset
removes may be real artifact, and "every dB is collateral" was overstated.

The repair: `the clean control` measures flicker excess of **−0.2 dB** — the
signature is *absent* there, the closest thing available to a true control.
Both columns are shown below. The ranking is stable and the magnitudes barely
move, so the conclusion survives the correction:

| Preset | 6.3 k | 8 k | 12.5 k | 16 k | **worst (same song)** | **worst ("Hey", no hash)** |
|---|---:|---:|---:|---:|---:|---:|
| **Deep Scrub** | −1.74 | −2.70 | −5.20 | −6.47 | **−7.47** | **−6.47** |
| Harsh Veil | −0.33 | −0.91 | −2.78 | −3.44 | −3.57 | −3.44 |
| Broadband Fizz | 0.03 | −0.07 | −1.02 | −2.58 | −2.98 | −2.58 |
| Vocal Glaze + Top End | −0.95 | −1.42 | −2.52 | −2.29 | −2.80 | −2.52 |
| Echo Sheen | −0.26 | −0.69 | −1.75 | −2.33 | −2.59 | −2.33 |
| Presence Haze | −1.30 | −1.80 | −2.23 | −2.30 | −2.62 | −2.30 |
| Brittle Air | 0.04 | −0.01 | −0.50 | −1.60 | −1.91 | −1.60 |
| Sibilance Rattle | −1.25 | −1.35 | 0.40 | 0.38 | −1.58 | −1.35 |
| Reverb Flutter | 0.11 | 0.24 | 0.25 | −0.86 | −1.14 | −0.86 |
| **Suno Hash** | −0.60 | −0.61 | −0.09 | 0.24 | −1.16 | **−0.61** |
| Vocal Glaze | −0.37 | 0.11 | 0.46 | 0.45 | −0.67 | −0.37 |
| Cymbal Chatter | 0.07 | −0.06 | −0.09 | 0.03 | −0.35 | −0.27 |
| Checkerboard Grid | 0.07 | −0.04 | −0.07 | 0.03 | −0.29 | −0.23 |
| Phantom Cymbal | −0.19 | −0.17 | 0.20 | 0.19 | −0.30 | −0.19 |
| Laser Whistle | 0.05 | 0.05 | −0.09 | −0.02 | −0.11 | −0.09 |
| Cymbal Sheen | 0.05 | 0.02 | −0.05 | 0.03 | −0.05 | −0.06 |

Two readings the control makes possible:

- **Deep Scrub removes 6.5 dB at 16 kHz from a track with no hash in it.**
  The 1 dB difference between the two columns is all the artifact could have
  accounted for. The rest is music.
- **Suno Hash behaves the way a repair tool should**: 1.16 dB where the hash
  is present, 0.61 dB where it is not. It responds to the signal. That is a
  point in its favour, not against it.

Full first-column detail (all nine bands, same-song master):

| Preset | 5 k | 6.3 k | 8 k | 10 k | 12.5 k | 16 k | **worst** |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Deep Scrub** | −1.90 | −3.06 | −4.26 | −4.89 | −6.05 | **−7.47** | **−7.47** |
| Harsh Veil | −0.26 | −0.48 | −1.14 | −2.14 | −2.93 | −3.57 | −3.57 |
| Broadband Fizz | 0.10 | 0.07 | −0.10 | −0.45 | −1.20 | −2.98 | −2.98 |
| Vocal Glaze + Top End | −1.45 | −2.21 | −2.80 | −2.78 | −2.59 | −2.44 | −2.80 |
| Presence Haze | −0.87 | −1.56 | −2.11 | −2.39 | −2.55 | −2.62 | −2.62 |
| Echo Sheen | −0.28 | −0.45 | −0.95 | −1.42 | −2.00 | −2.59 | −2.59 |
| Brittle Air | 0.09 | 0.07 | 0.02 | −0.11 | −0.55 | −1.91 | −1.91 |
| Sibilance Rattle | −0.77 | −1.42 | −1.58 | −0.84 | 0.17 | 0.18 | −1.58 |
| **Suno Hash** | −0.59 | −1.11 | −1.16 | −0.53 | −0.12 | 0.18 | **−1.16** |
| Reverb Flutter | 0.10 | 0.16 | 0.21 | 0.28 | 0.04 | −1.14 | −1.14 |
| Vocal Glaze | −0.63 | −0.67 | −0.07 | 0.26 | 0.26 | 0.26 | −0.67 |
| Cymbal Chatter | 0.09 | 0.09 | −0.11 | −0.35 | −0.20 | −0.01 | −0.35 |
| Phantom Cymbal | −0.30 | −0.28 | −0.25 | −0.01 | 0.12 | 0.12 | −0.30 |
| Checkerboard Grid | 0.09 | 0.09 | −0.08 | −0.29 | −0.15 | 0.01 | −0.29 |
| Laser Whistle | 0.07 | 0.07 | 0.07 | −0.07 | −0.11 | 0.04 | −0.11 |
| Cymbal Sheen | 0.07 | 0.07 | 0.02 | −0.05 | −0.05 | 0.07 | −0.05 |

Three groups:

- **Surgical (≤0.4 dB):** Cymbal Sheen, Laser Whistle, Checkerboard Grid,
  Phantom Cymbal, Cymbal Chatter, Vocal Glaze. These do what a repair tool
  should: nothing, when there is nothing to repair.
- **Moderate (1–2 dB):** Suno Hash, Reverb Flutter, Sibilance Rattle,
  Brittle Air.
- **Broadband and heavy (2.5–7.5 dB):** Echo Sheen, Presence Haze, Vocal
  Glaze + Top End, Broadband Fizz, Harsh Veil, and **Deep Scrub**.

**Deep Scrub takes 6.5-7.5 dB out of 16 kHz on finished commercial masters.**
And the detector rated it prior **0.85** on that same master — "5 kinds of
noise found at once" — because its prior is built from the same
darkness-and-hiss-likeness features that any real record exhibits.

So the corrective to the first draft: Suno Hash is not the destructive one.
It is near the *gentle* end. The scorer flaw that keeps surfacing it is real
and general, but the collateral damage is concentrated in the wide-band
presets — and above all in the one the detector likes most.

### 2.7 A finished run is not reproducible

Tag writing works (added 2026-09-05, commit `724d30e`; round-trip verified).
What it *records* was the gap: `shimmer_note` stored the preset label,
strength, an EQ **band count**, and the mastering target. It did not store
which sliders were moved, what the EQ moves actually were, or the tone
setting — so "Vocal Glaze + Top End 100%" and the same preset with different
sliders and a −0.9 dB air shelf produced identical notes.

Fixed in this pass — the note now carries the knobs moved off the preset, the
EQ as applied, and the tone setting:

```
Shimmer 1.5: pass 2, Vocal Glaze + Top End 100%, tweaks noise_resynth 0.16;
denoise 0.36; deres 0.36; deharsh 0.66; tone_kill 0.46, EQ 850Hz -3.5dB Q0.8;
8kHz -0.9dB Q0.7, tone med/neutral, mastered -14 LUFS / -1 dBTP
```

### 2.8 Nothing in the automated path can add brightness

- The high-shelf slider range is **`(-12.0, 0.0)`**
  ([params.py:342](shimmer/params.py:342)) — it is a cut-only control, and
  `apply_preset_strength` makes it *deeper* as strength rises.
- `dark_mix_rescue` (`high_shelf_db=+2.5`, `presence_db=+1.5`) is the one
  brightening preset, and it is listed in `NON_ARTIFACT_PRESETS`
  ([detect.py:67](shimmer/detect.py:67)) — **the auto-detector will never
  suggest it**, in either pass.
- The only "your track is dull" signal is a text note gated at
  `dull_db < -26` ([detect.py:880](shimmer/detect.py:880)). This track's
  4–14 kHz sits above that gate, so nothing was said — and even if it had
  fired, it is advice, not an action.

### 2.9 Loudness target

`LOUDNESS_TARGETS["streaming"] = -14.0` ([params.py:409](shimmer/params.py:409)).
The master lands at exactly −14.00 LUFS with true peak at −3.94 dBTP: a
gain-only move, limiter idle, 3 dB of ceiling left on the table.
The references ship −11.2 with peaks at 0.

**This matters less than the first draft claimed.** Spotify and YouTube
normalise to −14 LUFS and Apple Music to −16, so on those platforms the
−11.2 master is turned *down* to meet the −14 one and the two arrive at the
same loudness — the louder master just gets there with more limiting. A
−14 LUFS delivery is not "quiet" on a normalised platform; it is the target.

Where the 2.8 LU gap does bite: unnormalised playback (local files, some
DJ and web contexts) and, importantly, **every A/B the user does inside
Shimmer or a file browser** — which is where the impression "my masters
sound dull" is actually formed. Equal-loudness contours are real, so an
uncompensated 2.8 dB level difference reads as less bright. But the tonal
gap in §1 is the substance; loudness is a secondary, context-dependent term,
and "change the default target" is a weaker recommendation than it first
appeared. The defensible fix is the headroom warning, not the target change.

### 2.10 Listening test, round 1 — where the model agreed, and where it did not

Four songs, four versions each (untouched source, Cymbal Sheen, Suno Hash,
Deep Scrub), level-matched to −18 LUFS and blind-labelled. One listener.
Full material and method in `listening-test/`.

**Best master chosen:** Suno Hash, Suno Hash, the untouched source, Cymbal
Sheen. **Deep Scrub won nothing.**

**Residuals judged to hold *slightly* too much music:** Suno Hash on all four
songs; Deep Scrub on two; **Cymbal Sheen on none.** The listener's overall
verdict on the residuals was positive — every one of them correctly contained
the pops and very-high-frequency content that ought to come out (§2.11). The
qualifier matters: this is over-reach at the margin, not wholesale damage.

| | Model said | Listener said | |
|---|---|---|---|
| Cymbal Sheen | cleanest, all four (`lin_dist` 0.047–0.081) | never flagged | ✅ agree |
| Deep Scrub | worst, all four (`lin_dist` 12.5–20.4) | flagged on 2 of 4 | ⚠️ partial |
| Suno Hash | mid (`lin_dist` 0.43–0.79) | flagged on 4 of 4 | ❌ disagree |

**The disagreement was my test's fault, not the model's.** Round 1 normalised
each residual to the same peak. Measured on `alive-again`, the residual RMS
levels are Cymbal Sheen −53.1, Suno Hash −46.8, Deep Scrub −38.6 dBFS — so
per-file normalisation handed the gentlest preset about **26 dB more gain**
than the heaviest, and all three arrived sounding equally significant. That
reduces the listener's question from *"how much was taken"* to *"is what was
taken recognisable as music"* — a different question, and one where Deep
Scrub's dense broadband residual reads as wash while Suno Hash's narrower one
reads as identifiable content. Round 2 uses one shared gain per song. The
disagreement has to be re-judged there before it means anything.

### 2.10b Round 2 — and why the residual test cannot see the real damage

Round 2 fixed the gain flaw: one shared gain per song, so the residuals keep
their true relative loudness (Cymbal Sheen dropped 21–43 dB, Suno Hash 11–16,
Deep Scrub unchanged). Verdict, with the levels now honest:

| Preset | Flagged "very slightly too much music" | Model `lin_dist` |
|---|---|---:|
| Cymbal Sheen | **0 of 4** | 0.047–0.081 |
| Suno Hash | 3 of 4 | 0.43–0.79 |
| Deep Scrub | 2 of 4 | **12.5–20.4** |
| Hidden reference | 0 of 4 (its residual is silence) | 0 |

On `algorithms-lure` nothing was flagged at all, though Deep Scrub scores
17.1 there. And where Deep Scrub *was* flagged the listener added that the
pops it removed were "correct to remove".

So the residual test and the model still disagree about Deep Scrub — and the
reason is not that either is wrong. **They are measuring different things,
and a residual test structurally cannot detect the damage that matters here.**

Deep Scrub's damage is 6.5 dB of high-frequency energy (§2.6). Played on its
own, that content sounds like *shhh* — wash, hiss, air. It does not sound
like music, because air never does in isolation; it is what makes a master
sound open, not something you can hum. A listener asked "is there music in
this?" will correctly answer no. The same listener asked "which master sounds
best?" put Deep Scrub last on **all four songs** in round 1. Same ears, same
files, opposite verdict — because the second question is the one air loss
answers to.

The methodological conclusion, which should govern every future round:

- **Residual test → is the targeting right?** Answer here: yes. The presets
  remove genuine artifacts, with very slight over-reach on two of them.
- **Master comparison → is the tone damaged?** This is where air loss shows,
  and where `lin_dist` tracks the listener.

Using the residual test to judge tonal damage would have exonerated Deep
Scrub. It nearly did.

### 2.11 The cleaning itself is working — the aggregate is what hurts

The listener's summary of the residuals was that **each one correctly
contained the material that should be removed** — the click-like pops and the
very high whistling content that are genuine AI artifacts. That is a positive
result and it deserves to sit next to everything else in this document,
because it narrows the diagnosis considerably.

The presets are **aimed correctly**. Six of twelve residuals were judged to
carry *slightly* too much music alongside the artifacts. Nothing was judged
to be destroying the track wholesale, and the artifact-targeting was judged
sound throughout.

So the problem is not that the cleaning stages are wrong in kind. It is:

- **over-reach at the margin** — each stage takes a little more than it
  should, in the same band, and
- **compounding** — two cleaning passes, then a tone curve, then an auto Tone
  plan, all subtracting in 4–12 kHz, with nothing summing the total (§2.7),
  and a tone target that then *adds* low-mid on top (§1.1).

That is why the end result measures 11 dB of tilt error while no single stage
looks unreasonable in isolation, and it is why §4 items 1–3 are about
measurement and budget rather than about redesigning what the presets target.

**An open measurement, not a finding.** While investigating this I measured
attack peaks at detected onsets and saw 0.5–0.95 dB of mean attenuation
across all three presets (worst case ~3 dB). Two reasons not to call that a
defect yet: the amount barely varies between a preset that removes almost
nothing and one that removes a great deal, which points at my ad-hoc onset
detector rather than at the audio; and there is no reference here for how
much attack softening is normal for any STFT process. It is recorded so it
can be checked properly, not as a conclusion.

---

## 3. Proof: what closes the gap

Applied to the shipped master — three EQ moves and a louder master, nothing
exotic:

```
bell        850 Hz   −3.5 dB  Q 0.8      (the low-mid stack the reference scoops)
bell        5.6 kHz  +3.0 dB  Q 0.8      (the presence band the chain removed)
high shelf  9 kHz    +1.5 dB  Q 0.7
then master to −11 LUFS, −1.0 dBTP       (gain +3.16 dB)
```

Residual against the reference master of the same song, before and after:

| Band | Before | After |
|---:|---:|---:|
| 400 Hz | −3.0 | −1.9 |
| 800 Hz | −4.4 | −1.2 |
| 1 kHz | −3.3 | −0.3 |
| 3.15 kHz | +2.0 | +0.8 |
| 5 kHz | +3.2 | +0.3 |
| 6.3 kHz | +3.4 | +0.2 |
| 8 kHz | +3.2 | +0.5 |
| 10 kHz | +2.2 | −0.1 |
| 16 kHz | −0.4 | −2.2 |

From ±3.4 dB down to **within ~1 dB across 500 Hz–10 kHz**. The gap is not
mysterious and it is not expensive to close — it is three moves the automated
path is structurally forbidden from making.

---

## 4. Recommendations, in order of payoff

> **Revised after §2.5–2.6.** The first draft led with recalibrating
> `_REF_SHAPE_DB`. That is now #4, deliberately — see the note there. Fixing
> a tool that removes what isn't there must come before adjusting a target
> that decides how much to add back.

**1 — Replace `purity` with a perceptual disturbance measure. (Root cause.)**
Everything downstream of the detector is wrong because the scorer cannot see
musical damage. The ad-hoc `eligible` mask is not repairable by tuning
`PARTIAL_MAX_HZ` — that is a patch on a metric whose definition is the
problem.

There is a standard for exactly this: **ITU-R BS.1387 (PEAQ)**, revised to
BS.1387-2 in 2023, which compares a reference and a processed signal in the
*partial loudness* domain of an auditory model and reports separate measures
for **added** disturbance, **missing components**, and **linear distortion**.
Shimmer's damage is entirely "missing components" and "linear distortion" —
the two things PEAQ measures and `purity` cannot.

The 2022 performance analysis of PEAQ (Delgado & Herre, arXiv:2212.01467) is
directly on point and gives the design:

- PEAQ's composite `DI`/`ODG` mapping performs poorly, but **the individual
  disturbance-loudness MOVs remain strong predictors** — so use the MOVs, not
  ODG.
- **For music specifically, `AvgLinDistA` (linear distortion) is the best or
  second-best single predictor, while `RmsNoiseLoudA` is the worst.** Linear
  distortion is precisely the spectral-tilt change over-cleaning produces.
  This is the measurement Shimmer is missing.
- Added and missing components carry different perceptual weight
  (`RmsNoiseLoudAsymA = RmsNoiseLoudnessA + 0.5 × RmsMissingComponents`), so
  they must be computed separately, not netted.

Concretely: score a preset as **benefit − cost in sones**, where benefit is
artifact energy removed *that was above the masking threshold*, and cost is
missing-component loudness plus linear distortion. A preset that removes
inaudible energy scores ~0 instead of 0.998. Reference implementations exist
to check against (GstPEAQ; Kabal's `PQevalAudio`).

This also retires the user-facing sentence: replace "97% of what it removed
was noise, not music" with an audible-damage figure the number actually
supports.

**2 — Give the prior a real "nothing is wrong" state.** *Revised: the earlier
version of this item was "put a floor under the prior", which is a patch and
insufficient.* On a finished reference master the priors are `deep_scrub`
**0.85** and `vocal_glaze` **0.795** — a floor at 0.5 stops neither. The
priors are built from feature ramps like `_ramp(ev.presence_db, -14, -2)`
that map ordinary music onto high probabilities, because they were calibrated
on Suno renders with no clean-music control. Recalibrate every prior against a
labelled corpus that includes artifact-free commercial music, so "no artifact"
is a reachable output. Then the 0.8/0.2 weighting stops mattering, because
both terms will agree.

**3 — Rebuild the broadband presets against the new metric, don't just turn
them down.** Deep Scrub takes **6.5 dB out of 16 kHz from a released master
with no artifact in it** (§2.6) while six presets take under 0.4 dB — so the
damage is settings, not physics. But "reduce the numbers until it looks
better" is guesswork. With item 1 in place each preset can be tuned against a
measured audible-damage budget on a clean-music control set, which is the
difference between a fix and a guess. Keep Deep Scrub as a deliberate
last-resort choice (some renders genuinely need it) but remove it from
automatic selection, and surface its own docstring warning in the UI.

**4 — Do not recalibrate `_REF_SHAPE_DB` by offset. Rebuild the target
architecture.** *This item changed completely after checking the literature —
see §2.1.* The curve's mid slope (−4.50 dB/oct PSD) matches Pestana et al.
and the Nyberg LTAS thesis almost exactly, and its HF slope (−9.25) sits
*inside* the range the three references span (−5.36 to −10.81). Adding my
measured offsets would have been a band-aid over a mis-specified target and
would have broken the part that is right.

The actual defect is narrow: the cited study averages **1950–2010** and
itself reports "flattening since the 2000s", so the code uses a sixty-year
average as a present-day target. Three fixes, in order:

- **Rebuild the curve from a contemporary corpus** (2015+), not from an offset
  applied to a historical one. Report it with the mid slope preserved.
- **Widen the tolerance above 4 kHz to the measured variance.** Three
  references span 5.5 dB/oct of HF slope. A single tight target up there is
  the wrong architecture regardless of its value; `plan_tone`'s ±3 dB air
  tolerance is far too tight for a region that genuinely varies that much.
- **Add reference-track matching.** Professional practice is 1–3 genre- and
  era-matched references, not a universal curve; that is also what iZotope and
  sonible ship. It is the only approach that is correct per-track rather than
  on average, and it removes the need to guess a global HF target at all.

**5 — Let the high-shelf control boost.** Change the
`("high_shelf_db", -12.0, 0.0)` range to something like `(-12.0, +6.0)`.
There is currently no automatic path to a positive shelf at all. This is a
code fact independent of every measurement above, and the cheapest item here.

**6 — Loosen the low-mid path.** The largest single term in the gap is
800 Hz, not 8 kHz: `MUD_MAX_CUT_DB = 2.5` and the ±2.5 dB `lowmid` tolerance
cannot produce the reference's −4.4 dB. This buys perceived brightness without
touching the top end and without re-exposing any hash — which also makes it
the safest item on the list, since it is not downstream of the detector fixes.

**7 — Surface the cumulative loss; do not auto-restore it.** Sum what every
stage took out per band across both passes and show it in the Signal Chain
view. *The first draft went further and proposed letting the tone stage add
back up to what the cleaner removed. That is incoherent* — if the cleaner was
right, restoring undoes the repair; if it was wrong, the fix is not to remove
it in the first place. The ledger's value is diagnostic: it makes items 1–3
visible instead of papering over them.

**8 — Make the 5–12 kHz boost guard conditional.** `+0.5 dB` exists to stop
the EQ re-boosting fizz the cleaner just removed — right instinct, wrong
mechanism as a permanent ceiling, since it also blocks brightening a track
that was never cleaned there. Condition it on whether this run actually
attenuated that band. Lower value than 1–3, and only meaningful once the
ledger in 7 exists.

**9 — Leave the loudness target alone. It is already correct.** *Withdrawn:
the first draft said switch the default to `loud` (−11 LUFS). Research says
that would have made the output worse, not better.* **AES TD1008** — the
industry recommendation the streaming services collaborated on — is explicit:

> "A recording with high peak to loudness ratio (PLR) is often perceived as
> clearer and less fatiguing than one that has been excessively peak-limited."

It recommends album normalisation with the loudest track at −14 LUFS
(album integrated typically −16), keeping tracks above −20 LUFS, and a
maximum true peak not exceeding −1 dBTP at the codec input. The shipped file
measures **−14.00 LUFS, −3.94 dBTP, PLR ≈ 10** — that is *compliant and good*
by this standard, and Shimmer's codec-aware ceilings (−1.0 lossless / −1.5
lossy) already meet or exceed it.

So there is no loudness defect to fix, and pushing to −11 would have traded
compliant dynamics for nothing: every major platform normalises back down.
The only thing worth adding is an informational note when delivered true peak
sits well under the ceiling — not a warning, since per TD1008 that is a
*good* outcome, and my earlier framing of it as "unused headroom" was wrong.

What remains true from §2.9: the 2.8 LU gap makes the reference sound better in
an **unlevel-matched A/B**, which is where the "my masters are dull"
impression forms. The fix for that is loudness-matched A/B in the app (the
`ab_loudness_match` setting already exists), not a louder master.

**10 — Let the detector reach for `dark_mix_rescue`.** A track whose presence
band the detector *itself* measured at −6 dB against the mids should be able
to get a brightening pass, or at minimum a hard stop before a *second*
subtractive pass in the same band. Today a two-pass chain of two top-end
eaters on an already-dark track is something the automation will happily
propose.

**11 — The confirm dialog: gate it on the measurement, not the preset name.**
Requested as "warn when someone picks Suno Hash". The survey says that is the
wrong target — Suno Hash is ninth of sixteen for collateral damage, and a
warning there would leave Deep Scrub, six times more destructive,
unwarned. Three design points:

- **Trigger on measured loss, not identity.** The verification run already
  measures what the preset removes from *this* track. Warn when that crosses
  a threshold — `ARTIFACT_CAP_DB` already marks over-removal and today only
  produces the mild aside "expect some loss of air" inside a reason string.
  Same rule for every preset, so the warning means something.
- **Show the number.** "Takes out about 4.3 dB at 8 kHz on this track" is
  actionable. "May reduce brightness" is not, and gets clicked through.
- **Offer the alternative, not just OK/Cancel.** Six presets are surgical on
  clean material. A third button that points at a gentler preset turns a
  warning into a decision.

A modal on every use of a named preset trains people to dismiss it. A modal
that fires only when this track will actually lose something keeps its
meaning. Draft copy (Flesch–Kincaid grade 0.9, well under the 8th-grade
ceiling; numbers and the last line are filled in per run):

> **Deep Scrub will take out some of your top end**
>
> Deep Scrub turns down noise from 3 kHz to 18 kHz. It runs twice.
>
> We tried it on this track first. It takes out about 4.3 dB at 8 kHz and
> 7.5 dB at 16 kHz.
>
> **What you get.** Most of the hiss, sizzle, and wash that AI renders leave
> behind.
>
> **What you give up.** Cymbals, hi-hats, vocal air, and reverb tails live in
> that same range. Some of them go too. Your track will sound darker and less
> open.
>
> **What we found here.** Weak signs of the noise this preset cleans. A
> gentler preset may do the job.
>
> `[Use Deep Scrub]` `[Show me a gentler one]` `[Cancel]`

**12 — Note that this is systematic, not one bad render.**
`"remember_settings": true` means the saved config — `vocal_glaze_plus`
narrowed to 2–12 kHz, `flicker_tame 1.0`, `deharsh 0.66`, a manual −1.5 dB
high shelf, `tone.auto` on, mastering at `streaming`/`med`/`neutral` — is
reapplied to **every** track that goes through the automated flow. Every song
mastered under it gets the same 3–4 dB scooped out of 4.5–12 kHz, the same
two automatic top-end trims, and the same −14 LUFS ceiling. A run of dull
releases is the expected result, not a coincidence. Anything shipped under
these settings is worth re-checking.

**13 — Immediate workaround, no code change.** For anything already rendered:
turn `tone.auto` off, set mastering target to `loud`, and apply the three
moves in Section 3 by hand in the EQ tab. That gets existing masters to
within ~1 dB of the reference today.

---

## 5. Caveats

- Three reference masters, one of which is the same song — enough to
  establish direction and rough magnitude, not enough to derive a production
  reference curve from. Do that from a proper corpus.
- the reference mastering is itself an opinionated bright-and-loud preset. It
  is the stated target here, so that is the right yardstick for this
  assessment, but "matches the reference" is not the same as "neutral".
- The pass-1 file in `shimmer/` is not the input the shipped master was built
  from (see §2.4) — it is an earlier run with a wider, Deep-Scrub-shaped
  band. Every number in Sections 1 and 3 compares the Suno source directly to
  the shipped master, so nothing here depends on that intermediate.
- The exact pass-1 preset is inferred from the shape of the loss and the
  saved settings, because the exported files carry no tags. Turning on tag
  writing (or fixing it for WAV) would make future runs auditable.

---

## 6. Sources

Every recommendation in §4 is measured against one of these rather than
against judgement:

- **ITU-R BS.1387** (PEAQ), first published 1998, revised **BS.1387-2, 2023** —
  the standard for objective perceptual audio quality; supplies the
  partial-loudness disturbance model and the separate added / missing /
  linear-distortion measures that item 1 is built on.
  <https://en.wikipedia.org/wiki/Perceptual_Evaluation_of_Audio_Quality>
- **Delgado & Herre, "Can we still use PEAQ? A Performance Analysis of the ITU
  Standard for the Objective Assessment of Perceived Audio Quality"**,
  arXiv:2212.01467 — establishes that PEAQ's individual disturbance-loudness
  MOVs outperform its composite `DI`/`ODG`, and that for *music*
  `AvgLinDistA` (linear distortion) is the strongest single predictor while
  `RmsNoiseLoudA` is the weakest. <https://arxiv.org/pdf/2212.01467>
- **GstPEAQ** (Holters & Zölzer, DAFx-15) — open reference implementation of
  basic and advanced PEAQ, for validating an implementation.
  <https://github.com/HSU-ANT/gstpeaq> ·
  <https://www.dafx.de/paper-archive/2015/DAFx-15_submission_12.pdf>
- **AES TD1008.1.21-9, "Recommendations for Loudness of Internet Audio
  Streaming and On-Demand Distribution"** (2021, supersedes TD1004) — the
  loudness and true-peak recommendation item 9 defers to.
  <https://aes.org/technical-council/technical-document-aestd1008/> ·
  [PDF](https://aes.org/wp-content/uploads/2024/01/20210924_TD1008_v3.13.pdf)
- **Pestana, Ma, Reiss, Barbosa & Black, "Spectral Characteristics of Popular
  Commercial Recordings 1950–2010"**, AES 135 (2013) — the study
  `_REF_SHAPE_DB` cites: ~5 dB/octave decay from 100 Hz to 4 kHz, flattening
  since the 2000s. <https://aes.org/publications/elibrary-page/?id=17010>
- **Nyberg, "Target Spectrums For Mastering"** — independent LTAS corpus:
  mean slope **4.53 dB/octave between 89 Hz and 4.5 kHz**, steepening above
  4.5 kHz, and stable across percussion levels in the mid region.
  <https://www.diva-portal.org/smash/get/diva2:1557981/FULLTEXT01.pdf>
- **Streaming normalisation targets (2026):** Spotify, YouTube, Tidal, Amazon
  Music and SoundCloud at −14 LUFS; Apple Music −16; Deezer −15.
  <https://www.izotope.com/community/blog/mastering-for-streaming-platforms>
- **Reference-track practice:** 1–3 genre- and era-matched references is the
  professional norm and what commercial tools implement; target curves are
  corpus-derived per genre with tolerance ranges, not universal.
  <https://www.izotope.com/community/blog/how-to-use-mastering-references> ·
  <https://downloads.izotope.com/docs/tonal-balance-control/meters-and-target-curves/index.html>

**Not yet resolved.** No source found quantifies the average spectral slope
*above* 4.5 kHz for contemporary masters — both corpora stop there and say
only "steeper". That is the gap item 4 has to close empirically, and it is
the reason item 4 calls for a corpus and a tolerance band rather than a
number.

> **Closed 2026-09-08 — see §7.2.** A source does quantify it. The 4.53
> dB/octave figure attributed to Nyberg above originates in Elowsson &
> Friberg (AES 142, 2017), and that paper publishes the slope at every
> frequency to 15.7 kHz, not just the invariant range.

---

## 7. The replacement target is wrong too

**Added 2026-09-08, after §1–§6 had already shipped as commit `97609c0`.**

§2.1 established that the old target was a sixty-year average used as a
present-day target, and the fix pointed `_REF_SHAPE_DB` at a curve measured
from a catalogue of finished masters. That fix is wrong, in the opposite
direction, and by more than the original error. This section is the evidence
and the retraction.

Precisely: the shipped curve is the median of the **135 Neutral rows** of the
309-row corpus in `docs/tone-reference.json` — matching to a maximum
deviation of 0.05 dB — and all 309 were produced by **one automated mastering
service, from AI renders**. (Comparisons below labelled "service" use the
full 309 unless stated; the all-309 median is −1.53 dB over 2.5–12.5 kHz
against the shipped −0.80, so the two are close but not interchangeable.)

**What was replaced matters as much as what replaced it.** Before `97609c0`,
`_REF_SHAPE_DB` was derived from Pestana, Ma, Reiss, Barbosa & Black, AES 135
(2013) — 772 commercial recordings, published. The swap therefore went from a
peer-reviewed corpus to one vendor's house algorithm applied to AI renders.
The criticism that motivated it was sound: a 1950–2010 average *is* shifted
for present-day music. But the answer to "this study is too old" is a newer
study, and Elowsson & Friberg (2017, 12,345 tracks) existed and was not
looked for. The commit's own comment records the reasoning — *"an honest
specific in place of a wrong universal"* — which reads as restraint and is
not: it replaced a dated measurement of music with a current measurement of a
vendor, and quietly redefined the goal as sounding like that vendor.

That comment also states, as fact, that *"real masters hold roughly level
from 315 Hz to 10 kHz and then fall off a cliff."* *Measured:* they do not.
Across that span the published mean falls **15.7 dB** (+0.17 at 315 Hz,
−8.54 at 4 kHz, −15.57 at 10 kHz). What holds level there is the service's
own output: **+0.28, +0.41, −0.00**. An observation about one algorithm was
written down as a property of commercial music, and everything downstream
inherited it. `docs/tone-reference.json` says so in its own metadata: *"This is
a target for this tool's material, not a general commercial reference."* It
was shipped as a general commercial reference anyway. AI renders are bright
before anything touches them (§1, Suno source measures −4.83 in the presence
band), so a curve fitted to masters *of* them inherits that.

### 7.1 What the new evidence is

*Measured.* Thirteen contemporary commercial tracks captured through the
References tool (electronic, pop, country and metal; `reference-library.json`).
Two of fifteen were rejected: they read −50.6 and −43.6 dB at 10 kHz, against
a 1st percentile of −29.1 dB across 317 masters known to be real. No record
does that; those two captures are broken, not dark. The gate is derived from
the known-real distribution, not from agreement with any target, so it cannot
reject a capture merely for disagreeing.

*Measured.* The capture chain was validated by playing a known file through
the speakers and capturing it back through loopback: **0.28 dB mean error,
0.53 dB worst, 250 Hz – 12.5 kHz**. The chain colours nothing. (An earlier
run of this test was invalid — other audio was playing and the loopback heard
both. The script now aborts unless the recording correlates with what it
played.)

*Measured.* Short excerpts understate a master's top end by **−1.35 dB on
average, −4.45 dB worst**, with up to 5.71 dB of spread between 30 s windows
of the same track. Applied as a correction throughout this section.

*Cited.* **Elowsson & Friberg, "Long-term Average Spectrum in Popular Music
and its Relation to the Level of the Percussion", AES 142nd Convention (2017),
paper 9762. 12,345 tracks.**

### 7.2 The slope above 4.5 kHz — §6's open question, closed

The paper fits the mean LTAS with two quadratics on a log-frequency axis of
60 bins/octave over 30 Hz – 15.7 kHz, and publishes the derivative, so the
slope is available at every frequency rather than as one average:

| centre | slope dB/oct (PSD) |
|---|---:|
| 200 Hz | −2.350 |
| 400 Hz | −3.668 |
| 800 Hz | −4.985 |
| 1.6 kHz | −6.303 |
| 3.2 kHz | −7.621 |
| 6.4 kHz | −8.938 |

*Measured.* Their Eq. 7 reproduces every row of that table to three decimals
in our code, which is the check that the axis mapping is right. The 800 Hz
row (−4.985) is what the "≈5 dB/octave" figure in §6 refers to, and the
"4.53 dB/octave" is their 89 Hz → 4.5 kHz two-point slope, not a broadband
constant. **The slope is not linear in log frequency — it steepens
continuously**, which is why a single number was never going to describe it.

*Measured.* Their figures are vector art, so the plotted curves are in the
PDF as polylines. Figure 5 draws both fittings over the actual mean LTAS, and
because the fitted curve has a known closed form it calibrates its own axes:
fitting page coordinates to Eq. 6 gives a residual of **0.001 dB**. Reading
the grey curve through that mapping recovers their real measured mean.
**The quadratic misstates it by only −0.26 dB across 2.5–12.5 kHz**, so the
fit is faithful and "the target only looks bad because a quadratic
extrapolates badly" is not available as a defence.

### 7.3 The measurement

Departure from the paper's measured mean, in dB, by zone. Normalised the same
way throughout: 1/3-octave band power relative to the 200 Hz – 2 kHz median,
with the paper's density converted to band power by +10·log₁₀(0.2316·f₍c₎).

| zone | commercial (13) | Shimmer output | service (309) | **`_REF_SHAPE_DB`** |
|---|---:|---:|---:|---:|
| bass 63–160 Hz | +7.1 | +6.6 | +9.3 | **+9.3** |
| low-mid 200–500 Hz | +1.1 | +0.4 | +0.9 | **+0.7** |
| mid 630 Hz–1.6 kHz | +0.4 | +1.2 | +0.9 | **+0.8** |
| presence 2–5 kHz | +0.9 | +3.8 | +7.0 | **+7.6** |
| air 6.3–12.5 kHz | +4.4 | +5.6 | +12.2 | **+12.9** |

### 7.4 Why the captures are the trustworthy side

Thirteen tracks is a small sample, and it leans electronic. It would be easy
to dismiss. The reason not to is that they depart from the paper's mean in
precisely the shape the paper predicts they should.

The paper's §4.1 and Figure 7: material with more percussion sits above the
dataset mean **in the bass and in the treble**, and tracks it through the
mids, monotonically across all 11 percussion groups. Separately, Hove, Vuust
& Stupacher (*JASA* 145, 2019, Billboard Hot 100 1955–2016) find bass has
risen over time, strongest below 100 Hz. Contemporary pop and electronic
music is at the percussive end of a corpus whose heaviest contributors are
folk and classic rock CD masters.

So the prediction is a smile: up at both ends, flat in the middle. The
captures give **+7.1 bass, +1.1 low-mid, +0.4 mid, +0.9 presence, +4.4 air**
— that is the predicted shape, and the presence band lands within 1 dB of a
12,345-track mean. The shipped target instead climbs from +0.8 in the mids to
+7.6 to +12.9 and never comes back. Nothing in the literature predicts a
monotonic ramp, and no corpus measured here produces one.

**Two corpora with opposite biases bracket the answer.** The published mean
skews old and folky; the captures skew contemporary and electronic. They
differ by 4.4 dB in the air band. The shipped target sits 8.5 dB outside that
bracket on the bright side.

### 7.5 How wrong, and where

*Measured, triangulated three ways.* Against the paper's real measured curve,
`_REF_SHAPE_DB` is **+10.69 dB** across 2.5–12.5 kHz. Against the 13 captures
it is **+7.76 dB**, or +6.4 dB after the excerpt-bias correction. The shape
test above says the captures are the better contemporary estimate.

**Best estimate: the target runs about 8 dB hot over 2.5–12.5 kHz against
contemporary commercial masters, and the divergence begins at 1.25–1.6 kHz,
not at 4.5 kHz.** Target minus capture median, band by band: +1.30 at
1.25 kHz, +2.37 at 1.6 kHz, +4.12 at 2 kHz, +5.75 at 2.5 kHz, +8.03 at 4 kHz,
+8.47 over 5–12.5 kHz. The published corpus agrees with the captures to
within 0.2 dB at 1.6 and 2 kHz — two corpora with opposite era and genre
biases converging on the same numbers, both disagreeing with the target.

Note that 2 kHz sits *inside* the 200 Hz – 2 kHz normalisation window, so the
error has begun eating its own anchor. And the root of it is a mid-slope
disagreement rather than a treble defect: from 315 Hz to 2 kHz the paper falls
4.4 dB and the captures track it, while the target falls 0.3 dB. A curve that
is flat where real music tilts down reads high at both ends once it is
normalised to the middle. That is the same mechanism §2.1 identified in the
*old* target — "the excess is inherited from the mids, not created in the
top" — which is why a fix scoped to the air band would not work.

Bass, low-mid and mid are within about 2 dB of contemporary masters and need
no change. Against the paper the target is +8.45 dB in the bass, but the
captures are +7.1 there too, so that gap is the paper's era bias rather than
a target defect.

**The 89 Hz – 4.5 kHz invariant slope must not be used as evidence that the
low end is calibrated.** An earlier draft of this section did exactly that,
on the grounds that the target reads −4.28 against −4.53 published. Seven
independent reviews rejected it and they are right, for two reasons.

*Measured.* It is a two-point secant, structurally blind to any error common
to both endpoints. The target's PSD error against the paper is **+9.36 dB at
89 Hz and +10.10 dB at 4.5 kHz**; the slope sees only the 0.74 dB difference,
while the **RMS residual across the very span the test covers is 4.82 dB**.
A statistic that passes a curve 4.8 dB RMS wrong is measuring nothing. The
decisive counterexample is in this repository's own history: the pre-`97609c0`
target scores −4.545, *closer* to the paper than the current one, while
sitting about 4.9 dB above it everywhere.

*Cited and measured.* The ±0.055 dB/oct figure is not a tolerance. It is the
standard deviation between eleven **group means of ~1122 tracks each**
(§4.2), and it is the argmin of a two-dimensional search over endpoint pairs
(Fig. 8) — a selected minimum. The per-track standard deviation of the same
statistic measured here is **0.744 dB/oct across the 309 service masters and
1.085 across the captures**, thirteen to twenty times larger. Against a real
tolerance the target (−4.281), the service masters (−4.404) and the paper
(−4.412) are indistinguishable, and the captures (−5.188) are about 0.7 SE
out rather than anomalous.

This is the `purity` trap from §2.5 in a new costume: a number that cannot
fail, read as evidence because it looked like one. The invariant is worth
keeping as a coarse tilt check with an honest tolerance near ±1.5 dB/oct, and
it must never be quoted as a statement about level or shape.

### 7.6 What follows

1. **`97609c0` must not merge as-is.** It is branch-only, so nothing has
   shipped to a user. `main` still carries the sixty-year-average target from
   §2.1, which is wrong in the other direction. Neither is correct; the
   product needs a derived target, not a choice between two bad ones.

2. **Derive the target, and make the derivation the artifact.** Not a
   hand-edited curve. The constraint is sample size: per-track standard
   deviation in the 2.5–12.5 kHz mean is 3.7 dB, so **≈55 captures brings the
   standard error under 0.5 dB and ≈150 under 0.3 dB**. There are 13. The
   References tool is the machine for this and already exists.

3. **Adopt the 89 Hz – 4.5 kHz invariant as a standing check**, at −4.53
   dB/oct. Across the paper's 11 percussion groups its between-group standard
   deviation is 0.055 dB/oct, so it is genre- and material-independent —
   the one figure in the paper that does not inherit its corpus bias. It
   belongs in the test suite against any target we ship.

4. **Fix the References tool before believing another of its reports.** It
   published "8.4 dB darker" from a median over 15 captures, two of which
   were broken. Three defects in `shimmer/references.py`: no validity gate;
   capture level is discarded, which is the evidence that would diagnose a
   broken capture; and `report()` states a verdict with no uncertainty and no
   excerpt-bias correction.

**Confidence.** The direction and rough magnitude above 1.6 kHz are
*measured* and agree across independent routes. The exact per-band values are
*not* settled and should not be until item 2 is done — 13 tracks cannot set a
29-band curve.

### 7.7 What was done to try to break this

§7.1–7.6 were written first and then attacked, because the same investigation
had already produced three claims that did not survive checking (§2.1, §2.11,
and the loudness recommendation withdrawn in §4). Everything below either
confirms or corrects what is above; nothing here was known when it was
written.

**The capture path was validated end to end, twice.** *Measured.* The
loopback leg first: a file played through the speakers and caught on loopback
matched the file on disk to **0.28 dB** mean, 0.53 worst, 250 Hz – 12.5 kHz.
That left Spotify's own decoder and equalizer untested, and every commercial
capture came through them. So eight service masters that exist on this disk
were played through Spotify as local files and captured:
**−0.57 dB ± 0.38 over 2.5–12.5 kHz across eight paired controls**, with a
flat per-band difference — no tilt, no codec ramp, no equalizer signature,
and every capture landing inside the range of windows from its own source.
`scripts/tone-evidence/spotify_control.py`. **The captures are sound.**

**Seven independent reviews and a synthesis were run against §7.1–7.6.** Four
re-derivations, each on a different lens, and three skeptics briefed to refute
it — one of them specifically to argue the shipped target is closer to right
than the published corpus is. *Measured.* **All three skeptics returned "not
refuted"**, the assigned defender reporting that its position lost. The
headline arithmetic reproduced by five independent routes, including a
from-scratch reimplementation of the paper's §2.2 pipeline and a synthesis
check that built noise to the paper's exact PSD and measured −11.65 against
−11.75 predicted. **13 of 13 captures sit below the target in every band from
2.5 to 8 kHz** (sign test p = 0.00024); the brightest single commercial
capture in the set is still 2.00 dB below it.

Three things they corrected, all of which make the defect **larger**:

1. **"Correctly calibrated below 4.5 kHz" was false**, unanimously. The
   divergence begins at 1.25–1.6 kHz. §7.5 above is the corrected version;
   the claim came from over-reading the invariant-slope test.
2. **The invariant-slope test is invalid as evidence about level**, for the
   reasons now recorded in §7.5. This is the `purity` failure of §2.5
   repeating: a statistic that cannot fail, mistaken for evidence because it
   returned a number. It was nearly written into the test suite as
   checklist item 13 before this caught it.
3. **The excerpt-bias correction of −1.35 dB is not a solid measurement**
   (n=8, se 0.78, 95% CI [−3.19, +0.50]) and the Spotify control supersedes
   it: 21–23 s captures land within 0.75 dB of the full file. Carry
   **−0.6 ± 0.4 dB**.

One quoted figure was also simply wrong and is withdrawn: an intermediate
summary gave the lower bound of the defect as "+3 dB versus the captures".
That number is the *captures'* distance from the paper, not the target's
distance from the captures. **Target minus captures is +7.92 dB.** The
defensible bracket is +7.9 to +10.7 dB, and the paper half of it should be
carried as a direction-of-agreement witness rather than quoted as a bound.

**Everything above is re-runnable.** The scripts that produced every number
in §7, what each one establishes, and the two results that are traps rather
than evidence are indexed in `scripts/tone-evidence/README.md`,
which is gitignored: it is local working evidence, not product. They are
scripts with hardcoded paths and no tests, reading local audio that is not
distributed. Kept because without them §7 is a set of assertions
nobody can re-check, and re-deriving it costs days.
