# Sound changes since 1.1.1

Every change that alters what an export sounds like, with its numbers. This
becomes the 2.0.0 changelog (REBUILD-TRACKER Step 7). The rules behind it
are in `ARCHITECTURE.md` §19.1 item 1: a ported piece is first copied
unchanged and nulled against 1.1.1, then each fix lands on its own and is
listed here.

**Status words:**

- **Built:** the engine has it.
- **Live:** exports use it. That happens when a route moves to the new core.

## Ported unchanged (nulled against 1.1.1)

| Piece | Null | Date |
|---|---|---|
| Peak shaper and true-peak limiter | Bit-exact on both test mixes, at -1.0 and -1.5 dBTP | 2026-09-12 |
| Silence trim | Bit-exact; same cut, 1.930 s before and 2.730 s after | 2026-09-12 |
| Edge-glitch scan and in/out trim | Identical findings; trim bit-exact | 2026-09-12 |
| Fixed-tone scan, notch plan and notch repair | Identical lines and plan; repair bit-exact | 2026-09-12 |
| Bandwidth cutoff and 1/3-octave spectrum | Identical | 2026-09-12 |
| File fingerprint (SHA-1) | Identical, so Remix projects and the stem cache still match | 2026-09-12 |
| Report spectra and stereo correlation | Identical | 2026-09-12 |
| Release check | Identical verdicts and checks | 2026-09-12 |

## Report changes (numbers shown, not sound)

| Change | Before (1.1.1) | After |
|---|---|---|
| Upload analysis true peak | Read from a mono mix at 4x: -5.92 dBTP on the test render | The louder channel at 8x: -5.47 dBTP. 1.1.1 read 0.45 dB low |
| Peak-to-loudness ratio in the report | 11.98 dB on the test render, from the mono-mix true peak | 12.43 dB, from the per-channel true peak |

## Fixes

| Change | Before (1.1.1) | After | Status |
|---|---|---|---|
| Bells and shelves land on their setting | Preset shelves and bells were designed at full gain, then run forward and backward, so each landed at twice its setting: -3 dB became -6 dB | Exactly the setting: within 0.1 dB for bells, 0.2 dB for shelves (contract tests) | Built |
| Low-cut runs one way | 25 Hz zero-phase: pre-echo 32 ms ahead of a kick at -25 dB, still -53 dB beyond 20 ms; -6 dB at 25 Hz | One way: no pre-echo; -3 dB at 25 Hz | Built |
| No filter smears a hit | Any zero-phase filter | Zero-phase only where its pre-echo stays inside 20 ms; a contract test holds every filter to -60 dB beyond 20 ms | Built |
| MP3 and M4A keep every bit | Encoded from a 16-bit temp file with no dither | Encoded from 32-bit float | Built |
| Mono files stay mono | ffmpeg decode forced two channels | The file's own channel count | Built |
| A file's sample rate is never guessed | 44.1 kHz assumed when ffprobe failed | An error | Built |
| True peak is read per channel | The meter read a mono mix, so it under-read peaks whenever the channels differed | The louder channel, at 8x | Built |
| Limiter fix 1: peaks found at 8x | 4x. At 16x, the output read -0.91 (dense mix, -9 LUFS) and -0.77 to -0.78 (sparse mix) against a -1.0 ceiling | 8x, computed block by block. At 16x: -0.98 (dense) and -0.93 to -0.94 (sparse) | Built |
| Limiter fix 2: no clicks when it acts | The gain dropped within one sample at each peak: up to 0.84 dB per sample (dense mix) and 3.27-3.84 dB (sparse mix) | The gain ramps across the 2 ms lookahead: at most 0.01 dB per sample (dense) and 0.04-0.06 dB (sparse). Loudness unchanged | Built |
| Limiter fix 3: peaks stay under the ceiling | Aimed at the ceiling itself, so peaks hiding between readings passed it: -0.96 to -0.77 dBTP at 16x against -1.0 | Aims 0.17 dB under it, the most a peak can hide between 8x readings: -1.09 to -1.15 dBTP at 16x. Costs 0.01-0.04 dB of loudness | Built |
| The low-cut also removes DC | DC was removed by subtracting the whole song's average first | The 25 Hz low-cut removes it; a preview window then needs nothing from the rest of the song | Built |
| User EQ low-cut and high-cut | Run forward and backward: -6 dB at the set frequency, and pre-echo | Run one way: -3 dB at the set frequency, no pre-echo; Q still sets the resonance | Built |
| OGG export works | `save_audio` asked for 24-bit PCM inside an OGG file, which libsndfile rejects: every OGG export stopped with "Invalid combination of format, subtype and endian" | OGG Vorbis, written a block at a time. Written in one call, libsndfile's Vorbis encoder overflowed the stack on a 20 s song and killed the process | Built |
| OGG quality | libsndfile's default quality overshot by up to +2.2 dB on decoding: +0.26 dBTP, past full scale | Quality 0.8 (about 270 kbps on a dense mix), ceiling -2.0: decodes at -1.29 to -1.91 dBTP | Built |
| Lossy files never clip when played | Ceiling -1.5 dBTP for every lossy format. Decoded, M4A reached +1.24 dBTP and MP3 -0.42 | Each format's ceiling is set from measurement. Every lossy file is decoded after encoding and, if still over -1.0 dBTP, turned down by the excess and encoded again. The report says by how much | Built |
| 16-bit dither at the textbook level | TPDF of +/- 1 LSB from each of two sources, twice the usual noise: 56.5 % of samples non-zero on silence | Textbook TPDF, +/- 1 LSB in total: 25 % on silence. A -100 dBFS tone still survives at -99.9 dBFS | Built |
