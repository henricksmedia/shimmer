# The shimmer artifact: what it is, and what could reduce it

Research for the Shimmer card, 2026-09-12. It combines what the project
measured (`HANDOFF-CHECKLIST.md` item 15, `PRESET_REVIEW.md`,
`ARCHITECTURE.md` §9, §13) with published work and listener reports. Sources
are at the end. Step 6 of the rebuild starts from this page
([REBUILD-TRACKER.md](REBUILD-TRACKER.md)).

## Short answer

Shimmer is most likely **not noise sitting on top of a clean song.** It is
more likely the song's own upper range, rebuilt coarsely by the AI's audio
decoder into a noise-like texture that moves with the music.

- Every past fix assumed the first picture: clean music with noise on top.
- So did every test model in `shimmer/artifacts.py`.
- That is the most likely reason fixes that scored well on the models did
  little on real songs.

If the second picture is right, the file has no clean top end underneath to
uncover. Turning shimmer down turns the top end down with it (dulling), which
is the trade every past attempt measured. Removing shimmer *and* keeping the
brightness would mean creating new detail. The evidence is suggestive, not
settled. The listening tests in "Questions only listening can answer" below
can settle it.

## What listeners hear

- A metallic, crystalline glaze of high, flickering narrow peaks, 5–14 kHz
  (deshimmer).
- A glassy layer over the chorus; fine noise that moves with the instruments;
  hi-hats that blur into spray (Sunofix).
- A moving synthetic texture around vocals, cymbals and pads, unlike hiss,
  which is a steady floor (Jack Righteous).
- Swishy, phasey cymbals around 8–10 kHz; shimmer on held vocal notes around
  3–5 kHz (aimusicfixer).
- A brittle top end and grainy highs, said to be worse in newer versions
  (Neural Analog).
- The author, on what the learned remover took out: "shimmer, high-pitched
  sheen and pops" (checklist 15).

They agree on four things:

- It moves with the music.
- It sits in the upper mids and highs.
- It is described in texture words: glassy, metallic, spray, swish.
- Those words point at something sparser and more "twinkly" than smooth
  noise.

## How AI music is made, briefly

Suno has not published its method. Most music generators work in two
stages:

1. A model writes compact "tokens".
2. A **neural audio codec** turns them back into sound. This is a network
   trained to squeeze audio into a few kilobits per second and rebuild it.

The squeeze rounds the audio to the nearest entries in a series of codebooks
(**residual vector quantisation**), which throws fine detail away. Codecs
work in **frames**:

| Codec | Frames per second |
|---|---|
| EnCodec | 75 at 24 kHz, 150 at 48 kHz |
| DAC | 86 |
| Stable Audio Open's autoencoder | 21.5 |

Suno's earlier speech model, Bark, used EnCodec. Fixed decoder tones were
found in Suno v2 to v3.5, which fits a decoder of this kind.

## What it is technically

| Likely cause | Where | How it behaves | Confidence | In our test models? |
|---|---|---|---|---|
| **Detail lost in the squeeze, filled in by the decoder as noise-like texture** ("hash", "fizz") | Upper mids and highs; differs by song (measured 5.6–11.3 kHz on two renders, 1–16 kHz on *leave-the-world-behind*) | Only there while notes play; irregular flicker at 2–50 Hz, moving together across the band; Side moves as much as Mid | High that codecs lose high and fine-timing detail. Medium that this is what people call shimmer | **Partly.** The flicker matches, but every model *adds* noise to an intact song; none *replaces* detail |
| **"Birdies"**: narrow peaks that switch on and off | 5–14 kHz (claimed) | Lasts tens of ms; twinkles on cymbals, partials, consonants | Well documented for MP3/AAC; for AI codecs only practitioner reports | **Missed.** All models are smooth band noise. Could explain the "crystalline" and "sheen" descriptions |
| **Flicker locked to the codec frame rate** | Broadband | A fixed rate, about 21–150 Hz | Low: follows from the design; no source shows it is audible | **Partly.** Flicker was only ever measured up to 50 Hz; 75–86 Hz was never looked at |
| **Fixed tones, combs, imaging** from upsampling layers | Fixed frequencies | Steady | High | Tones and combs: yes (the notch handles them). Imaging: missed. Not shimmer |
| **Phase smear ("swish")** | Highs | Smeared attacks, grainy reverb tails | Medium | **Missed.** Also the Phasiness card |
| **Cutoff at 12–15 kHz** | Above the cutoff | Steady | High | Not an artifact, but boosting above it lifts the hash |

## Why past attempts fell short

1. **The flicker tamer was built for the wrong movement.** It looked for
   regular 10–50 Hz pulsing, on frames too long to see it. Real hash is
   irregular. The tamer also turns the band down when the whole band moves,
   and music moves the band too. Suno Hash removed 12 %.
2. **Noise profiles come from the wrong place.** Quiet-section profiles never
   see hash, because hash only exists while music plays. Gated subtraction
   removed 52–61 %, but cost 0.19–0.47 sones against a 0.10 limit, and every
   guard that cut the cost cut the effect with it.
3. **Hand-built measures cannot tell hash from cymbals.** On *Hey*, drums
   alone push band coherence to 0.90, with no hash at all.
4. **Stem separation spreads the hash** into drums, bass and "other". The
   best result was 39 %, with heavy tone change.
5. **Mid protection fights it.** Hash sits in Mid and Side alike.
6. **The learned remover is safe but timid,** possibly because of how it was
   trained (read from the code, not yet measured):
   - It was trained on the mono mix, but runs on each channel.
   - Its loss gives almost no reward for removing quiet artifact.
   - What it did remove was pure junk (correlation to the song 0.009–0.084),
     just not much of it.
7. **Any fix that only turns parts of the sound up or down has a hard
   ceiling.** This covers masks, gates, subtraction and dynamic EQ. Where the
   song is 20 dB louder than the hash, the best possible gain takes out about
   1 %. If hash *is* the band's texture, turning it down *is* dulling the
   band.
8. **The test models are easier than the real thing.** A fix can score 81 %
   on a model and still do little on a real song.

## Candidate fixes, ranked by evidence

**Step zero: a real test case.**

- Pass clean masters through an open AI codec (DAC or EnCodec at low
  bitrate, or the Stable Audio Open autoencoder), then compare with the
  originals. This gives real codec damage with the clean version known
  exactly.
- First, a listening check: does it sound like Suno shimmer?
- Suno's codec is private, so open codecs are a stand-in.
- Effort: days. GPU runs follow the machine's limits.

| Rank | Fix | How it works | What it risks | Evidence | Effort |
|---|---|---|---|---|---|
| 1 | **Rebuild the top band** (generative post-filter) | A trained model writes a new, plausible top band instead of turning parts down (FlowDec, Apollo, AudioSR) | It invents detail: cymbals and vocal air are rewritten. Must pass "still sounds like my song" blind | Strongest published, but mostly speech and MP3; nothing on Suno output | Probe: a day. Product: weeks |
| 2 | **Retrain the existing remover on codec pairs**, in stereo, with a loss that rewards removing quiet artifact | Same small network, better teacher | Dulling as it gets bolder; the 0.10-sone limit catches it | The project's own data: it already removes only junk | Days |
| 3 | **Harmonic–percussive–residual split**, gently lowering only the residual in the upper band | Separates steady tones, hits and "everything else"; only "everything else" is touched | Cymbal wash, breath, reverb and air also land in "everything else" | The split is well established; as a shimmer fix, only marketing | Small |
| 4 | **Filter flicker at the codec frame rate**, if one exists | Find a fixed modulation rate above 50 Hz and remove it | Little, if the rate is real | None; **measure first** (envelopes up to 200 Hz) | Hours to measure |
| 5 | **Mask it**: add real detail above the cutoff, or a little real reverb | The ear hears the hash as part of a richer texture | Over-brightness; new artifacts | Unmeasured anywhere | Medium |

**Not recommended:**

- Broadband spectral de-noise, which trades hash for watery "musical noise"
  (5–7 % measured).
- Stem separation as a finder.
- A periodic flicker compressor.

**Commercial AI-music fixers** publish no removal measurements. One admits
that EQ only masks the problem. Any of them could go on the bench as a black
box, but that means uploading your tracks, which is your call.

## Questions only listening can answer

1. Does a clean master sent through DAC or EnCodec at low bitrate sound like
   Suno shimmer? If yes, step zero becomes the test case.
2. Smooth band noise against **sparse flickering peaks**, on the same master:
   which is "shimmer" and which is "hiss"?
3. On a real render, gently turn down just the shimmer band. Does the shimmer
   only go when the brightness goes? If so, the "replaced detail" picture is
   right.
4. Does a rebuilt top band sound like *the same* cymbals and voice?
5. Does added real air or reverb hide the shimmer at a brightness you accept?
6. The `quiet-*` sets and rounds 3 and 7 were built but never judged. They
   cost nothing new, so they come first.

## How sure this is

- **Solid:** codecs lose high-frequency and fine-timing detail, and fixed
  decoder tones exist (primary papers).
- **Unconfirmed:** that shimmer *is* that loss, and that it replaces detail
  rather than adding noise. This is an inference from the papers and the
  project's failure pattern.
- **Not found:** any published study that measures shimmer in AI music with
  listening tests.
- **Possibly no clean fix:** if the detail was never stored in the file,
  nothing can remove shimmer and restore the lost brightness. Under the
  "never damage the music" rule (`GOALS.md`), the card then offers the least
  damaging option within its measured limit, and says what it costs.

## Sources

- Fourier artifacts in AI music; fixed decoder peaks, Suno v2–v3.5:
  https://arxiv.org/html/2506.19108v1
- Pons et al., tonal and imaging artifacts from upsampling:
  https://arxiv.org/abs/2010.14356v2
- ArtifactNet, codec loss of high-frequency and timing detail:
  https://arxiv.org/html/2604.16254
- DAC (Improved RVQGAN), 86 Hz frames, over-smoothed highs:
  https://ar5iv.labs.arxiv.org/html/2306.06546
- EnCodec, 75 / 150 frames per second: https://ar5iv.labs.arxiv.org/html/2210.13438
- Stable Audio Open, 21.5 Hz latent rate: https://arxiv.org/html/2407.14358v2
- Afchar et al. (Deezer), the autoencoder round-trip method:
  https://arxiv.org/html/2501.10111
- FlowDec, buzzy noise from unsynchronised phases:
  https://arxiv.org/html/2503.01485
- Vocoder phasiness and its measurement: https://arxiv.org/html/2607.24323v1
- Apollo, restoring MP3-damaged music: https://arxiv.org/abs/2409.08514
- AudioSR, bandwidth extension for music: https://arxiv.org/abs/2309.07314
- Kandpal et al., metrics miss audible artifacts in music:
  https://arxiv.org/abs/2204.13289
- SonicMaster, music restoration: https://arxiv.org/abs/2508.03448
- Driedger, Müller and Disch, harmonic–percussive–residual separation:
  https://www.audiolabs-erlangen.de/resources/2014-ISMIR-ExtHPSep/2014_DriedgerMuellerDisch_ExtensionsHPSeparation_ISMIR.pdf
- Fraunhofer patent on birdies:
  https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11170794
- iZotope RX Spectral De-noise (musical noise):
  https://docs.izotope.com/rx11/en/spectral-de-noise.html
- iZotope RX Spectral Recovery:
  https://s3.amazonaws.com/izotopedownloads/docs/rx9/en/spectral-recovery/index.html
- MuQ-Eval / MusicEval: https://arxiv.org/html/2603.22677v1
- deshimmer (descriptions; no numbers): https://github.com/TheApeMachine/deshimmer
- Sunofix (descriptions; marketing): https://sunofix.app/how-to-remove-suno-artifacts/
- aimusicfixer (descriptions; marketing):
  https://aimusicfixer.com/how-to-remove-suno-ai-artifacts-without-flattening
- Jack Righteous (shimmer vs hiss):
  https://jackrighteous.com/en-us/blogs/guides-using-suno-ai-music-creation/reduce-ai-music-noise-fix-shimmer-hiss-in-suno-ai
- Neural Analog (marketing): https://neuralanalog.com/fix-suno-hiss
- Intrect (marketing; admits EQ only masks):
  https://intrect.io/blog/how-to-fix-ai-music-artifacts/
