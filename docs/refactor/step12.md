Before considering the refactor complete, add or update tests for the full Shimmer pipeline.

Required test groups:

1. DSP integrity
- Stereo shape handling
- Complementary FIR split/recombine null test
- M/S encode/decode null test
- No np.roll usage in DSP alignment
- Output length preservation

2. Artifact engine
- Low/mid band bypasses STFT cleaning
- Only high band enters M/S artifact cleaning
- Mid is processed less aggressively than Side
- Removed signal is generated
- Transient hold envelope reduces cleaning across hold/release duration

3. Stereo width
- Side attenuation is detected
- Makeup gain applies only after threshold
- Makeup gain is capped
- Envelope is smoothed

4. Mastering
- pyloudnorm integrated loudness is measured
- Static LUFS gain is applied once
- No max_iterations loop exists
- Codec-aware ceiling works
- Lossy formats use -1.5 dBTP
- WAV/FLAC use -1.0 dBTP

5. Preview
- Pre-roll and post-roll are included
- Output preview duration is exact
- Start/end edge cases do not fail

6. UI/API
- Original/master/removed playback states exist
- Removed signal toggle handles unavailable data gracefully
- Three master variants are returned
- Export uses selected variant and correct ceiling

After tests, produce a short final report:
- Files changed
- Main architecture changes
- Tests added
- Any known limitations
- What should be deferred to post-MVP