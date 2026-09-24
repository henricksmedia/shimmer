# The sound chain, checked stage by stage

Audit of 2.0.0, 2026-09-23. Every stage of `render()` was checked four ways:

1. **What users report.** The faults people describe in Suno and Udio songs.
2. **Why it happens.** The most likely technical cause.
3. **What trusted engineers do.** Mastering practice from Sound On Sound,
   AES TD1008, Bob Katz, Ian Shepherd and plugin manuals. Vendor pages are
   marked as vendor.
4. **Whether it works.** Measured on real songs, and on clean songs, where it
   should change nothing.

Nothing in the app was changed by this audit. The full research reports, the
measuring scripts and their raw numbers are kept out of this public repo, in
the private folder (`private/research/2026-09 chain audit/`, see
[STYLE.md](STYLE.md), "Public and private"). The sources are listed
at the end.

**Words used here**

- **LUFS**: loudness as a streaming service measures it.
- **dBTP**: true peak, the highest point of the wave between samples.
- **PLR**: peak-to-loudness ratio, how far the peaks stand above the loudness.
  Bigger means punchier.
- **Sones**: how loud a change sounds to the ear, from the ear model in
  `shimmer/perceptual.py`. The damage limit for a fix is 0.10 sones.
- **Oversampling**: working at a higher sample rate for a moment so a clipper
  does not fold harsh new tones back into the audible range (aliasing).

---

## 1. Verdicts

| Stage | Its job | Verdict | The main reason |
|---|---|---|---|
| Output rate | Change the rate with no audible change | **Works** | Flat to 18 kHz; its weak spots sit above 20 kHz |
| De-click | Find and fill pops | **Doesn't work** (off in the app) | Flags drum hits; misses real pops in dense music |
| Fixed tones (notch) | Remove steady generator whistles | **Works**, one false hit | Cut a real musical note (A7, 3514 Hz) on Alive Again by 15.8 dB |
| Shimmer | Remove fizzy, flickering hash | **Doesn't work on real songs** | Finds only the flicker it was trained on; trained to *keep* steady Suno sizzle |
| Sibilance (de-esser) | Turn down harsh "s" sounds | **Partly works** | Good design; too gentle, and misses held and steady "s" |
| Harshness (dynamic EQ) | Cut a harsh band while it sticks out | **Partly works** | Acts on loudness, not on sticking out; over the damage limit on 2 of 5 songs |
| Low-mid build-up (dynamic EQ) | Cut mud while it builds up | **Partly works** | Same design as Harshness; acts 19–30 % of the time on every song |
| Tone curve | Move the tone toward released music | **Partly works** | Target too dark; +2 dB cap too low; two guards don't work |
| User EQ | Do exactly what is set | **Works** | Measured to the setting |
| 25 Hz low-cut | Remove rumble and DC | **Partly works** | Adds up to 1 dB of peak for no loudness |
| Loudness gain | Reach the target | **Works** | Lands 0.02–0.32 LU under; no correction loop |
| Peak shaper | Catch the peaks before the limiter | **Partly works** | Does all the peak work at −9 LUFS, with no oversampling: most of the chain's damage |
| True-peak limiter | Hold the ceiling | **Works** | Safe; gives away 0.15 dB; barely works on real songs |
| Meters and release check | Measure correctly | **Works** | Within 0.05 LU of ffmpeg |
| Export and dither | Write the file cleanly | **Works**, one flaw | 16-bit WAV rounds down instead of to nearest: +3 dB noise, tiny DC |
| Album mode | Keep songs' levels relative | **Works** | Loudest song 0.32 LU short |

---

## 2. What users complain about, by Suno version

**Where this comes from:** every post in r/SunoAI, r/udiomusic and three
audio subreddits from January 2024 to 23 September 2026, read through the
Arctic Shift Reddit archive. That is 235,254 posts, plus the comment threads
under 2,566 complaint posts. The complaint counts also draw on Hacker News,
VI-Control, KVR and press coverage.

**How to read the counts:**
- **Threads:** how many Reddit threads raise the complaint.
- **Real:** that count after removing false hits, such as prompt lists
  ("tape hiss") and guitar "distortion". About 70 % of hits were real
  overall.
- **v5.5 → v6:** posts per 1,000 while each model was Suno's default.
  - v6 covers only its first two weeks, and launch weeks always spike, so
    compare the rows against each other.
  - Two exceptions: the Shimmer row shows v4, where it peaked, and Endings
    shows v4 → v5.5 → v6.

The full report and the dataset are in the research folder (`reports/5`,
`data/reddit/`).

| # | Complaint | Threads (real) | v5.5 → v6 | Covered by |
|---|---|---|---|---|
| 1 | Distortion, clipping, crackle | 1005 (~600) | 16 → **28** | **Nothing** for clipping; de-click is off |
| 2 | Steady hiss, noise floor | 744 (~610) | 10 → **19** | **Nothing** (Shimmer is for the moving kind) |
| 3 | Endings: cut off mid-word, no fade, long intros | 884 (~575) | 25 (v4) → 12 → 21 | **Nothing** |
| 4 | Muffled, muddy, dull, vocals buried | 709 (~530) | 8 → **48** | Partly: tone curve, too weak (§4) |
| 5 | Shimmer, sizzle, fizz | 605 (~530) | 32 in v4, 4.6 → 10 | Shimmer card, which misses it on real songs (§3) |
| 6 | "Sounds like an MP3", 16 kHz cutoff | 587 (~470) | 7 → **17** | Lack of air; can't be rebuilt without a trained model |
| 7 | Gets worse later in the song, or after Extend | 633 (~455) | 9 → **26** | **Nothing.** Every fix uses one setting for the whole song |
| 8 | Metallic or robotic vocals, static on the voice | 592 (~415) | 10 → **18** | **Nothing** (§3) |
| 9 | Too quiet or too loud | 381 (~170) | 5 → **15** | Loudness target |
| 10 | Over-compressed, squashed | 281 (~170) | 4 → **12** | **Nothing.** No check or warning |
| 11 | Stereo: narrow, mono, phasey | 302 (~165) | 5 → **14** | **Nothing** (the release check tests mono only) |
| 12 | Sibilance, harsh "s" | 139 (~105) | 2 → 2 | Sibilance |
| 13 | Too much reverb or echo | 100 (~55) | 1 → **7** | **Nothing** |
| 14 | Level jumps at section joins | 93 (~55) | 1 → 2 | **Nothing** |
| 15 | Weak or boomy bass; weak drums | 129 (~75) | 1 → 4 | **Nothing** |

Not fixable in mastering, but common: ghost vocals and gibberish (~360),
mispronunciation, voice drift and warble. Shimmer should name these, not
pretend to fix them.

### Share of each version's complaint threads

| Complaint | v3.5 | v4 | v4.5 | v5 | v5.5 | **v6** | Udio |
|---|---|---|---|---|---|---|---|
| Muffled, muddy | 11% | 9% | 24% | 19% | 15% | **38%** | 12% |
| Hiss, noise floor | 15% | 19% | 10% | 23% | 20% | **28%** | 6% |
| Worse later in the song | 13% | 13% | 17% | 14% | 18% | **24%** | 11% |
| Metallic vocals | 15% | 10% | 10% | 15% | 18% | **22%** | 9% |
| Shimmer | 3% | **37%** | 13% | 10% | 15% | 22% | 2% |
| Over-compressed | 4% | 4% | 4% | 7% | 8% | **14%** | 6% |
| Too much reverb | 0% | 0% | 1% | 3% | 2% | **9%** | 1% |
| Endings | 29% | 30% | 18% | 19% | 20% | 14% | 22% |

### What changed in v6 (first two weeks)

- **Worse:**
  - **Muffled:** 207 posts say worse, 7 say better.
  - **Hiss:** 65 worse, 11 better.
  - **Reverb and echo:** 51 worse, 5 better.
  - **Compression:** 62 worse, 29 better.
  - Also a "haze" over the vocals, and muffling that grows toward the end.
- **Better:**
  - **Stereo width and fullness:** 47 better, 26 worse.
  - Voices stay more consistent.
  - Some users say shimmer in intros is gone.
- **In short:** v6 trades shimmer for muffle. The complaint Shimmer was named
  for is now a smaller share than dullness, hiss and late-song decay.

### The vocal hiss heard on the test song

This is a common, lasting complaint. About 210–260 Reddit threads describe
a hiss, static or sizzle on the voice.

**By version:**

| Version | Items |
|---|---|
| v4 | 74 |
| v5 | 86 |
| v5.5 | 82 |
| v6 | **65, in only two weeks** |

**Where users place it:**
- **Pitch:** 5–8 kHz, then 6–12 kHz.
- **When:** on breaths and high notes.
- **Over time:** 29 items say it gets worse later in the song.

**What users say helped, one or two reports each:**
- a de-esser at about 6–6.5 kHz plus a 2–3 dB high-shelf cut at 8–10 kHz, on
  the vocal stem only
- a dynamic EQ notch
- RX Voice De-noise
- remastering on an older model
- cutting the song before the hiss starts

Prompts don't reliably help.

---

## 3. The cleaning fixes

### Why Shimmer misses the vocal sizzle

Measured on the test song:

- **The sizzle is not too much energy.** 3.5–7 kHz sits 6–11 dB *below*
  clean songs. It is the wrong texture, not too much level.
- **It is centered.** The sides are 15–17 dB under the middle; clean songs
  are 0–10 dB.
- **It does not flicker.** Its level moves no faster than clean music. The
  Shimmer model looks for flicker.
- **It sits on the vocal.** A stem split puts almost all of it in the vocal
  (listening rounds 4 and 5).

Planted into a clean song, a steady centred sizzle like this was **0.5–1 %
removed** by Shimmer at 100 %. The noise it was trained on was 30 % removed.

**The root cause the docs never recorded:** the model's "clean music" for
training was 43 of the author's own Suno masters
(`scripts/hash_learn/data.py:111-121`). Any steady Suno sizzle in them was
labelled as music to keep. The model learned to keep exactly this sound.

**And mastering makes it louder.** On this song the tone curve adds +2 dB
from 2.5 kHz up. After the loudness gain, 3.5–7 kHz comes out 1.6 dB louder
than the rest of the mix.

### How the safety limits were set

Each fix's top Amount was set from `scripts/efficacy_harness.py`. That
harness renders only the song's loudest 8 seconds, as if it were a whole
song (`:118`, `:176-178`), so each fix plans from those 8 seconds. The app
plans from the whole song (`render.py:202`). Measured both ways on the same
8 seconds, in sones:

| Song | Sibilance (8 s / whole song) | Harshness | Low-mid |
|---|---|---|---|
| Alive Again | 0.056 / 0.016 | 0.029 / 0.024 | 0.009 / 0.021 |
| Falling For You | 0.047 / 0.045 | 0.044 / **0.076** | 0.041 / 0.052 |
| Leave the World Behind | 0.005 / 0.010 | 0.050 / **0.148** | 0.053 / 0.079 |
| Stars | 0.059 / 0.073 | 0.097 / **0.103** | 0.099 / 0.048 |
| Hey | 0.100 / **0.107** | 0.000 / **0.065** | 0.036 / 0.032 |

On the whole-song plan, Harshness goes over the 0.10 limit on 2 of 5 songs
and Sibilance on 1. The limits in `STEP6-FIXES.md` need measuring again,
the way the app runs.

### Each fix

**Sibilance (de-esser)**
- **Design:** it follows good practice.
  - Split-band (4.5–10 kHz), with no phase shift.
  - About 4.5 ms of lookahead and a 1 ms attack.
  - It judges brightness against the song's own mids.
  - The sides get half the cut.
- **Measured:** it acts 2–11 % of the time, cutting 1–3 dB on average.
- **What's wrong:**
  - **Too gentle.** A consonant 12 dB over its surroundings gets about 4 dB
    of cut.
  - **Long "s" sounds partly escape.** An "s" longer than about 150 ms raises
    the level it is judged against.
  - **Centred songs fight it.** On a song whose top is very centred, the
    centre weighting (`deesser.py:154-156`) makes a consonant need 17–29 dB
    before it counts in full.
  - **Steady sizzle.** Anything that never jumps, it never touches.
  - **A log warning** at `deesser.py:107`. No bad values reached the output.

**Harshness and Low-mid build-up (dynamic EQ)**
- **How it picks a band:** the one 1/6-octave band that most often rises
  above its neighbours.
- **What it does with it:** runs a gentle compressor on that band against
  the band's own 70th-percentile level (`dynamic_eq.py:218-219`).
- **What's wrong:**
  - **It works on level, not on the band sticking out.** It says it cuts
    "only while it sticks out", but in this mode it never looks at the
    neighbours. So it acts about 30 % of the time on every song, clean ones
    included.
  - **The chosen band usually doesn't stick out:** −1.7 to +3.3 dB above its
    neighbours.
  - **It often lands on the edge of its range** (2000 Hz, 200 Hz).
  - **The filter is narrower than stated.** Running it forward and backward
    doubles the bell, so the real Q is narrower than 3 / 1.4.

**Fixed tones (notch)**
- **Real generator lines:** it found and removed them (14.2–19.2 kHz,
  on the codec's grid).
- **One false hit:** on Alive Again it cut 3514 Hz by 15.8 dB, taking 6.6 %
  of the 4 kHz octave. 3514 Hz is the note A7, and the same scan lists
  C7, D7, E7 and F7 on that song.
  - That line stood out only 58 % of the time, but the rule says "three
    quarters of the time" (`notch.py:115-117`).
  - **Guard to add:** a line that is not on the generator's grid, at a
    musical note's pitch, is music.
- **Blind spot:** lines in the busy 3.5–7 kHz range can't clear the 6 dB
  rule. A planted 5.2 kHz line was missed.

**Shimmer (the model)**
- **Only works on training-style flicker** (above).
- **Wrong range on screen:** the card says 5–12 kHz; the model works on
  1.5–16 kHz.
- **Harmless:**
  - No watery "musical noise".
  - No change in stereo width.
  - Running the mono-trained model on each channel made no measurable
    difference.

**De-click** (off in the app)
- **False hits:** on clean songs it flags 2–17 spots a minute, 38 % of them
  on drum hits, and "fills" them with a guess.
- **Not ready:** it stays off until it can find real pops in dense music.

**The fixes together:** they don't fight each other. Running them together
matches running them one at a time within 0.01 dB. All are zero-phase, and
the level holds.

---

## 4. The mastering stages

Measured on five raw Suno songs × three targets, against two commercial
masters and the DistroKid masters of the same songs.

| Target | Output | True peak | Peak shaper: most cut | Hit peaks lost (median) | PLR after |
|---|---|---|---|---|---|
| −9 LUFS | −9.02 to −9.32 | −1.10 to −1.16 | 3.0–7.7 dB | 2.3–5.7 dB (worst 8.8) | 7.9–8.2 |
| −11 LUFS | −11.00 to −11.10 | −1.08 to −1.34 | 1.5–5.8 dB | 0.8–3.7 dB | 9.7–10.0 |
| −14 LUFS | −14.00 | −1.15 to −2.88 | 0–3.2 dB | 0–1.0 dB | 11.1–12.9 |
| Commercial pair | −9.1, −10.6 | **+1.07, +0.45** | — | — | 10.2–11.0 |

**Peak shaper**
- **Doing most of the work:** at −9 it cuts peaks by up to 7.7 dB, not the
  "top ~2 dB" its note describes (`limiter.py:84`). The limiter after it
  barely acts (0.3–1.4 dB).
- **No oversampling.** A clipper at the base rate folds harsh, off-key tones
  back into the audible range (aliasing).
  - On test tones those images reach −18 to −24 dB for notes at 9–13 kHz.
  - On music at −9 they reach −25 to −44 dB relative to the top end.
  - Oversampling 4× is standard (Ozone, FabFilter) and puts the images
    below about −80 dB.
- **Channels not linked:** each side is shaped on its own.
- **This is the main source of damage at −9 and −11:** softer drum hits and
  grit in the top end.

**Before the gain, the chain makes peaks worse**
- The 25 Hz low-cut shifts the timing of the deep bass slightly. That adds up
  to +1 dB of peak (lure) with no gain in loudness.
- With the tone curve, the steps before the gain raise PLR by 0.6–2.5 dB.
  The shaper then has to cut all of that back off.

**Tone curve**
- **Pinned at its limit.** On dark songs it sits at +2 dB from 2 to 16 kHz.
- **The target itself is darker than released music:** about 1.6 dB darker
  at 2–5 kHz and 3.5 dB darker at 6–12 kHz than the commercial pair.
- **Result:** presence on dark songs ends up 5–10 dB short of the
  commercial masters.
- **Two guards don't work:**
  - **The fizz-band guard never does anything.** Its 2 dB cap equals the
    overall 2 dB cap (`tone.py:91-95`, `:191-193`).
  - **The cutoff guard leaks.** The curve is spread between bands on a
    straight Hz scale (`tone.py:270-278`), so boost reaches past the
    song's top cutoff (+1.1 dB at the cutoff on the test song).
- **When no cutoff is found,** +2 dB goes onto 16–20 kHz, where there is
  mostly noise.

**Other stages**
- **Loudness gain:**
  - One gain with no second pass, so songs land 0.02–0.32 LU short.
  - A second pass closes it.
- **True-peak limiter:**
  - **Safe design:** detection at 8×, linked channels, 2 ms lookahead,
    50 ms release.
  - **Gives away about 0.15 dB** under the ceiling.
  - **Release never changes.** It is fixed and doesn't follow the music; pro
    limiters adapt it.
  - **Distorts deep bass:** −33 dB at 40 Hz with 3 dB of cut.
- **16-bit WAV:** the file writer rounds down instead of to nearest. That
  adds 3 dB of noise and a tiny DC offset.
  - FLAC is correct.
  - Harmless to the ear, but not the dither the code means to apply.
- **Stale docs:** ARCHITECTURE §3 and §13.4 describe an older export (an
  undithered 16-bit temp file for MP3, 4× detection). The code now encodes
  from float and detects at 8×.

### Why masters sound quiet next to released music

1. **At −9 LUFS, level is not the problem.** The loud parts reach −6.9 to
   −8.0 LUFS, as loud as the commercial pair.
2. **Tone is the biggest gap.** Shimmer masters are 2–7 dB short in
   presence. With the loudest 30 s level-matched, the ear model hears
   "The Little Things" 21 % quieter (about 3 dB) than its DistroKid master.
   The ear hears presence as loudness.
3. **Peaks.** Hit records go past 0 dBTP (only 20 % of the 2024 top 10 stay
   under it). Shimmer holds −1 dBTP, so it has to remove 2–3 dB more peak,
   and it does that with the un-oversampled shaper. The result: flatter
   drums and grit.
4. **The −14 choice** plays 5 LU quieter in a player that doesn't match
   levels. That is expected; the screen already says so.
5. **Not checked:** the listening setup. With Spotify's volume matching on,
   Spotify plays at −14, so a −9 master in Windows Media Player should
   sound *louder*. Worth ruling out.

---

## 5. What a pro chain has that Shimmer lacks

| Pro stage | Shimmer | Do the numbers say it matters? |
|---|---|---|
| Resonance control (soothe-style, mid/side) | Dynamic EQ on one band | Yes: for the vocal sizzle, and before any brightening |
| Gentle "glue" compression, 1.1–2:1, 1–2 dB | None | Likely: spreads the peak work so the shaper cuts less |
| Upward or parallel compression | None | Possible: density without touching peaks. Test by ear |
| Oversampled clipper, 0.5–2 dB, then limiter, 1–3 dB | Clipper not oversampled, cuts up to 7.7 dB | **Yes, the clearest gap** |
| Limiter release that follows the music | Fixed 50 ms | Some: less bass grit and pumping |
| Tone target with room to move | One dark target, ±2–3 dB cap | **Yes: the biggest loudness gap** |
| Mid/side EQ and width | None | Minor: the chain narrows nothing, and bass is already centred |
| Low-end mono | None | Not needed: bass side level is already −12 to −21 dB |
| Saturation or exciter | None | Not needed on this evidence; engineers say use sparingly |
| Checks on the encoded file | Checks the render | Worth adding: true peak after MP3/AAC encoding |

**A warning from the research:** brightening a Suno song makes its
artifacts "the signature of the master" (a vendor mastering service; no
independent source was found). So the tone fix and the vocal-sizzle fix go
together: take the sizzle down first, then brighten.

---

## 6. Build plan, ranked

Each sound change goes through a level-matched A/B, and the author's blind
pick decides (`GOALS.md` rule 4).

### A. Fix what exists (2.0.1): mostly bugs, each measurable

**Status, 2026-09-24:** done in 2.0.1, except item 4 and part of item 3.
- **Item 1:** Sibilance's top is now 6.5 dB (was 7.2) and Harshness's
  3.3 dB (was 5.1); Low-mid build-up was under the limit.
- **Item 2:** the shaper runs at 4x with linked channels.
- **Item 3:** the cutoff guard holds per FFT bin, and nothing above 16 kHz
  is boosted with no cutoff. The inert fizz cap was removed, not tightened:
  a real cap would darken masters that §4 found already too dark.
- **Item 4 not done:** a zero-phase low-cut smears kicks with pre-echo, so
  the filter code refuses it on purpose (SOUND-CHANGES, "Low-cut runs one
  way").
- **Item 5:** one correction pass after the limiter.
- **Item 6:** the notch skips lines at a note's pitch that are off the
  200 Hz grid. The duty rule was left as it is: real generator lines
  measure 0.50-0.64 too.
- **Item 7:** 16-bit files round to the nearest step.
- **Item 8:** the description was changed to match the code. The band
  compressor was chosen by measurement (STEP6-FIXES).
- **Item 9:** the docs are updated.

1. **Measure the Amount limits again on whole-song plans.** Fix the
   harness, then reset the top Amount for Harshness and Sibilance.
2. **Oversample the peak shaper 4×, and link the channels.** This is the
   biggest drop in damage for one change.
3. **Tone curve guards:**
   - Spread the curve on a log scale so the cutoff guard holds.
   - Give the fizz-band guard a real cap.
   - No boost above 16 kHz when no cutoff is found.
4. **Low-cut:** zero-phase, so it stops adding peak.
5. **Loudness:** a second pass so each song lands on target.
6. **Notch:** skip lines at musical-note pitches that are off the
   generator's grid, and make the duty rule match its "three quarters of
   the time" note.
7. **16-bit WAV:** round to nearest after dither.
8. **Dynamic EQ:** make it cut only while the band sticks out above its
   neighbours, as its own description says.
9. **Docs:**
   - Update ARCHITECTURE §3 and §13.4.
   - Correct the Shimmer card's stated range.
   - Correct the peak shaper's note.

### B. New mastering stages the numbers support

10. **Spread the peak work:**
    - gentle glue compression (1.2–2:1, 1–2 dB)
    - then the oversampled clipper (0.5–2 dB)
    - then the limiter with a release that follows the music (1–3 dB)
11. **Tone target:**
    - Rebuild from released music (the capture library).
    - Allow more boost in presence (2–5 kHz).
    - Only after the sizzle fix in C, so brightening doesn't lift it.
12. **Check the encoded file:** measure true peak after MP3/AAC encoding in
    the release check.

### C. New cleaning tools for top complaints with no fix

Ordered by the Reddit counts in §2, weighted toward what is growing in v6.

13. **Hiss, on the vocal and underneath** (§2, complaints #2 and #8; both
    up sharply in v6):
    - Split out the vocal, the same split the Remix tab makes.
    - Take the steady hiss out of the vocal's top end only.
    - **Round 5 result (2026-09-23): C, "steady hiss taken out of the
      vocal".** The author's pick on the test song, 1:50. Taking out
      a per-pitch hiss floor from the vocal stem above 3.5 kHz removed the
      hiss, and what it took sounded like nothing useful. One song and one
      passage so far.
    - **Rounds 6–11 (2026-09-23): the author's "shimmer" identified.** It is
      not the forum sense of shimmer, and none of four fixes on the
      instruments touched it. It sits on the vocal, strongest at 4–8 kHz,
      and has two parts, both left after C:
      - **grain:** sharp spikes in time and pitch, removed by pulling each
        spot back to within 3 dB of its neighbours
      - **a moving hiss floor:** a floor measured every 2 s, so it follows
        the voice
      The "what it took" files of those two fixes hold what the author has
      heard all along.
    - A steady-floor de-noise for the whole mix is the same tool with a
      different target.
14. **Endings** (#3): trim silence and long intros, and add a clean fade.
    This is common and cheap.
15. **Worse later in the song** (#7, 9 → 26 per 1,000 in v6):
    - Compare the start with the end.
    - Let each fix change strength through the song.
    - Report where the decay starts, so the user can re-generate from
      there.
16. **Clipped loud parts and crackle** (#1): a de-clipper, and a de-click
    that finds real pops.
17. **Retrain the Shimmer model.** Its complaint is shrinking in v6 (22 %
    of threads) but was 37 % in v4, and older songs keep it.
    - Use clean music that isn't Suno output as the "keep" examples, and
      real codec damage as the "remove" examples (`SHIMMER-RESEARCH.md`,
      step zero).
18. **Joins and level jumps** (#14): find the section seams and smooth the
    level.

**Changed by the Reddit counts:**
- **Muffled** is the fastest-growing complaint (38 % of v6 threads), so the
  tone target (plan B, item 11) matters more than it first seemed. It still
  waits for item 13, so brightening doesn't lift the hiss.
- **Over-compressed** is up in v6 (4 → 12). The glue compression in item 10
  must first measure how squashed the song already is, and do nothing when
  it's already dense, as Ozone's assistant does.

---

## Sources

The research reports gave every source with its link; the main ones:

- **Complaints:**
  - Reddit, via the Arctic Shift archive (arctic-shift.photon-reddit.com):
    r/SunoAI, r/udiomusic, r/audioengineering, r/mixingmastering and
    r/WeAreTheMusicMakers, 2024-01 to 2026-09
  - Hacker News threads 46610728, 49665479, 42244599 and 39993648
  - VI-Control, "SUNO audio quality vs sample libraries" (May 2026)
  - MusicRadar, Digital Music News and Gearnews on Suno v6 (Sep 2026)
  - SingGAN (arXiv 2110.07468), on metallic noise in generated singing
  - SONICS (arXiv 2408.14080)
- **Mastering:**
  - AES TD1008
  - Sound On Sound:
    - "Crafting loud mixes"
    - "Multi-band compression tips"
    - "M/S Mastery"
    - "Clipping vs limiting"
  - Bob Katz on dither (digido.com)
  - Ian Shepherd (productionadvice.co.uk), on clipping, limiters and how loud
  - FabFilter Pro-L 2 manual (vendor)
  - iZotope Ozone 9 and 11 manuals, and mastering trends 2024 (vendor)
- **Earlier pages this builds on:** `SHIMMER-RESEARCH.md`,
  `MASTERING-SOURCES.md`, `STEP6-FIXES.md`, `GOALS.md`.
