You are refactoring Shimmer, an offline AI song mastering tool, into a transparent high-fidelity AI audio mastering engine.

Do not start coding immediately.

First, inspect the repository structure and identify the files responsible for:

- Audio loading and format conversion
- Core DSP processing
- STFT artifact cleaning
- Mastering / loudness / limiting
- Preview rendering
- Export encoding
- Frontend player / visualizer UI
- Any existing tests

Create a concise implementation map showing:

1. Which files need changes
2. What each file currently does
3. Where the current architecture risks damaging phase, punch, stereo width, or loudness
4. Which functions should be replaced, preserved, or wrapped
5. Any missing dependencies needed for scipy, numpy, pyloudnorm, or oversampling/limiting

Do not invent files. Only reference files that exist in this repo.

After the audit, propose the smallest safe refactor plan that implements the Shimmer architecture:

Raw input analysis
→ bounded static tone curve
→ complementary FIR crossover split
→ low/mid bypass
→ high-band M/S cleaning
→ transient-protected artifact reduction
→ side-width compensation
→ low/high recombination
→ static LUFS gain
→ soft peak shaper
→ 4x oversampled true-peak limiter
→ codec-aware export ceiling
→ removed-signal audition