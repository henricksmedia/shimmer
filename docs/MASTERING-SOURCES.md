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
