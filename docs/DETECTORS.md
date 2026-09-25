# Detectors

Analyze marks a "What do you hear?" card **Found** only when a detector for
that card measures its fault. A card with no detector stays quiet rather
than guess: the 1.x detector recommended cleaning finished masters
(PITFALLS.md, "A metric that cannot fail").

Code: `shimmer/core/analyze/detectors.py`. Findings:
`shimmer/core/analyze/findings.py`. Every line below was set on the test
library (`scripts/test_library.py`, `docs/TEST-LIBRARY.md`): 284 AI songs
across generator versions, and a 31-song core set.

Every detector must pass three checks:

- **Quiet on finished masters.** The two masters in `assets/reference`
  raise no finding from any detector.
- **Found where the fault is.** A planted fault is found
  (`tests/core/test_core_detectors.py`).
- **The line marks the songs that stand out,** not every song.

## Levels and Amounts

Each finding has a level, **some** or **a lot**. For a card with its own
fix, Analyze turns the fix on at a starting Amount: 50 % for some and
100 % for a lot. Every fix's 100 % was already set under its damage limit
(`docs/STEP6-FIXES.md`). The user can change the Amount or turn the card
off, and Analyze does not turn it back on for that song.

## At upload (fast, about 2 s)

| Card | Measure | Some | A lot | Library |
|---|---|---|---|---|
| Fixed tones | The whole-file tone scan the notch uses | a tone found | | |
| Loudness | How far under the chosen loudness target | 1 dB under | | |
| Lack of air | Mean of the 8-16 kHz bands under the tone target, leaving out bands at or above 90 % of the song's cutoff | 3 dB under | 6 dB under | Typical song 4.7 dB under; 65 % of songs 3 dB or more |
| Low-mid build-up | Mean of the 200-500 Hz bands over the tone target | 2 dB over | 4 dB over | Typical song -0.2 dB; 7 % of songs 2 dB or more |

Both tone measures are the one mastering makes (`master/tone.py`,
`analyze_spectrum` against `REF_DB`).

- **Lack of air** is fixed by mastering's tone, not a cleaning tool. The
  finding offers Tilt: Bright (some) or Brightest (a lot), unticked, since
  the tone is the user's choice. Mastering boosts any band by 2 dB at most,
  so a song 5 dB dull comes up only 2 dB. The finding says so.
- **Low-mid build-up** turns on its dynamic EQ. How much that dynamic EQ
  acts does not follow the song's steady low-mid level (correlation 0.04
  on the core set). The steady part is what mastering's tone match cuts,
  by up to 3 dB.

## After the upload (slow, about 5-15 s each)

These run in their own job (`POST /api/detect`, docs/API.md), started as
soon as the song is loaded; Analyze waits for them.

| Card | Measure | Some | A lot | Core set | Finished masters |
|---|---|---|---|---|---|
| Sibilance | Share of the song the de-esser, at full strength, cuts more than 1 dB of 4.5-10 kHz (50 ms frames with sound) | 8 % | 14 % | Typical 2.7 %; top tenth 12 % or more; 9 of 31 never | 5 % and 1 % |
| Harshness | The same for the dynamic EQ in 2-5 kHz | 6 % | 15 % | Typical 3.3 %; top tenth 18 % or more | 0 % and 1.5 % |

Those fixes act only when their band sticks out above its usual level, so
how often they act is the measure. A finished master with real singing
still has "s" sounds: "Hey" reads 5 %, which is why the Sibilance line sits
above it.

### Vocal grain

- **Measure:** how much of the centre's 4-8 kHz the Vocal grain fix's
  **grain step** takes out: sharp spots standing more than 0.75 dB above
  their neighbours (7 bins by 9 frames).
  - Taken in 15 s stretches, leaving out the first, the last and quiet
    ones.
  - The half with the most voice in the centre counts (the 1-4 kHz
    energy of the mid against the side). The middle of those, in dB, is
    the score.
- **Lines:** 2.5 dB is some, 3.5 dB is a lot.
- **Starting Amount:** 40 % for some, and 75 % for a lot, the author's
  "strong" from the listening rounds. The fix's 100 % is "extra strong",
  over the damage limit, so Analyze never starts there.

| | Grain score |
|---|---|
| Library, typical song | 2.4 dB |
| Library, top tenth | 3.8 dB or more |
| Just Another Rain, the known worst case | 4.1 and 4.7 dB |
| Finished masters | 1.7 and 1.0 dB |

**Only the grain step counts.** The fix also takes a steady floor and a
moving floor, and on finished masters those take as much as or more than
on AI songs: a full, clean top end has a lot of steady high-frequency
sound. The whole fix's share scored the masters in the top third of the
library, so it could not tell grain apart. The grain step alone put them
in its bottom 20 % and 3 %.

## Not yet

- **Shimmer.** On the core set its fix acts on a typical song 1.4 % of the
  time, and it takes about 100 s a song. The fix itself is still waiting on
  its blind round. The author's "shimmer" was vocal grain, which has a
  detector.
- **Clicks and crackle.** The de-click still finds too few pops in dense
  music (docs/STEP6-FIXES.md). Its detector comes with that work.
- **Phasiness** has no fix, and so no detector.
