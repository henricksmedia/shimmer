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

### How a moment is judged, compared (Amount at the tested strength)

| Card | Design | Removed 2.0 / 0.5 | Music taken, mean | Worst song |
|---|---|---|---|---|
| Harshness | Fixed 4 dB over the neighbours | 17 % / 9 % | 0.060 | 0.111 |
| Harshness | Over the band's usual excess | 13-16 % / 7-17 % | 0.057-0.074 | 0.122-0.160 |
| Harshness | **Band compressor (over its 70th percentile)** | **26 % / 31 %** | **0.087** | **0.169** |
| Harshness | Compressor and sticks out (both) | 15-16 % / 13-15 % | 0.072-0.078 | 0.135-0.152 |
| Harshness | Compressor weighted by sticking out | 16-23 % / -1-22 % | 0.074-0.121 | 0.144-0.237 |
| Harshness | Every band watched, no finder | 23-34 % / 17-40 % | 0.106-0.263 | 0.154-0.432 |
| Mud | Fixed 4 dB over the neighbours | 39 % / 8 % | 0.091 | 0.184 |
| Mud | Over the band's usual excess | 14-22 % / -5-5 % | 0.079-0.123 | 0.132-0.222 |
| Mud | **Band compressor (over its 70th percentile)** | **35 % / 17 %** | **0.083** | **0.181** |
| Mud | Compressor and sticks out, or weighted | 30-38 % / 10-12 % | 0.117-0.136 | 0.220-0.228 |
| Mud | Every band watched, no finder | 25-40 % / -5-14 % | 0.228-0.512 | 0.471-0.911 |

- No design showed a side effect worth naming: width within 0.2 dB (every
  band, mud: up to -0.4), hits unchanged, pumping at most 0.35 dB.
- Ranking bands by how far they swing, not how high they get, made the mud
  finder pick 224-252 Hz instead of the planted 480 Hz.
- Watching every band removes a little more but takes far more music: the
  songs' own low mids and upper mids stick out too.
- On "We Were Meant For The Stars" both finders pick the song's own
  200 Hz and 2.2 kHz bands, so the cut costs music there and removes
  little. Whether those bands are that song's own mud and harshness is a
  listening question.

**Chosen:** the finder picks the band that sticks out highest (up to two
for Harshness, one for Low-mid build-up); a band compressor cuts it by half
of every dB it gets louder than its own 70th-percentile level in the song.
Harshness: Q 3, at most 9 dB. Low-mid build-up: Q 1.4, at most 6 dB.

Unit tests (`tests/core/test_core_dynamic_eq.py`): it finds a planted
resonance within its own bell's half-width; takes it down; leaves a quiet
stretch untouched (under -60 dB); moves nothing far outside its band
(under -40 dB); nothing more than 20 ms before a hit (-60 dB); both
channels get the same cut; a preview window equals the export (under
-60 dB); nothing found in plain noise, nothing changed.

### Amount

Measured through the engine's `render()` at the tested strength (0.5 dB of
cut per dB, 9 dB deepest for Harshness and 6 dB for Low-mid build-up), with
Amount scaling both:

| Card | Share of tested strength | Removed 2.0 / 0.5 | Music taken, mean | Worst song |
|---|---|---|---|---|
| Harshness | 50 % | 18 % / 25 % | 0.046 | 0.087 (Stars) |
| Harshness | 70 % | 23 % / 29 % | 0.063 | 0.121 (Stars) |
| Harshness | 85 % | 25 % / 31 % | 0.076 | 0.145 (Stars) |
| Harshness | 100 % | 26 % / 30 % | 0.087 | 0.169 (Stars) |
| Low-mid build-up | 50 % | 22 % / 12 % | 0.034 | 0.068 (Stars) |
| Low-mid build-up | 70 % | 28 % / 15 % | 0.051 | 0.107 (Stars) |
| Low-mid build-up | 85 % | 32 % / 16 % | 0.066 | 0.141 (Stars) |
| Low-mid build-up | 100 % | 35 % / 17 % | 0.083 | 0.181 (Stars) |

Per song at 100 %, Harshness: Alive Again 0.046, Falling For You 0.070,
Leave The World Behind 0.152, We Were Meant For The Stars 0.169, Hey 0.000
(nothing found). Low-mid build-up: 0.013, 0.067, 0.094, 0.181, 0.060. No
side effect: width within 0.02 dB, hits unchanged, pumping at most 0.32 dB.
Each card leaves the other's problem alone (3 % and -3 %).

**Decision:** the worst song reaches the 0.10 limit at about 56 % of the
tested strength for Harshness and 66 % for Low-mid build-up, so those are
the sliders' 100 %: Harshness 0.28 dB per dB and 5.1 dB deepest, Low-mid
build-up 0.33 dB per dB and 4.0 dB deepest. Most of the cost is one song
("Stars"), where both finders pick the song's own bands; the blind round
will say whether those bands are its own harshness and mud.

### Final numbers (the shipped settings)

| Card | Amount | Removed 2.0 / 0.5 | Music taken, mean | Worst song |
|---|---|---|---|---|
| Harshness | 50 % (default) | 11 % / 16 % | 0.026 | 0.049 (Stars) |
| Harshness | 100 % (top) | 20 % / 26 % | 0.052 | 0.097 (Stars) |
| Low-mid build-up | 50 % (default) | 15 % / 9 % | 0.021 | 0.041 (Stars) |
| Low-mid build-up | 100 % (top) | 27 % / 14 % | 0.048 | 0.099 (Stars) |

Per song at 100 %, Harshness: Alive Again 0.029, Falling For You 0.044,
Leave The World Behind 0.088, Stars 0.097, Hey 0.000 (nothing found).
Low-mid build-up: 0.009, 0.041, 0.054, 0.099, 0.036. Width within 0.02 dB,
hits unchanged, pumping at most 0.20 dB. 1.x: Harsh Veil 4 %; Muddy/Boxy a
static tone move only.

These are modest numbers. A resonance that rides the music's own level looks,
to any detector, much like the music's own loud notes in that band, so every
design that removed more also cut more of the clean songs. The blind round
decides whether what they do is worth having.

### Blind round

Built 2026-09-13 with `scripts/make_fix_round.py`, from the masters where
each card acts most (of 43 scanned, loudest 20 s at the top Amount):

| Card | Song | Acting | Band found |
|---|---|---|---|
| Harshness | Dawn Through Smoke | 44 % | 2245 / 3564 Hz |
| Harshness | Crooked Run | 38 % | 2245 / 3175 Hz |
| Harshness | Borrowed Ground | 38 % | 2000 / 2828 Hz |
| Harshness | Pilot Light | 33 % | 2520 Hz |
| Low-mid build-up | Crossing Wires - Temple of the Rave | 33 % | 252 Hz |
| Low-mid build-up | Stitched From Two Directions | 33 % | 200 Hz |
| Low-mid build-up | Ah | 32 % | 224 Hz |
| Low-mid build-up | Crossthread | 30 % | 283 Hz |

Harshness found nothing in 7 of the 43 songs. Each set: 20 s where the fix
acts most, as original, Amount 50 % and Amount 100 %, level-matched and
shuffled; the residual is what 100 % took out. The Harshness sets were
built at 5.2 dB deepest, a hair above the shipped 5.1 dB.

## Clicks and crackle: the de-click, rebuilt

`shimmer/core/repair/declick.py`. It runs first in the fixes, before the
notch, since a click would ring on through a notch filter.

**What 1.x's de-clicker did** (checklist item 17): 450-870 "clicks" found
per 8 s clip with about 12 planted, since it took drum hits for clicks; the
pops' energy left where it was (1.0-1.2 of it); pops 15 % / -15 % and
crackle 48 % / 37 % removed (0.5 / 2.0 sones); 0.104-0.107 sones taken from
a clean song.

**How it works:**

1. A model of the music predicts each sample from the 24 before it
   (forward) and the 24 after it (backward), refitted every 40 ms. A click
   breaks both predictions at the same samples; a hit breaks only the
   forward one. Only samples both miss by more than 6 robust sigmas (at
   Amount 100 %; 12 at 0 %) are candidates.
2. A candidate is a click only if it is short (at most 3 ms), the sound
   after it is not much louder than before (not a hit's start), and its
   error stands 3x above every error around it, within 4x its own length
   (1-10 ms), so crackle, many tiny clicks close together, still counts.
3. Each click becomes a gap a little wider than the click (a quarter of its
   length more, for its fading tail), filled by the samples that best
   continue a 48-sample model of the music fitted on 20 ms either side
   (least-squares AR interpolation).

### Checks compared (5 real songs, Amount 100 %, first fill)

| Checks | Pops 2.0 / 0.5 | Pop energy left | Crackle 2.0 / 0.5 | Music taken, mean / worst | Found on clean songs, per 8 s |
|---|---|---|---|---|---|
| None | 49 % / 60 % | 0.30 | 12 % / -104 % | 0.144 / 0.336 | 205 |
| Falls back to normal after | 22 % / 59 % | 0.50 | 8 % / -100 % | 0.041 / 0.168 | 44 |
| Stands alone within 10 ms | 37 % / 35 % | 0.42 | 15 % / -34 % | 0.013 / 0.064 | 1.6 |
| Both | 18 % / 36 % | 0.57 | 15 % / -34 % | 0.012 / 0.061 | 1.4 |

"Stands alone" cut false alarms from 205 to under 2 per 8 s; the
fall-back check threw out real pops with the hits, so it is off.

### Filling the gap

A gap in steady chords over a strong bass (the hardest case for a fill),
filled from the music either side, 30 places each:

| Gap | Typical error | Worst error |
|---|---|---|
| 20 samples | -33 dB | -21 dB |
| 40 samples | -23 dB | -5 dB |
| 60 samples | -12 dB | about 0 dB (no better than leaving it) |

That is with the best method found (a 48-sample model fitted directly on
the samples, 20 ms either side). A shorter model filled slow bass badly (it
dipped toward zero); taking the bass trend out first made it worse. So gaps
are kept short: a quarter of the click's length added for its tail, not the
whole length.

With that fill, on the real songs at Amount 100 %: pops about 49 % / 11 %
removed, crackle 42 % / -34 %, 0.017 sones taken on average and 0.070 at
worst, 3 false alarms per 8 s. A trigger of 5 sigmas instead of 6 removed a
little more (pops 47 % / 22 %, crackle 48 % / -31 %) but flagged music just
past an instant chord change, so it stays at 6.

**The weak spot:** faint crackle (0.5 sones) comes out slightly worse by the
hearing model. A fill is never exact, and on clicks that faint the fill's
own error is as large as the click. At the card's default Amount (50 %) the
trigger is 9 sigmas, so faint crackle is mostly left alone.

Unit tests (`tests/core/test_core_declick.py`): finds planted pops and
nothing else; fills them (at least 3 dB off overall, most by 5 dB, none
louder); a gap in a steady tone comes back within -40 dB; clean music and
drum hits left alone; only the found clicks change; a preview window equals
the export; the Removed track holds the pops; bypass is bit-exact.

### Numbers through the engine (settings as committed 2026-09-13)

| Amount | Pops 2.0 / 0.5 | Crackle 2.0 / 0.5 | Pop energy left | Music taken, mean | Worst song |
|---|---|---|---|---|---|
| 50 % (default) | 40 % / 21 % | 38 % / -40 % | 2.12 | 0.007 | 0.037 (Alive Again) |
| 100 % (top) | 49 % / 11 % | 42 % / -34 % | 2.44 | 0.017 | 0.070 (Alive Again) |

Width, hits and pumping unchanged. No Amount cap needed: the worst song
takes 0.070 at the top.

**Open problem, being fixed:** the pop energy left is over 1. By the
hearing model about half of each planted pop is gone, but by plain energy
the fills leave more error behind than the pops had. With the first,
shorter fill it was 0.30-0.42. The longer fill was tuned on steady chords
over a bass, and on the real songs' denser sound it misfires. The fill is
being chosen again on the real songs; the card stays off in the Master tab
until that is settled and the blind round passes.

## Shimmer

The research's step zero, the real-codec test case, is being built
(`scripts/make_codec_case.py`, 2026-09-13): five clean masters through
EnCodec 48 kHz at 3, 6 and 12 kbps. EnCodec is the open codec of the kind
Suno's earlier speech model used; it was installed with the author's
permission (package `encodec` 0.1.1, 3.7 MB, into the stems environment
without dependencies; its 48 kHz model, 72.8 MB, in the stems model cache).
It makes test material only and never ships.

Next: the author judges whether the codec's damage sounds like Suno shimmer
(listening question 1). If it does, the codec pairs are the ground truth
every Shimmer fix is measured on.

## Phasiness

The `phasiness` model scrambles phase in the song's tails. A fix that
restores smooth phase in tails would undo that model almost by definition,
so it would pass without proving anything. The codec test case above is
the honest check for Phasiness too: the codec rebuilds phase on its own.
