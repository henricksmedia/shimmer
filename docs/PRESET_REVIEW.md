# Preset review — are we on target?

A review of every Shimmer preset: the problem it claims to solve, what
actually causes that problem in AI-generated music (and in ordinary
mixes), the three best-known ways to address it, and a verdict on how
close the preset comes. Written 2026-09-04 as input for a fix
discussion; nothing here changes the code.

Evidence used:

- The preset rationales and settings in [presets.py](../shimmer/presets.py)
  and the stage mechanics in [engine.py](../shimmer/engine.py).
- Today's corpus measurements on 26 of Jeremy's Suno renders (the
  verified auto-detect in [detect.py](../shimmer/detect.py)): which
  presets win, how much each removes, and how far steady tones drop.
- Published research on why generative audio models leave artifacts, and
  the restoration playbooks practitioners use on Suno / Udio output.
  Sources are listed at the end.

---

## 1. What actually causes the artifacts

The presets were named by ear. The literature now explains most of what
those ears were hearing, and the causes sort into five families.

**A. Fixed-frequency tonal lines and combs (architecture artifacts).**
Transposed-convolution upsampling layers in codecs and vocoders
periodise the spectrum, cloning the low-frequency energy peak at
multiples of each layer's internal sample rate. The result is a set of
narrow spectral peaks at *fixed absolute frequencies* that depend only
on the architecture, never on the training data or the song (Encodec
produces 161 of them). These show up as horizontal lines on a
spectrogram: the "16 kHz / 17.8 kHz Suno whistle", and evenly spaced
teeth (the "checkerboard"). Today's scan found lines at 17.1, 17.7, 18.4
and 19.9 kHz on several tracks, 10–13 dB above their surroundings,
present 50–90 % of the time. Imaging (low frequencies mirrored into the
top band) is a sibling artifact from the same layers.

**B. Residual hash / fizz (codec quantisation loss).** Residual vector
quantisation discards fine high-frequency and fine temporal detail; the
decoder fills the gap with a noise-like texture that follows the music.
Practitioners describe it as flickering high-Q outliers at 5–14 kHz,
"digital fizz" at 4–7 kHz that rides consonants and cymbals, and a
"shadow" of noise that only exists while notes play. Forensic work
measures the AI residual as having roughly 7× less effective bandwidth
than real music: the top end is smeared, not detailed.

**C. Phase incoherence (decoder "swish").** Neural decoders lose
inter-frame phase coherence in the highs, giving the classic
phase-vocoder "phasiness": watery, smeared transients, grainy or
fluttering reverb tails, cymbals that blur into spray.

**D. Timbre and mix errors (model, not codec).** Unstable formants and
"plastic" vocals, brittle consonants with crackle, cymbal wash that
never stops, low-mid pile-up at 200–800 Hz from clustered instruments,
collapsed dynamics, artificial stereo widening with phase smear.

**E. Bandwidth cutoff.** Many Suno exports roll off at 12–15 kHz. A
brick-wall top end is not an artifact to remove; it is missing content.
Boosting above the cutoff lifts only hash.

Practitioner consensus on fixing these, independent of tool brand:

1. Clean first, master last, and A/B at matched loudness.
2. Prefer dynamic, per-frequency tools (dynamic EQ, dynamic resonance
   suppression, split-band de-essing) over static cuts; keep reductions
   small.
3. Spectral denoise gently, with a floor and smoothing, or you trade fizz
   for "musical noise" and a watery, blanketed sound.
4. Split to stems and treat the noisy stem (vocal, cymbals) alone.
5. Use spectral repair or de-click/de-crackle for localised crackle.
6. Restore missing bandwidth by super-resolution, not by EQ.

---

## 2. Cross-cutting findings

These apply to several presets at once and matter more than any single
preset's numbers.

1. **The engine cannot see the flicker it targets.** Every stage runs on
   4096-point frames at hop 1024 (93 ms windows, 47 frames per second).
   Modulation faster than about 23 Hz averages out inside a frame. The
   Suno hash is documented, in this very codebase, as 10–50 Hz amplitude
   modulation. Today's detector had to drop to 1024/256 frames before a
   20 Hz test flicker registered at all. FlickerTamer, the "only stage
   that can distinguish hash from cymbals", is blind to the upper half of
   the range it was built for.

2. **Centered artifacts are largely out of reach.** The Mid channel is
   cleaned at 0.2× (0.45–0.5× in three presets). Measured today: a
   centered steady tone drops 22–27 % at *any* strength, a side-only
   tone drops 80 %. Fixed tonal lines (family A) are not music and do not
   deserve the Mid protection that vocals do.

3. **Fixed artifacts are treated as if they moved.** Tonal lines and combs
   are stationary for the whole file, yet they are chased per frame with
   EMA trackers that need warm-up (500 ms for the tone killer) and
   re-detect continuously. A whole-file scan plus static, zero-phase
   notches is simpler, deeper and safer. The scan already exists in
   `detect.py`.

4. **The transient hold fights the de-esser.** DeHarsh's depth is
   multiplied by the non-transient weight. A sibilant burst raises the
   energy flux exactly like a drum hit, so the stage backs off on the
   very consonants Sibilance Rattle exists for.

5. **Band-level gains where per-bin gains are the state of the art.**
   DeHarsh applies one gain across 2–8 kHz; FlickerTamer uses six
   1.25 kHz sub-bands. Modern resonance suppressors act per bin against a
   smoothed envelope, which is what ShimmerStage already does for narrow
   peaks. Whole-band ducking is what makes a vocal "go dull".

6. **No impulsive-noise tool.** Crackle and pops on v5.5 consonants and
   cymbals are the most-cited new complaint; nothing in the chain is a
   de-click or de-crackle.

7. **No bandwidth awareness.** Nothing measures where the top end stops.
   Dark Mix Rescue's +2.5 dB shelf at 9 kHz can lift pure hash above a
   13 kHz cutoff.

8. **Stems exist but are not used for cleaning.** The Remix tab already
   separates vocals, drums, bass and other. The practitioner answer to
   "protect the vocal while cleaning the cymbals" is to clean the stems,
   which would also retire the Mid-scaling compromise.

9. **The catalog is wider than the engine.** Verified over 26 tracks,
   four presets win almost everything (Vocal Glaze + Top, Sibilance
   Rattle, Suno Hash, Deep Scrub). Nine presets rarely or never win, and
   several are the same stages with different band edges. Names promise
   distinct fixes the engine does not deliver.

---

## 3. Preset by preset

Verdict scale: **On target** (right cause, right tool), **Partly** (right
idea, wrong resolution, scope or gating), **Off target** (the tools do
not address the named problem).

| Preset | Claims to fix | Real cause (family) | Verdict |
|---|---|---|---|
| Generic | safe defaults + tone safety net | A | On target |
| Suno Hash | 5–12 kHz AM hash | B | Partly: right tool, wrong time resolution |
| Cymbal Sheen | sustained 8–12 kHz tone | A | Partly: right tool, Mid-blocked, per-frame not static |
| Laser Whistle | intermittent 9–15 kHz chirp | A (+ imaging) | Partly: "intermittent" case unaddressed |
| Brittle Air | glassy > 12 kHz | A + E | Partly: no cutoff awareness |
| Sibilance Rattle | razor "sss" bursts | D (+ crackle) | Partly: gated off by transient hold, no de-crackle |
| Cymbal Chatter | periodic "ta-ta-ta" | B/C (periodic AM) | Off target: nothing acts on the period |
| Broadband Fizz | steady top-end haze | B | On target |
| Checkerboard Grid | comb-spaced teeth | A | Partly: right idea, should be static |
| Reverb Flutter | grainy decays | C | Partly: phase is the cause, only noise-resynth touches it |
| Vocal Glaze | glassy vocal overtones | D | Partly: band-level gain, needs per-bin or stem |
| Vocal Glaze + Top | glaze + hash | D + B | Partly: inherits both parents' limits |
| Echo Sheen | content-shadow shimmer | B | Partly: expander acts in gaps, not on the shadow |
| Presence Haze | 3–8 kHz wash | B | Partly: same tools as three other presets |
| Phantom Cymbal | metallic wash 4–10 kHz | B/C/D | Partly: needs residual/transient separation |
| Harsh Veil | grit 4–12 kHz | B/D | Partly: a multiband compressor by another name |
| Deep Scrub | "make it stop" | all | As designed; over-removes (5–15 % of top-end energy) |
| Muddy / Boxy | 200–500 Hz pile-up | D | On target for a static fix; should be dynamic |
| Dark Mix Rescue | dull, no air | E | Partly: shelf above a cutoff lifts hash |

### Generic
*Fix:* nothing except a moderate tone killer 3.5–20 kHz.
*Cause:* family A lines survive every other stage.
*Best three:* (1) static notches at scanned line frequencies; (2) adaptive
long-term-excess notch (present); (3) nothing else, by design.
*Verdict:* On target. The one gap is shared with every preset: the tone
killer reaches centered lines at 20 % depth.

### Suno Hash
*Fix:* FlickerTamer (sub-band AM compressor) leads, gentle denoise /
de-harsh / de-resonator mop up, density floor 0.7.
*Cause:* B. Practitioners and the deshimmer project describe it as
high-Q, rapidly flickering outliers at 5–14 kHz.
*Best three:* (1) AM-envelope compression per sub-band at a time
resolution that sees 10–50 Hz, i.e. a 1024/256 (or finer) branch for
4–12 kHz; (2) per-bin outlier gating: residual above a smoothed
envelope that lasts fewer than a few frames is flicker, longer is
music (ShimmerStage's logic, with a short-persistence rule); (3)
dynamic resonance suppression per bin with fast attack. Stem-split
first when vocals carry the hash.
*Verdict:* Partly. The concept is exactly right; the implementation
runs at a frame rate that hides half the modulation range. The density
floor then keeps the broadband stages engaged, which is where the
dulling comes from on hashy tracks.

### Cymbal Sheen
*Fix:* tone killer 0.9 across 4–20 kHz, de-resonator, opened flatness gate.
*Cause:* A. Fixed lines; the preset docstring already names 16 kHz.
*Best three:* (1) whole-file scan, static zero-phase notches at each
line, no Mid scaling; (2) adaptive notch for lines that drift (present);
(3) spectral repair (interpolate across the line) for the deepest cases.
*Verdict:* Partly. Right tool. Three limits: the 20 dB attenuation cap
against lines measured at up to 40 dB excess, the Mid 0.2× reach, and
the per-frame tracker's warm-up. The de-resonator is admitted in the
docstring to fail on dense bands and can be dropped.

### Laser Whistle
*Fix:* same tone killer, 9–15 kHz band, small de-resonator.
*Cause:* A for constant whistles. The *intermittent, chirping* case the
name describes is more likely imaging (low-frequency content mirrored
into the top band, so it moves with the music) or a codec line whose
level tracks the program.
*Best three:* (1) static notches for constant lines (as above); (2) a
mirrored-spectrum tracker: detect energy at f_s/2 − f that correlates
with energy at f, and suppress the mirror; (3) spectral repair on
the chirp trajectories. None of the second and third exist in the
chain.
*Verdict:* Partly. Constant whistles are handled as well as Cymbal
Sheen handles them; the chirp the preset is named for is not
addressed, and the tone killer's 2 s long-term EMA is the wrong
detector for something intermittent.

### Brittle Air
*Fix:* shimmer suppression 12–18 kHz, light denoise, tone killer from
10 kHz, −1.5 dB shelf at 15 kHz.
*Cause:* A lines at 15–20 kHz plus E: many renders stop at 12–15 kHz, so
"glassy air" is often a thin band of hash between the cutoff and the
line frequencies.
*Best three:* (1) measure the cutoff, then treat only the band between
cutoff and Nyquist as noise; (2) static notches for the lines; (3)
bandwidth extension (AudioSR-class super-resolution) if air is actually
wanted back.
*Verdict:* Partly. Reasonable tools, but without cutoff detection the
preset cannot tell "brittle air" from "no air plus hash", and today's
scan shows this preset wins on none of the 26 tracks.

### Sibilance Rattle
*Fix:* DeHarsh as a wideband de-esser (5.5–10.5 kHz against 1–4 kHz),
noise resynth, mild tone killer.
*Cause:* D with a codec twist: fine temporal structure is lost, so
consonants come out brittle and often with crackle or static (the
top v5.5 complaint).
*Best three:* (1) split-band or spectral de-esser: attenuate only the
bins that exceed the envelope during the consonant, with lookahead;
(2) de-click / de-crackle on the consonant transients (impulsive-noise
model, interpolation); (3) dynamic resonance suppression at 4–8 kHz.
Set it with the instrumental playing, not solo.
*Verdict:* Partly, with a real defect: DeHarsh's depth is scaled by the
non-transient weight, and an "sss" burst trips the transient detector.
The stage is dimmed exactly when it should act. There is also no
crackle tool. It wins seven of 26 tracks today, likely because its
narrow band gives it high purity in verification rather than because
it fixes sibilance.

### Cymbal Chatter
*Fix:* shimmer suppression, denoise, de-harsh, de-checker, strong noise
resynth across 8–16 kHz.
*Cause:* B/C. A repeating "ta-ta-ta" is periodic amplitude modulation,
most plausibly at the codec's token or frame rate, or repeated smeared
micro-transients.
*Best three:* (1) modulation-domain filtering: measure the envelope
spectrum of the band, find the chatter rate, and compress that
modulation frequency; (2) transient shaping or de-click on the repeated
micro-hits; (3) spectral repair on the chatter region.
*Verdict:* Off target. The analyser measures time-periodicity, but the
preset contains no stage that acts on it; it is a generic top-end scrub
with a comb suppressor bolted on. It has not won a single track.

### Broadband Fizz
*Fix:* strong shimmer suppression and denoise 8–18 kHz, heavy noise
resynth, −2 dB shelf at 14 kHz, no notches.
*Cause:* B, the steady part.
*Best three:* (1) minimum-statistics spectral denoise with a spectral
floor and time/frequency smoothing (present); (2) content-relative
noise model for the part that follows the music; (3) gentle shelf
under the cutoff.
*Verdict:* On target for steady fizz. The known weakness is stated in
the Presence Haze docstring: minimum statistics learns the floor in
quiet frames and misses fizz that only exists while music plays.

### Checkerboard Grid
*Fix:* DeChecker (per-frame frequency-axis autocorrelation, 80–600 Hz
spacing, persistence-gated) plus the usual support stages.
*Cause:* A. The peaks are at fixed frequencies set by the layer strides
(for an Encodec-style stack the spacings are 75 Hz, 600 Hz and 3 kHz).
*Best three:* (1) whole-file long-term spectrum, fit the comb, apply
static notches; (2) per-frame comb suppression (present) for models
whose comb level varies; (3) spectral repair for the worst teeth.
*Verdict:* Partly. The detector's spacing window covers the 600 Hz
family and can miss the 75 Hz family; more importantly the pattern is
stationary and should be measured once, not re-detected per frame. Never
wins today because the comb score sits at 0.09–0.25 on every track.

### Reverb Flutter
*Fix:* maximum random-phase resynth, denoise 8–18 kHz, de-resonator,
tone killer, expander off.
*Cause:* C. Grainy, wavering tails are inter-frame phase incoherence,
the phase-vocoder "phasiness", plus lost fine temporal detail.
*Best three:* (1) phase-coherence reconstruction in decay regions
(peak-locked phase propagation, as in modern phase vocoders; deshimmer
does a version of this); (2) re-reverb: add a low level of real
algorithmic reverb so a coherent tail masks the grainy one, which is
what engineers do; (3) temporal smoothing of the magnitude envelope
only on decaying frames.
*Verdict:* Partly. Random-phase resynth trades "crystalline" for
"noisy" but cannot make a tail coherent, and the flatness gate keeps it
off tonal tails. Keeping the expander off is correct.

### Vocal Glaze
*Fix:* DeHarsh anchored to 300–1500 Hz fundamentals against 2–8 kHz
overtones, denoise 2–8 kHz, crossover dropped to 300 Hz, Mid 0.5×.
*Cause:* D. Overtones rendered too bright with unstable formants; the
"robotic shimmer at 3–5 kHz".
*Best three:* (1) per-bin dynamic resonance suppression over 2–8 kHz
keyed to vocal presence; (2) separate the vocal stem and clean it alone
(the app already has the separator); (3) split-band de-esser plus a
small static tilt.
*Verdict:* Partly. The fundamental-referenced tilt compressor is a
sound idea, but a single gain across 2–8 kHz is the mechanism behind
"dull vocals". Dropping the crossover to 300 Hz sends the vocal body
through the STFT engine, which the rest of the design deliberately
avoids.

### Vocal Glaze + Top End
*Fix:* Vocal Glaze plus Suno Hash in one pass.
*Verdict:* Partly; it inherits the frame-rate limit of FlickerTamer and
the band-level limit of DeHarsh. It is the most frequent winner today
because it removes the most energy at acceptable purity, not because it
is the most surgical.

### Echo Sheen
*Fix:* downward expander 3–10 kHz at −40 dB, fast-tracking denoise,
two iterations.
*Cause:* B. The "shadow" is the codec's coarse high-frequency
reconstruction of whatever is playing.
*Best three:* (1) a signal-relative noise model: estimate the residual
as a fraction of the band's own envelope and apply Wiener gain against
that, instead of a floor learned in silence; (2) harmonic / percussive
/ residual separation and attenuate only the residual; (3) stem-split
denoise.
*Verdict:* Partly. The docstring says the artifact is present only
while music plays, but an expander with a −40 dB threshold acts when
the band is quiet. The fast denoise tracker does the real work; the
second iteration compounds broadband loss.

### Presence Haze
*Fix:* denoise 3–8 kHz with a short minimum-statistics window, small
presence cut.
*Cause:* B, presence band.
*Best three:* same as Echo Sheen.
*Verdict:* Partly. Honest about why minimum statistics struggles, and
the short window is the right instinct, but it is one of four presets
built from the same stages with different band edges.

### Phantom Cymbal
*Fix:* de-resonator + DeHarsh led, denoise, density floor 0.5.
*Cause:* B/C/D. Generated cymbal texture: "hats blur into spray",
metallic ring inside a wash.
*Best three:* (1) harmonic / percussive / residual separation, keep the
percussive attack, attenuate the residual wash; (2) transient shaping
to restore attack against sustain; (3) per-bin resonance suppression
for the ring.
*Verdict:* Partly. The de-resonator is the stage whose docstring admits
it fails on dense bands. Nothing separates wash from hit.

### Harsh Veil
*Fix:* DeHarsh 4–12 kHz with a 3 dB threshold, denoise, mild
de-resonator, −2 dB shelf at 10 kHz.
*Cause:* B/D. Persistent grit.
*Best three:* (1) dynamic resonance suppression; (2) multiband
compression 4–12 kHz with fast attack; (3) HPSS residual attenuation.
*Verdict:* Partly. With a 3 dB threshold, DeHarsh is a one-band
multiband compressor, which is a legitimate method; per-bin control
would do the same with less dulling.

### Deep Scrub
*Fix:* every stage at high strength, two iterations, pre-analyse, Mid
0.45×, shelves.
*Verdict:* As designed, and the corpus shows the cost: it removes 5–15 %
of the top-end energy where the surgical presets remove under 2 %.
Its right role is a documented last resort. A two-preset chain
(surgical first, broad second) would reach the same result with less
collateral.

### Muddy / Boxy
*Fix:* static −3.5 dB bell at 300 Hz, +1 dB presence, 30 Hz highpass.
*Cause:* D. Instrument clustering at 200–800 Hz; on the corpus the
low-mids sit +4 to +25 dB over 500–2000 Hz.
*Best three:* (1) dynamic EQ cut at 250–400 Hz that engages only when
the band builds up; (2) static bell (present); (3) low-mid multiband
compression keyed to bass and vocal energy.
*Verdict:* On target as a static fix. A static cut thins the verses to
fix the chorus; the dynamic version is the standard answer.

### Dark Mix Rescue
*Fix:* +2.5 dB shelf at 9 kHz, presence lift, mud cut, FlickerTamer and
denoise on the lifted band.
*Cause:* E, mostly. Many renders are dark because the top end ends at
12–15 kHz.
*Best three:* (1) detect the cutoff and place any lift below it; (2)
bandwidth extension by super-resolution when real air is wanted; (3)
gentle shelf plus cleaning (present), with exciters left off until the
peaks are controlled.
*Verdict:* Partly. Cleaning the band before lifting it is the right
order, but a shelf above a brick wall lifts only the residual hash.

---

## 3b. The fingerprint result, and why it matters here

The Fourier-artifacts paper goes one step further than explaining the
peaks: it shows that the peaks alone identify the generator. A 10K-
parameter logistic regression over the long-term spectral "fingerprint"
(the average log spectrum with its smooth baseline removed) detects
real versus synthetic audio at 99.7–100 % for DAC, Encodec, Musika,
Suno v2/v3/v3.5 and Udio 130, matching a 20M-parameter transformer.
The learned weights are positive at the peak frequencies and negative
on the baseline, and each generator has its own peak placement. The
one failure (Udio 32, about 40 %) was a model version the detector had
never seen, which the authors read as an architecture change between
versions.

Three consequences for Shimmer:

1. **The line set is a property of the model version, not the song.**
   Once the peak frequencies for a Suno version are known, the fix is a
   fixed set of narrow zero-phase notches, computed once, applied to
   both channels with no Mid protection. This is roadmap item 2 with a
   published recipe: the fingerprint is the same whole-file
   average-spectrum residual that `detect.py` already computes for
   steady tones; the paper's peak-vs-baseline weighting is the
   principled way to separate generator lines from musical partials.
2. **Version detection becomes principled.** Shimmer retired its
   version-named presets (suno_v3 … suno_v5.5) in favour of artifact
   names because version guessing by ear was unreliable. The
   fingerprint gives a reliable version signal: compare a track's peak
   set against per-version templates learned from the user's own
   library, then apply that version's line set and its known
   bandwidth cutoff. Analyze could report "looks like Suno v4.5" with
   the evidence.
3. **Templates go stale; per-file peak finding does not.** The Udio 32
   result is the caution: a template from one version does not
   transfer to the next architecture. So the notch list should always
   be *derived from the file* (unsupervised peak finding, which is what
   the scan does today) and the version template used only to sharpen
   thresholds and to name the version, never as the sole source of the
   notch list.

---

## 4. What this means for the roadmap

Ranked by how much sound quality they buy per unit of work, for
discussion:

1. **A second, faster analysis branch (1024/256) for 4–12 kHz** so the
   flicker and consonant tools see the modulation they target. Touches
   FlickerTamer, DeHarsh and the detector's evidence.
2. **Static, whole-file notches for fixed lines and combs**, applied
   zero-phase to both channels, exempt from Mid scaling, derived from
   the file's own spectral fingerprint (Section 3b) and optionally
   confirmed against per-version templates. The scan in `detect.py`
   already finds them; Cymbal Sheen, Laser Whistle, Brittle Air,
   Checkerboard Grid and Generic all get better at once.
3. **Un-gate the de-esser from the transient hold** (or give sibilance
   its own detector) and add an impulsive-noise stage for crackle.
4. **Per-bin dynamic attenuation in DeHarsh** instead of one gain per
   band; this is the single change most likely to stop "dull vocals".
5. **Stem-aware cleaning**: run the chosen preset on the vocal or drum
   stem from the existing separator and recombine, retiring the Mid 0.2×
   compromise for those cases.
6. **Cutoff detection** feeding Brittle Air and Dark Mix Rescue, and a
   note in Analyze when a track ends at 13 kHz.
7. **Consolidate the catalog** into artifact families that map to real
   tools (tonal lines, hash, sibilance/crackle, wash/tails, balance),
   keeping names as entry points, so a preset's promise matches what the
   engine does. Cymbal Chatter and Reverb Flutter need new tools or
   honest retirement.

---

## Sources

Research on causes:

- Fourier explanation of AI-music artifacts (transposed-convolution
  tonal lines, architecture-determined peaks):
  <https://arxiv.org/html/2506.19108v1>
- Upsampling artifacts in neural audio synthesis (tonal, filtering,
  imaging artifacts): <https://arxiv.org/abs/2010.14356v2>
- ArtifactNet: forensic residual physics of codec-generated music
  (RVQ high-frequency and temporal loss, residual bandwidth):
  <https://arxiv.org/html/2604.16254>
- FA-GAN / Avocodo on checkerboard and periodic vocoder artifacts:
  <https://arxiv.org/html/2407.04575>, <https://arxiv.org/pdf/2206.13404>
- Phasiness in time-frequency neural vocoders:
  <https://arxiv.org/html/2607.24323v1>
- Musical noise in spectral subtraction, minimum statistics, floors and
  smoothing: <https://www.researchgate.net/publication/3333805>,
  <https://ieeexplore.ieee.org/document/5521910>

Practitioner playbooks for Suno / Udio output:

- deshimmer (birdies, stationary whines, decoder swish; phase-coherence
  reconstruction): <https://github.com/TheApeMachine/deshimmer>
- Sunofix, "How to remove Suno artifacts without dulling the mix":
  <https://sunofix.app/how-to-remove-suno-artifacts/>
- aimusicfixer, artifact types and removal techniques:
  <https://aimusicfixer.com/how-to-remove-suno-ai-artifacts-without-flattening>
- Neural Analog on v5.5 hiss, crackle and the 12–15 kHz cutoff:
  <https://neuralanalog.com/fix-suno-hiss>,
  <https://neuralanalog.com/docs/improve-suno-ai-audio-quality>
- MixMasterAI on 4–7 kHz fizz, low-mid mud and dynamic EQ:
  <https://www.mixmasterai.co/mastering/fix>
- Dynamic resonance suppression versus dynamic EQ and de-essing:
  <https://oeksound.com/manuals/soothe2/>,
  <https://ghostnotesupply.com/blogs/magazine/dynamic-resonance-suppressor-explained>
- iZotope on the order of repair operations and spectral de-ess:
  <https://www.izotope.com/en/learn/order-of-audio-repair-operations.html>
