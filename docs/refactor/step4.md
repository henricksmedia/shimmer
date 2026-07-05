Implement transient hold protection for the Shimmer artifact engine.

Problem:
A single-frame transient gate is not enough. If cleaning turns back on immediately after the detected transient frame, it slices off snare ring, vocal consonant decay, cymbal tail, room reflections, and musical air.

Requirement:
Create an attack/hold/release envelope that controls artifact-cleaning intensity.

Behavior:
- When transient confidence exceeds threshold, cleaning intensity drops immediately to zero or near-zero.
- Hold this reduced cleaning for 50–80 ms.
- Then ramp cleaning back in over 120–200 ms.
- Apply this envelope to the Dynamic Tonal Control macro group.
- It may also reduce Surgical De-noising slightly during transient hold if needed.

Defaults:
- threshold: 0.65
- hold_ms: 70
- release_ms: 160
- attack: instant
- hop_length: 1024
- sr: current project sample rate

Return a frame-based multiplier:
0.0 = no cleaning
1.0 = full cleaning

Apply:
effective_cleaning_amount = base_cleaning_amount * transient_hold_envelope

Add tests for:
- A detected transient creates immediate cleaning reduction
- Hold lasts at least the configured duration
- Release ramps smoothly
- No abrupt one-frame jumps occur after hold
- Envelope length matches STFT frame count