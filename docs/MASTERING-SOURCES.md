# Mastering sources (Step 5)

Gathered 2026-09-12 for REBUILD-TRACKER Step 5 ("fetch the sources first").
Every claim is marked the `STYLE.md` way:

- **cited:** the page was fetched and read
- **not found:** no source could be read
- **contradicted:** the source says something else
- **inference:** our reading of what it means for Shimmer, not a source

**Caveats:**

- Most research papers are paywalled, so several claims rest on abstracts.
- Nearly every loudness figure comes from a company that sells mastering
  tools or services. That is noted where it applies.

## 1. How loud released music is

- **314,876 tracks, 2016–2026.** Median -9.5 LUFS; the middle half runs
  from -11.4 to -8.2. By genre: pop -9.5, electronic -9.3, Dance/EDM -8.7.
  [cited: Freshly Baked Studios, A. Almgren, 22 August 2026,
  https://freshlybakedstudios.com/blog/average-lufs-by-genre]
  - The figures are estimates: "projected to whole-track integrated LUFS"
    with a correction model (about 0.5 dB mean error).
  - The page says the data reads "roughly a decibel conservative", so real
    masters are a little louder.
  - The source of the tracks is not stated. The publisher sells mastering
    (vendor).
- **Billboard Global 200 top 10, first half of 2024 (54 songs).** Mean -8.3
  LUFS, SD 1 LU, range -11.1 to -6. The loudest short-term moment averaged
  -6 LUFS. Only 20 % had true peaks below 0 dBTP. [cited: iZotope, I.
  Stewart, 16 July 2024, https://www.izotope.com/en/learn/mastering-trends]
  (vendor)
- **25 most-streamed songs of 2022.** Average -8.4, range -5.8 to -13.8.
  [cited: Mastering The Mix, 18 April 2023,
  https://www.masteringthemix.com/blogs/learn/mastering-trends-for-2023]
  (vendor)
- **10 top dance/electronic songs, March 2025.** Mean -8.3. [cited:
  iZotope, 8 April 2025,
  https://www.izotope.com/en/learn/dance-electronic-analysis] (vendor)
- **An academic study of release loudness:** [not found].

**Inference:** Commercial at -9 LUFS is a sound default. It sits between the
large-catalogue median (about -8.5 once the stated 1 dB bias is allowed
for) and chart hits (-8.3 to -8.4), with a little room left for punch. Call
it a consistent industry figure, not science.

## 2. Streaming normalisation

| Service | Level | Turns quiet tracks up? | Source |
|---|---|---|---|
| Spotify | -14 LUFS ("Loud" -11, "Quiet" -19) | Yes, leaving 1 dB headroom; web player and third-party devices do not normalise | [cited: https://support.spotify.com/us/artists/article/loudness-normalization/] |
| Apple Music | -16 LUFS, industry-reported (AES TD1008), not in Apple's own pages | Uncertain; "only as much as peak levels allow" per iZotope | [cited: https://www.meterplugs.com/blog/2022/03/23/apple-switch-to-lufs.html; https://www.izotope.com/en/learn/mastering-for-streaming-platforms] |
| YouTube | -14 LUFS, found by measurement | No | [cited: https://productionadvice.co.uk/stats-for-nerds/] |
| Amazon Music | -14 LUFS | **No** (1.1.1 said yes) | [cited: https://productionadvice.co.uk/amazon-music-loudness-normalization/] |
| Tidal | -14 LUFS, album-based since 2017 | **No** (1.1.1 said yes) | [cited: https://productionadvice.co.uk/tidal-loudness/; https://productionadvice.co.uk/tidal-normalization-upgrade/] |
| Deezer | -15 LUFS | **Not supported** (1.1.1 said yes) | [cited: https://en.deezercommunity.com/features-feedback-44/how-does-the-normalise-volume-option-work-57025] |

**Inference:** at -9 LUFS every service turns a track down, so this only
changes what the release check says, not the sound.

## 3. Tone targets by genre

- **Elowsson & Friberg (AES 2017, paper 9762).** Tracks with more
  percussion have relatively more bass and treble. Genre differences are
  "mainly a side-effect of percussive prominence". [cited:
  https://aes2.org/publications/elibrary-page/?id=18638]
  - The paper itself is paywalled.
  - The 12,345-track corpus size comes from a search summary only.
  - No per-genre table with numbers was found.
- **Pestana et al. (AES 2013).** A "consistent leaning toward a target
  equalization curve". [cited: https://aes2.org/publications/elibrary-page/?id=17010]
  - Its detailed numbers were not confirmed (paywall).
- **Hove, Vuust & Stupacher (JASA 145, 2019).** Billboard Hot 100 songs,
  1955–2016: after level matching, "only the lowest frequency bands showed
  an increase". [cited: Europe PMC 31046334]
- **Openly licensed genre curves with numbers:** [not found]. iZotope's
  chart curve is proprietary.

**Inference:** do not ship per-genre curves from literature. Build one
target curve from our own captures of released songs, adjusted in the bass
and treble for how percussive the track is, as Elowsson & Friberg suggest.

## 4. Reference-track matching

- **iZotope Ozone Match EQ.** The manual advises a matched amount "under
  50%", and warns that 100 % with no smoothing can give "extreme,
  unnatural EQs". [cited:
  https://s3.amazonaws.com/izotopedownloads/docs/ozone9/en/match-eq/index.html]
  (vendor)
- **FabFilter Pro-Q EQ Match.** It averages the spectrum over time ("normally
  this doesn't take more than 30 seconds"). [cited:
  https://www.fabfilter.com/help/pro-q/using/eqmatch] (vendor)
- **Sound On Sound (E. Bazil, November 2017), independent.** Its advice:
  - Level-match first.
  - Usually keep the curve "within ±3dB, and probably less".
  - Use a reference with "similar energy and tempo", since different kick
    patterns skew the result.

  [cited: https://www.soundonsound.com/techniques/diy-mastering-made-easy]

**Inference:** Shimmer's matching should:

- default to 50 % or less
- smooth to about an octave
- level-match first
- limit the result to ±3 dB
- warn when the reference's tempo or percussion differs a lot

## 5. Low-end mono and stereo width

- **Vinyl.** Centre everything below 100 Hz, and keep everything under
  300 Hz in phase. [cited: Furnace Record Pressing,
  https://www.furnacemfg.com/vinyl-record-audio-preparation/]
- **Pushback.** A mastering engineer calls the "below 150 Hz" rule
  "patently wrong": mono bass only when the cutting engineer asks. [cited:
  Masterdisk, S. Hull, 21 July 2023,
  https://www.masterdisk.com/post/mastering-for-vinyl]
- **Playback.** Keep bass central; many PAs sum low frequencies to mono.
  [cited: Sound On Sound, M. Senior, September 2012,
  https://www.soundonsound.com/techniques/mixing-bass]
- **Correlation meters.** +1 is mono, 0 is very wide, negative means
  channels out of phase. "Any steady reading in the negative half" loses
  something in mono, while brief dips are "usually insignificant". [cited:
  Sound On Sound, H. Robjohns, October 2016,
  https://www.soundonsound.com/sound-advice/q-what-are-my-phase-correlation-meters-telling-me]
- **A standard with numbers:** [not found]. "100–150 Hz" is a working habit.

**Inference:** make this a check, not a process:

- Flag a steady negative correlation.
- Flag side-channel energy below about 100 Hz.
- Offer mono bass only as a vinyl option.

**Update 2026-11-13:** Standard mastering, now the default, makes the bass
mono below 120 Hz, as online mastering services do; the author asked for
their usual chain. Built-in and Reference track leave the stereo image as
it is.

## 6. Tone-correction tolerance (deadband)

- **Mastering The Mix.** Within ±3 dB is "a very similar tonal balance";
  beyond ±6 dB is a considerable difference (broad bands). [cited:
  https://www.masteringthemix.com/blogs/learn/compare-eq-the-ultimate-tonal-balance-tool]
  (vendor)
- **Sound On Sound (Bazil).** Keep curves within ±3 dB (topic 4). [cited]
- **A peer-reviewed per-band deadband:** [not found].

**Inference:** `REF_TOL_DB` (1.5–7.3 dB, derived from captures) sits in the
same range. Its midrange values (1.5–1.8 dB) are tighter than any published
guide, which is a reason to test the deadband by ear before shipping it.

---

Topics 7–11 were gathered 2026-11-14 for Standard mastering
([FEATURES 3.1a](FEATURES.md#31a-standard-mastering)). Shimmer must work on
music from anyone, made with any tool, and there is no human-made test audio,
so these settings rest on published work. The same marks apply.

## 7. How dynamic released music and mixes are

- **Deruty & Pachet (ISMIR 2015), 7,200 tracks, 1967–2014.** [cited:
  https://archives.ismir.net/ismir2015/paper/000136.pdf]
  - Crest factor fell until about 2008 and has been rising since.
  - 65 % of tracks released after 1994 show more than 3 dB of limiting.
  - Dynamics depend more on the year of release than on genre.
  - Loudness range (LRA) barely moved through the loudness war, and depends
    little on genre or year.
- **Deruty (Sound On Sound, September 2011).** Crest factor fell about 3 dB
  from the early 1980s; LRA did not fall after 1991. [cited:
  https://www.soundonsound.com/sound-advice/dynamic-range-loudness-war]
- **EBU Tech 3342.** Defines LRA: 3 s windows, gated, 10th to 95th
  percentile. It gives no values for music genres. [cited:
  https://tech.ebu.ch/docs/tech/tech3342.pdf]
- **Billboard Global 200 top 10, first half of 2024.** The loudest
  short-term moment sits 2–4 LU above the song's loudness; the middle half
  of LRA values runs from 3.7 to 6.8 LU. [cited:
  https://www.izotope.com/en/learn/mastering-trends] (vendor)
- **Vickers (AES 2010).** Engineers he quotes call a crest factor of about
  10 dB reasonable for pop, and about 6 dB heavily pushed. These are
  opinions, not measurements. [cited:
  https://www.sfxmachine.com/docs/loudnesswar/loudness_war.pdf]
- **Unmastered mixes.** De Man et al. (ISMIR 2014) measured crest factor on
  student mixes, but the units are not stated. [cited:
  https://archives.ismir.net/ismir2014/paper/000293.pdf] A study of the
  typical loudness range or crest factor of mixes sent to mastering:
  [not found].
- **Deruty & Tardieu (JAES 2014):** paywalled, [not found].

**Inference:**

- Expect a lot of input to arrive already limited, from people and from
  generators alike.
- Judge how dense a song already is by its crest factor or peak-to-loudness
  ratio, not by LRA. LRA hardly changes with how hard a song was limited.
- Standard's output is already in line with chart masters: on two test songs
  it measures a peak-to-loudness ratio of about 8 dB.

## 8. Compression: how much, and should it follow the song

- **Hilsamer & Herzog (DAFx 2014).** [cited:
  https://www.dafx14.fau.de/papers/dafx14_marcel_hilsamer_a_statistical_approach_to.pdf]
  - It sets a mastering compressor's threshold and ratio offline, from the
    spread of the song's levels, to reach a target spread.
  - A song already near the target gets almost no compression.
  - Matching one unmastered song to its professional master took only
    1.28:1.
- **Ma, De Man, Reiss et al. (JAES 2015), mixing, not mastering.** [cited:
  https://joshreiss.github.io/documents/2015/Ma%202015%20-%20Intelligent%20Multitrack%20Compression.pdf]
  - Engineers' ratios followed how percussive a track is and how much low
    end it has. Their thresholds followed its level.
  - LRA predicted their settings poorly.
  - The fitted ratios run from about 1:1 to 2.3:1.
- **Sound On Sound (Robjohns & White, 2002).** [cited:
  https://www.soundonsound.com/techniques/multi-band-compression-tips]
  - 3–4 bands is the usual compromise.
  - The low crossover sits near 120 Hz; the high one no lower than 2.5 kHz.
  - Its mastering example uses 1.1:1 in the mid band.
  - Release: about twice the mid band's in the low band, about half in the
    high band.
- **Waves, mastering compression tips.** [cited:
  https://waves.com/8-tips-for-compression-in-mastering] (vendor)
  - 1.25:1 to 1.5:1, rarely over 2:1, for 1–2 dB of reduction.
  - Attack 30–40 ms or slower.
  - Release a little longer than one beat, typically 300–800 ms.
  - Keep ratios alike across bands, or the tone shifts with level.
- **Linkwitz.** Linkwitz-Riley bands add back to a flat level, but the sum is
  an all-pass: the phase is not flat. [cited:
  https://linkwitzlab.com/crossovers.htm]
- **FabFilter Pro-MB.** Minimum-phase band splits shift the phase at the
  crossovers even with no gain change. Steep ones are often unpleasant for
  mastering. [cited:
  https://www.fabfilter.com/help/pro-mb/using/processingmode] (vendor)
- **Mimilakis et al. (2016); Giannoulis, Massberg & Reiss (JAES 2012):**
  paywalled, [not found].

**Inference:**

- Standard's split (120 Hz, 4 kHz) and release times (250 / 150 / 100 ms)
  follow Sound On Sound.
- Its ratios (2:1 / 1.5:1 / 2:1) are at the top of the range, and unequal.
  Equal, gentler ratios (about 1.5:1) are better supported.
- Its thresholds come from the song, so a dense song is turned down less.
  But the ratio stays the same, so it does not back off fully the way
  Hilsamer & Herzog's does. Scaling the ratio toward 1:1 when the song's
  level spread is already narrow is supported. The target spread has no
  published number yet.
- "Dry plus change" (out = song + each band times its gain change) looks
  like a way to pass untouched moments through with no phase shift. Tested
  2026-11-14, it does not work with Linkwitz-Riley bands: they are
  phase-shifted against the song, so turning the low band down 6 dB raised
  90 Hz by 2.3 dB and cut 30 Hz by only 3 dB. Summing the bands, as
  Standard does, gave the clean −6 dB shelf. A phase-true version needs
  zero-phase bands, which ring before each hit. Keep summing the bands.

## 9. The glue compressor and the limiter

- **SSL The Bus+ review (Sound On Sound).** [cited:
  https://www.soundonsound.com/reviews/ssl-the-bus-plus]
  - 1.3:1 and 1.5:1 ratios added "for mastering".
  - A detector high-pass of 0–300 Hz, 12 dB/octave.
  - Auto release.
- **Waves, SSL bus compressor guide.** [cited:
  https://www.waves.com/how-to-use-ssl-bus-compressor-classic-mix-glue]
  (vendor)
  - Mastering: 2:1, 30 ms attack, auto release, 1–2 dB of reduction.
  - Over 4–5 dB sounds over-compressed.
- **Sound On Sound (Senior, 2024).** Use the detector high-pass so the low
  end does not set off the compressor, and cut only the very lowest
  frequencies. [cited:
  https://www.soundonsound.com/sound-advice/q-why-does-my-kick-lose-weight-when-compress-drum-bus]
- **A standard detector high-pass frequency:** [not found]. "About 100 Hz"
  appears only in search snippets that were not read.
- **EBU R 128 and Tech 3343.** At most −1 dBTP. The 1 dB of headroom covers
  what a 4x true-peak meter can miss. Some older broadcast codecs need
  −2 dBTP. [cited: https://tech.ebu.ch/docs/r/r128-2014.pdf;
  https://tech.ebu.ch/docs/tech/tech3343.pdf]
- **Sound On Sound (Robjohns, 2011), limiter release.** [cited:
  https://www.soundonsound.com/sound-advice/q-what-release-settings-should-use-limiter]
  - A fast release sounds louder but can pump and distort the bass.
  - A slow one leaves holes after big hits.
  - An auto (two-speed) release lets go fast after short peaks and slowly
    after longer ones.
- **Newfangled Audio.** [cited:
  https://www.newfangledaudio.com/post/when-to-clip-vs-when-to-limit-and-why-order-matters]
  (vendor)
  - Order: EQ, clipper, limiter.
  - Clip 0.5–2 dB, and let the limiter average 1–3 dB.
- **SOS review of FabFilter Pro-L 2.** 4x oversampling catches most
  inter-sample peaks. [cited: https://www.soundonsound.com/node/4920014]

**Inference:**

- Standard's glue (2:1, 30 ms, about 1–2 dB on loud parts) matches practice.
- Two departures stand out:
  - It has no detector high-pass.
  - Its release is fixed at 300 ms, the short end of the usual range.
- The detector high-pass is well supported; its frequency is not. 100 Hz,
  12 dB/octave, is a middle choice inside SSL's range.
- The limiter matches the standards (−1 dBTP, 8x detection). Its release is
  fixed at 50 ms, and practice favours an auto release.
- On two test songs the limiter did at most 0.9 dB. A very dynamic song
  (classical, jazz, an unmastered live mix) raised to −9 LUFS would lean on
  it much harder, and that is where an auto release matters.

## 10. Saturation

- **Sound On Sound (Rogers, May 2021).** [cited:
  https://www.soundonsound.com/techniques/saturation-strategies]
  - Leave below about 100 Hz clean to keep the bass weight.
  - Use light layers.
  - Its multiband bass example does not saturate the low band.
- **Sound On Sound (Fischmann, December 2023).** Aliasing from one gentle
  saturator is usually too quiet to hear; oversample when you hear a
  problem. [cited:
  https://www.soundonsound.com/techniques/when-should-you-use-oversampling]
- **On the master, saturation should be very subtle.** [cited:
  https://violetrecording.com/how-to-use-saturation-on-the-mix-bus/]
- **How much saturation to use, in numbers:** [not found].
- **Research showing added harmonics raise loudness or warmth:** [not found].

**Inference:**

- Keep saturation off the band below 120 Hz, the low band Standard already
  splits off. The reason: it keeps the bass weight clean.
- Standard's amount (30 % mix, peaks down about 1 dB) is "subtle" by these
  sources, but no source gives a number.
- Do not count on saturation for loudness, and always compare it
  level-matched.

## 11. Stereo: width and the side channel's top end

- **Sound On Sound (Robjohns, August 2021).** Making the bass mono is the
  same as a high-pass on the side. The cost: hard-panned low parts lose a
  little level. [cited:
  https://www.soundonsound.com/sound-advice/q-how-do-you-make-only-low-frequencies-mono]
- **Mastering The Mix.** "Mono below 100 Hz" is outdated, but width below
  about 150 Hz must be phase-safe. Most usable width sits at 150 Hz–3 kHz.
  [cited: https://www.masteringthemix.com/pages/how-to-get-the-right-stereo-width]
  (vendor)
- **iZotope, mid-side mistakes.** Keep side boosts to about 1.5 dB; check
  mono when correlation goes negative. [cited:
  https://www.izotope.com/en/learn/8-common-mistakes-in-mid-side-mixing]
  (vendor)
- **Sonarworks.** Gentle side boosts of 1 dB or less at 2–7 kHz, a little
  more higher up. [cited:
  https://www.sonarworks.com/blog/learn/pro-mastering-tips-mid-side-eq]
  (vendor)
- **Afchar et al. (Deezer), ISMIR 2025 and ICASSP 2025.** [cited:
  https://arxiv.org/html/2506.19108v1; https://arxiv.org/html/2501.10111v1]
  - AI music generators leave small spectral peaks from their upsampling
    layers.
  - Both papers study them in mono, and neither mentions stereo.
- **Low-bitrate codecs.** Intensity stereo and "birdies" make an unstable
  top end. [cited: https://en.wikipedia.org/wiki/Joint_encoding;
  https://www.audiolabs-erlangen.de/content/resources/aesCodingTutorial/birdies.html]
- **Narrowing or de-essing the side's top end as a routine mastering
  step:** [not found]. Sources more often boost it gently, and cut only to
  fix a problem heard in the song.

**Inference:**

- Mono below 120 Hz is inside the usual range. Keep it.
- Standard's width rule (up to +1.5 dB, only for narrow mixes) matches the
  1.5 dB ceiling.
- Do not narrow the side's top end in Standard. It is not general practice,
  and it does not target AI artifacts, which are mono spectral peaks. A
  harsh, unstable stereo top end points to a low-bitrate MP3 or AAC source,
  which is a matter for a detector and a "What do you hear?" card, not for
  the default master.
