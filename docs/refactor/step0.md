Shimmer is an AI song mastering tool focused on transparent artifact removal and safe mastering.

Never aggressively process the full mix through the STFT artifact engine.

Required architecture:
Raw input analysis
→ bounded static tone curve
→ complementary linear-phase FIR crossover
→ low/mid bypass
→ high-band M/S cleaning
→ gentle Mid processing
→ stronger Side processing
→ transient hold protection
→ Side width compensation
→ M/S decode
→ low/high recombination
→ static LUFS gain
→ soft peak shaper
→ 4x oversampled true-peak limiter
→ codec-aware ceiling
→ master export and removed-signal audition

Hard rules:
- Do not use np.roll for delay compensation.
- Do not use iterative limiter max_iterations loops.
- Do not tone-match after cleaning in a way that reintroduces harsh peaks.
- Do not expose pro mastering controls in the default MVP UI.
- Do not collapse the stereo image by over-cleaning Side without compensation.
- Do not remove transient tails with one-frame gating.
- Do not export lossy formats at the same ceiling as WAV/FLAC.

Default export ceilings:
- WAV/FLAC: -1.0 dBTP
- MP3/M4A/AAC/OGG: -1.5 dBTP

Default STFT:
- n_fft = 4096
- hop_length = 1024
- Hann window
- 75% overlap

Default crossover:
- 4500 Hz
- 1023 taps
- complementary FIR via spectral inversion