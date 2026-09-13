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

**The fill, chosen again on the real songs** (same detection, 5 songs,
Amount 100 %):

| Fill | Pops 2.0 / 0.5 | Pop energy left | Crackle 2.0 / 0.5 |
|---|---|---|---|
| 48-sample model, 20 ms either side, tail margin | 49 % / 11 % | 2.44 (Alive Again 9.9) | 42 % / -34 % |
| 32-sample model, 10 ms, tail margin | 28 % / 40 % | 0.40 | 28 % / -47 % |
| **24-sample model, 96 samples, tail margin** | **46 % / 41 %** | **0.31** | **14 % / -20 %** |
| 24-sample model, 96 samples, no margin | 41 % / 38 % | 0.27 | 14 % / -19 % |

The longer models filled steady synthetic chords better but misfired on the
real songs' denser sound, so the short one is back.

**The de-click does not pass yet.** A check on "Hey" with the same pop
model planted at 15-30 % of the song's peak (clearly audible, but quieter
than the harness's "plainly there" level), three 6 s stretches with 4 pops
each, found only 0-2 of the 4 pops per channel, and the energy left was
4-15 times the pops' own: the few gaps it filled were long and filled
badly. Why it misses them: the pop model's clicks, with the ringing its
200 Hz high-pass leaves, last 6-7.5 ms, past the 3 ms the de-click accepts;
and where only a sample or two of a pop was flagged, the isolation check
compared it with the rest of the same pop and threw it out. On steady pure
chords over a heavy bass, a loud pop can come out louder after filling. The
harness's encouraging numbers came from louder pops, which are easier to
find. What passes today: a click-length gap (20 samples) in a steady tone
comes back within -63 dB, and clean music and drum hits are left alone.
The card stays off in the Master tab; its blind sets are built
(Dawn Through Smoke, Algorithm's Lure, Crosscut, Crossthread) but should
not be judged until it finds and fills pops in dense music.

**Tried and undone (2026-09-13):** judging each click's whole body instead
of its core (growing the flagged stretch while either prediction still
missed, accepting clicks up to 5 ms, and a looser core rule), with the fill
held in bounds (a steadier model, a held-back solve, and a cap at 1.5x the
loudest sample next to the gap). It found a few more pops in "Hey" (1-2 of
4) but raised false alarms on clean music, and its fills were 14-28 dB
worse than the pops they replaced: the grown gaps ran to 5 ms, and filling
that much real music from a guess replaces the music with something
unrelated. The cap cannot help, since the guess stays within normal level
and is simply wrong.

**What this shows, and the next step:** filling a gap from the sound
either side works only for gaps under about a millisecond. The pop model's
clicks, with their ringing, run longer. They need a different repair, a
redesign rather than more tuning:

- estimate the click itself (what the music's model cannot explain) and
  subtract only that, so the music under it stays; or
- repair only the band above about 2 kHz, where pops live, and leave the
  bass and mids, which a short model cannot carry through a gap, as they
  are.

The de-click as committed in 6d3f9e6 was the last measured version (above):
on the harness's louder pops it removed 46 % / 41 % at 0.017 sones on
average, left clean music and drum hits alone, and missed moderate pops in
dense music.

### The fill above 2 kHz only (2026-09-13)

The second redesign idea, tried first as a prototype outside the repo:
clicks are still found on the whole band, but inside each gap only the band
above 2 kHz is filled; the bass and mids there are kept as they were, and
every sample outside a gap is untouched.

| | Whole-band fill | Fill above 2 kHz |
|---|---|---|
| Synthetic song's 5 pops, each | -13 to +8 dB (three made worse) | +9 to +16 dB (all better) |
| "Hey", pop energy left, 6 stretches | 4-15 x the pops' own | 1.3-2.9 x |
| Drum hits and clean music | left alone | left alone |

Splitting at 1 kHz filled less well; at 4 kHz about the same as 2 kHz.
Finding clicks in the top band as well picked up drum hits (6-7 false
alarms per channel on the drum test), so finding stays on the whole band.

On the harness (5 real songs, the pop and crackle models, Amount 100 %):

| Measure | Whole-band fill | Fill above 2 kHz |
|---|---|---|
| Pop energy left | 0.31 | 0.29 |
| Crackle removed, 2.0 / 0.5 sones | 14 % / -20 % | 41 % / 57 % |
| Pops removed by the hearing model, 2.0 / 0.5 sones | 46 % / 41 % | -54 % / 14 % |
| Music taken from clean songs, mean / worst | 0.017 / 0.072 | 0.015 / 0.063 |
| False alarms per 8 s, clean songs | 3 | 3 |

The measures disagree. By plain energy the new fill removes as much of the
pops as before, and it is far better on crackle, faint crackle included,
which the old fill made worse. By the hearing model, loud pops came out
worse on three songs (Falling For You -183 %, Leave The World Behind -54 %,
We Were Meant For The Stars -91 %; Alive Again +45 %, Hey +16 %). One
likely cause: the part of each pop below 2 kHz is left in place beside a
filled top. The hearing model also blurs events as short as a click (its
frames are longer than the click), which is why the harness reports pop
energy beside it. The top-band fill is kept for its gains on energy,
crackle and the tests; which of the two measures the ear agrees with is a
listening question, and the card stays off until finding pops in dense
music is solved.

The fill test now passes. **Still failing:** in dense music it finds only
0-2 of 4 moderate pops per channel, so on "Hey" the energy left stays above
1 (the pops it misses are left as they are), and on one clean stretch of
"Hey" it flags one spot. Finding those pops is the de-click's next step.

### Finding quieter pops: a burst finder, tried and dropped (2026-09-13)

A prototype outside the repo looked for bursts in the two predictions'
combined error (over 0.5 ms) against its usual level over the surrounding
40 ms, then kept the hit and "alone" checks:

| Burst threshold | Pops found in "Hey" (of 4 per channel) | False alarms, clean 6 s stretch | Pop energy left | Test song: false alarms |
|---|---|---|---|---|
| Committed finder | 0-2 | 0-1 | 1.3-2.9 | 0 |
| 8 x usual | 3-4 | 5-14 | 27-178 | 7 per channel |
| 16 x usual | 1-4 | 3-10 | 22-192 | 7 |
| 32 x usual | 0-2 | 0-5 | 1.1-107 | 7 |

It finds more of the pops, but it flags far more of the music, and its
finds run long, so even the top-band fill leaves many times the pops'
energy. Every finder tried so far trades found pops for false alarms on
dense music.

**What would move this forward:** real clicks. No click from an AI render
has been captured in the corpus yet (`shimmer/artifacts.py`); the pop model
follows the complaint, not a recording. A few songs where the author hears
clicks, with rough times, would let the finder be built and tested on the
real thing.

## Shimmer

The research's step zero, the real-codec test case, is being built
(`scripts/make_codec_case.py`, 2026-09-13): five clean masters through
EnCodec 48 kHz at 3, 6 and 12 kbps. EnCodec is the open codec of the kind
Suno's earlier speech model used; it was installed with the author's
permission (package `encodec` 0.1.1, 3.7 MB, into the stems environment
without dependencies; its 48 kHz model, 72.8 MB, in the stems model cache).
It makes test material only and never ships.

### What the codec does (measured 2026-09-13, 20 s of each master)

| Song | Bitrate | Change against the song | Heard (added / missing, sones) | Change in the sides | Top-band flicker | Where (2k / 4k / 8k octaves) |
|---|---|---|---|---|---|---|
| Alive Again | 3 / 6 / 12 kbps | -5.1 / -6.2 / -7.2 dB | 2.15 / 1.12, 1.35 / 0.93, 1.00 / 0.73 | 37 % (song 20 %) | -0.7 to -0.8 dB | 17-23 % / 28-35 % / 15-25 % |
| Falling For You | 3 / 6 / 12 | -2.9 / -3.8 / -4.8 dB | 1.41 / 0.80, 1.21 / 0.60, 0.74 / 0.48 | 26 % (song 23 %) | -0.2 dB | 11-20 % / 37-46 % / 18-27 % |
| Leave The World Behind | 3 / 6 / 12 | -4.0 / -4.6 / -5.2 dB | 2.31 / 1.37, 1.61 / 0.97, 1.02 / 0.67 | 26-30 % (song 11 %) | -0.1 to -0.2 dB | 10-17 % / 29-32 % / 28-38 % |
| We Were Meant For The Stars | 3 / 6 / 12 | -4.3 / -5.2 / -6.2 dB | 6.00 / 2.23, 3.79 / 1.60, 2.21 / 1.14 | 17-19 % (song 14 %) | -0.3 dB | 11-19 % / 33-38 % / 25-36 % |
| Hey | 3 / 6 / 12 | -2.0 / -2.7 / -3.5 dB | 1.48 / 1.04, 1.19 / 0.93, 0.90 / 0.70 | 16-17 % (song 15 %) | -0.1 dB | 7-13 % / 41-42 % / 30-40 % |

- The codec rewrites the waveform: the change is only 2-7 dB under the
  song itself, since a codec like this keeps what the sound is like, not
  the exact wave. The hearing model says how much of that is audible.
- The change sits in 2-16 kHz, most in the 4 and 8 kHz octaves, and more
  of it is in the sides than the song's own balance.
- **The top band flickers less, not more** (0.1-0.8 dB less level swing
  over 20-50 ms). This codec replaces the top with a smoother texture; it
  does not add the flickering "hash" the earlier models are built on.
- None of the built fixes touches it (-4 % to +3 %), as expected: they aim
  at other problems.

**Next:** the author judges the five `codec-*` sets: does any bitrate sound
like Suno shimmer (listening question 1)? If one does, those pairs are the
ground truth every Shimmer fix is measured on, and the research's ranked
fixes (a model retrained on codec pairs, or rebuilding the top band) can be
tried against them. If none does, the cause is something this codec does
not do, and the next step is to measure Suno's own renders against their
stems or a clean re-record.

### The learned mask, ported (2026-09-13)

The one Shimmer fix already trained is the mask network from the evidence
branch (`scripts/hash_learn`, model 3; HANDOFF-CHECKLIST item 15). It is
now `shimmer/core/repair/hash_remover.py`, in numpy, so nothing new is
installed. It runs in render's Fixes stage as the Shimmer card's
"Spectral de-noise", on to try (below).

- **Same result as torch:** its gains are within 1.3e-6 of the network
  run in torch, on a real song's spectrogram
  (`tests/core/test_core_hash_remover.py`).
- **What changed from the training script:**
  - The level the network sees is set by the whole song, not by each
    excerpt. So a preview window gets the same gains as the export.
  - It works at 48 kHz, the rate it was trained at. Only what it removes
    is resampled back, so nothing outside 1.5–16 kHz is touched.
  - Amount is clamped, so no bin is pushed past silence.
- **Speed:**

  | Version | Time for 6 s of audio, one channel |
  |---|---|
  | Plain port | 7.2 s |
  | Kept | 0.75–1.2 s |

  The kept version:
  - does all 25 taps of two rows as one matrix multiply
  - folds the batch norm into the weights
  - skips rows no later layer reads
  - runs on 8 threads

  That is about 8 s for 30 s of stereo, or about 50 s for a 3-minute
  song. It runs once per song, from the song as it comes in, before the
  other fixes. The gains are kept (7 MB per 30 s of stereo), so a new
  Amount or a preview window takes about 0.3 s. Kept gains match gains
  worked out per window to -84 dB.
- **Weights:** `shimmer/core/repair/hash_remover.npz` (0.5 MB). They are
  in git so the fix ships with Shimmer (the author's call, 2026-09-13).
  Without the file the tool does nothing and says so.
- **Caveat:** it was trained on the flicker models (`hash`, `hash_wide`).
  The codec test above found that a real codec smooths the top rather than
  adding flicker. Removing the models' fizz may not mean removing what
  Suno does. The codec sets are the check.

### Numbers through the engine (2026-09-13)

5 real songs. The two levels are how loud the added fault is, in sones.
Each cell is the range over the songs, with the mean in brackets.

| Model | Amount 50 %, 0.5 sones | Amount 100 %, 0.5 sones | Amount 100 %, 2.0 sones |
|---|---|---|---|
| `hash`: flicker, what it was trained on | 27 to 46 % | 47 to 77 % (61 %) | 28 to 82 % (52 %) |
| `hash_wide`: broadband, measured on a Suno song | 14 to 28 % | 21 to 46 % (36 %) | -23 to +37 % (13 %) |
| `fizz`: steady, 8-18 kHz | 0 to 14 % | -1 to +19 % (6 %) | -4 to +1 % (-2 %) |
| `shadow`: follows the music | -4 to +5 % | -10 to +5 % (-2 %) | -28 to +7 % (-8 %) |

What it takes from the clean songs (missing, sones):

| Song | Amount 50 % | Amount 100 % |
|---|---|---|
| Alive Again | 0.014 | 0.033 |
| Falling For You | 0.006 | 0.011 |
| Leave The World Behind | 0.009 | 0.021 |
| We Were Meant For The Stars | 0.008 | 0.017 |
| Hey | 0.026 | 0.064 |

Side effects on the clean songs:
- Width within 0.01 dB.
- Attacks unchanged.
- Pumping at most 0.22 dB (Hey, Amount 100 %).
- What it adds with nothing to remove: up to 0.094 sones (Alive Again,
  Amount 100 %). It changes the top's texture a little even there.

Against the rule:
1. **Removes the fault on the models:** only the one it was trained on
   (`hash`). It takes part of `hash_wide`, but at 2 sones on Stars it
   makes that one 23 % more audible, and `shadow` 28 % more. It does
   nothing for `fizz` or `shadow`. So it does not pass on the models.
2. **Cost:** passes. At most 0.064 sones, so Amount's top stays at 100 %.
3. **Side effects:** none worth naming.
4. **Blind round:** the `fix-shimmer-*` sets, on the author's own mixes,
   the same kind of songs as the other cards' sets. If Suno shimmer is in
   them, this is the real test.

**On to try in the rebuild (2026-09-13).** The Master tab shows the card as
"Spectral de-noise · Shimmer", as it shows the other three before their
blind round, so the author can try it on real songs. The first time it is
turned on for a song, the network takes about 50 s for a 3-minute song.
The screen says how far it has got ("reading the whole song once, 40%"),
in the preview's status line or the export's progress window, and it can
be cancelled (`POST /api/prepare`, API.md §4). After that, a new Amount or
a preview is quick.

## Phasiness

The `phasiness` model scrambles phase in the song's tails. A fix that
restores smooth phase in tails would undo that model almost by definition,
so it would pass without proving anything. The codec test case above is
the honest check for Phasiness too: the codec rebuilds phase on its own.
