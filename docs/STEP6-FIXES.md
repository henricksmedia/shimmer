# Step 6: the fixes, measured

Every card under "What do you hear?" gets a real fix inside the app. A fix
turns on for users only when it passes the decision rule (`GOALS.md`):

1. It removes its problem on the test models.
2. The music it takes from a clean song stays under 0.10 sones, and that
   cost sets the top of its Amount slider.
3. It adds no new problems: pre-echo, warbly noise, pumping, lost width or
   softened hits.
4. It wins or ties in the author's blind listening round. This one is final.

## How each fix is measured

- **Test models** (`shimmer/artifacts.py`): a known problem planted into a
  clean song. Added for Step 6:
  - `consonants`: "s" and "sh" held 80-180 ms, "t" and "ch" 15-40 ms, each at
    its own pitch in 4.5-9.5 kHz, centred
  - `harshness`: resonances in 2-5 kHz that ring out on the loud notes
  - `mud`: a broad resonance in 200-500 Hz that swells when the low mids
    are busy
  - `phasiness`: the song's own tails with their phase scrambled
- **Real songs:** five of the author's clean masters, loudest 8 s each
  (Alive Again, Hey, Falling For You, Leave The World Behind, We Were Meant
  For The Stars). Four more carry their own hash and are left out.
- **The harness:** `scripts/efficacy_harness.py --cards <card>` runs the
  card's fix through the new engine's `render()`, exactly as the Master tab
  does. Results go to `docs/efficacy-core.json`.
  - **Removed:** the share of the planted problem the fix takes out, at two
    levels: 0.5 sones (just audible) and 2.0 sones (plainly there).
  - **Music taken:** what the fix takes from the clean song, in sones.
- **Side effects** (`shimmer/side_effects.py`), on the clean song: width
  (side against centre), hits (the peak just after each hit, against the
  level around it) and pumping (how the level outside the fix's band swings).
  Pre-echo is checked on a known drum hit in the unit tests.

## Sibilance: the de-esser

`shimmer/core/repair/deesser.py`. Split-band: while a consonant sticks out,
the 4.5-10 kHz band is turned down, fully in the centre and half as much in
the sides. It runs before mastering, so a spike is gone before the loudness
gain raises it.

**Why 1.x's de-esser failed** (-2 % on centred sibilance): it cleaned the
centre at 0.2x, its reference band was nearly empty, and it backed off on
hits, which "t" and "ch" are.

### First version: brightness alone

It cut whenever 4.5-10 kHz rose 3 dB above the song's usual balance against
500 Hz-4 kHz.

| | Removed, 2.0 sones | Removed, 0.5 sones | Music taken (mean / worst) |
|---|---|---|---|
| New "s, t, ch" model | 64 % | 44 % | 0.150 / 0.258 |
| Older "s" model | 52 % | 34 % | |

It acted a third of the time and cut hi-hats. On the real songs the
brightness reading swings 13-20 dB with the cymbals, so brightness alone
cannot tell an "s" from a hat.

### What tells a consonant from a cymbal

Planted consonants against the rest of each song, 5 ms readings (median;
the song's own moments at their 95th percentile):

| Song | Jump above the 300 ms around it | More centred than usual |
|---|---|---|
| Alive Again | 9.2 dB against 3.7 | 13.4 dB against 10.3 |
| Hey | 1.1 against 11.7 | 3.1 against 11.1 |
| Falling For You | 10.3 against 4.4 | 12.8 against 11.5 |
| Leave The World Behind | 8.6 against 3.1 | 14.3 against 6.5 |
| We Were Meant For The Stars | 6.2 against 8.4 | 9.7 against 10.1 |

Neither alone separates every song; together they do better. "Hey" is the
hard one: a bright, vocal-forward master with centred brightness all
through.

### Designs compared (Amount 100 %)

| Design | Removed 2.0 / 0.5 | Older model | Music taken, mean | Worst song |
|---|---|---|---|---|
| Brightness alone | 64 % / 44 % | 52 % | 0.150 | 0.258 |
| Higher trigger (8 dB) | 53 % / 23 % | 42 % | 0.069 | 0.122 |
| Centred only | 63 % / 37 % | 52 % | 0.119 | 0.185 |
| Jump only | 63 % / 41 % | 50 % | 0.129 | 0.249 |
| **Jump and centred** | **62 % / 36 %** | **50 %** | **0.095** | **0.168** |
| Jump and centred, 6 dB trigger | 55 % / 25 % | 44 % | 0.059 | 0.114 |

No design showed a side effect: width moved at most 0.05 dB, hits and
pumping not at all. Capping the cut at 8 dB instead of 12 dB took the same
music (0.094 against 0.095): the cost comes from how often it acts, not how
deep.

**Chosen:** jump above the surrounding 300 ms and more centred than usual,
3 dB trigger, 12 dB deepest cut at Amount 100 %. A band more than 20 dB
under the vowel never counts, so a dark voice's top harmonics moving with
its vibrato are left alone. Amount scales every cut, not only the deepest,
so a lower Amount takes much less.

### Where it acts on clean songs (Amount 100 %)

| Song | Music taken | Acting | Cuts in 8 s | Typical length | What it takes |
|---|---|---|---|---|---|
| Hey | 0.148 | 8.9 % | 26 | 20 ms | 99 % centre, loudest at 6.2 kHz |
| Alive Again | 0.084 | 11.9 % | 89 | 9 ms | 95 % centre, loudest at 5.1 kHz |

- On **Hey**, what it takes is centred, short and peaks at 6 kHz: that fits
  the song's own vocal consonants, and would fit centred hi-hats too. The
  numbers cannot say which. The blind round will.
- On **Alive Again**, 89 very short cuts look like hi-hat ticks. It never
  cuts deeper than 6 dB there, and the hits measure unchanged.

### Amount

Measured with the chosen design at 0.75 dB of cut per dB over the trigger
and 12 dB deepest ("tested strength"), with Amount scaling both:

| Share of tested strength | Removed 2.0 / 0.5 (new model) | Older model | Music taken, mean | Worst song (Hey) |
|---|---|---|---|---|
| 50 % | 40 % / 18 % | 33 % / 10 % | 0.045 | 0.084 |
| 70 % | 51 % / 24 % | 41 % / 13 % | 0.061 | 0.114 |
| 85 % | 57 % / 28 % | 45 % / 16 % | 0.072 | 0.133 |
| 100 % | 61 % / 31 % | 50 % / 18 % | 0.082 | 0.148 |

Music taken per song, same order: Alive Again 0.049 / 0.064 / 0.074 / 0.084,
Falling For You 0.039 / 0.053 / 0.063 / 0.073, Leave The World Behind
0.004 / 0.006 / 0.007 / 0.009, We Were Meant For The Stars 0.050 / 0.069 /
0.083 / 0.098, Hey 0.084 / 0.114 / 0.133 / 0.148. No side effect at any
Amount.

**Decision:** Hey reaches the 0.10 limit at about 60 % of the tested
strength, so that is the slider's 100 %: 0.45 dB per dB and 7.2 dB deepest.
If the blind round shows that what it takes from Hey is Hey's own harsh "s"
and the author wants it gone, that is the evidence to raise the top.

### Final numbers (the shipped settings)

| Amount | Removed, new model (2.0 / 0.5 sones) | Older model | Music taken, mean | Worst song |
|---|---|---|---|---|
| 50 % (the card's default) | 27 % / 11 % | 23 % / 6 % | 0.028 | 0.051 (Hey) |
| 100 % (the top) | 46 % / 21 % | 37 % / 12 % | 0.053 | 0.100 (Hey) |

Per song at 100 %: Alive Again 0.056, Falling For You 0.047, Leave The
World Behind 0.005, We Were Meant For The Stars 0.059, Hey 0.100. Width
+0.01 dB, hits and pumping unchanged. 1.x's de-esser: -2 %.

Unit tests (`tests/core/test_core_deesser.py`): consonants down more than
4 dB at the top; the song untouched between them (under -60 dB); nothing
below 2.5 kHz moves; nothing more than 20 ms before a hit (-60 dB); a
cymbal only in the sides left alone; the sides get half the cut; a dark
voice alone left alone; mono works; a preview window equals the export
(under -60 dB); bypass is bit-exact.

### Blind round

Built 2026-09-13 with `scripts/make_fix_round.py sibilance`, from the four
masters where the de-esser acts most (of 43 scanned, loudest 20 s at the
top Amount):

| Song | Acting | Typical cut | Why it is in the round |
|---|---|---|---|
| Dawn Through Smoke | 20 % | 28 ms | acts most |
| Crossing Wires - Backroads and Tides (Susan) | 9 % | 32 ms | long cuts: likely consonants |
| You Are the One | 7 % | 39 ms | long cuts: likely consonants |
| Pilot Light | 11 % | 11 ms | short cuts: does it touch the hats? |

Each set: 20 s where the fix acts most, as original, Amount 50 % and
Amount 100 %, level-matched and shuffled; the residual is what 100 % took
out. Waiting for the author's verdict.

## Harshness and Low-mid build-up: the dynamic EQ

`shimmer/core/repair/dynamic_eq.py`. One tool, two settings: up to two
bands in 2-5 kHz (Harshness), one band in 200-500 Hz (Low-mid build-up).
Found once per song; cut only while the band sticks out; the same cut on
both channels.

### Finding the band

Planted resonances on five real songs (2.0 sones):

- **Harshness** (planted near 2.6 and 4.4 kHz): found both on four songs,
  and on the fifth, 2245 Hz, the song's own strong band, with 4.5 kHz.
- **Low-mid build-up** (planted near 480 Hz): found 400-450 Hz on four
  songs; on the fifth it picked the song's own 200 Hz.
- Clean songs have their own bands sticking out 6-17 dB at times, so a
  dynamic EQ can cut real music.

### First version: a fixed 4 dB over the neighbours

| Card | Removed 2.0 / 0.5 | Music taken, mean | Worst song |
|---|---|---|---|
| Harshness | 17 % / 9 % | 0.060 | 0.111 |
| Low-mid build-up | 39 % / 8 % | 0.091 | 0.184 |

Too weak: the song's own notes at that band jump over the neighbours too,
so it cut the same moments with or without the resonance. On two songs the
mud finder picked the song's own 200 Hz, and those songs took the most.

### Next

Comparing how a moment is judged ("relative" to the band's usual level in
the song, or a band compressor that cuts only when the band gets loud) and
how the finder ranks bands (how high a band gets, or how far it swings).

## Clicks and crackle, Shimmer, Phasiness

Not started.
