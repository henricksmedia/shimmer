Fix preview rendering edge artifacts.

Problem:
A preview slice with only pre-roll still truncates the end of the DSP block. STFT, FIR, envelope followers, and limiter lookahead need audio after the preview region to avoid clicks, sputtering, or loop-edge artifacts.

Requirement:
Preview extraction must include both pre-roll and post-roll.

Defaults:
- pre_roll_sec = 1.5
- post_roll_sec = 0.5 minimum
- Also include any required safety margin for FIR delay and limiter lookahead if those values are available.

Flow:
1. Extract:
   pre-roll + requested preview slice + post-roll
2. Process the entire padded block through the DSP chain.
3. Trim both ends in the time domain after processing.
4. Encode only the requested preview duration for UI playback.

Implement:
- extract_preview_block()
- trim_processed_preview()

Acceptance criteria:
- Preview output duration equals requested duration.
- Preview does not click at start.
- Preview does not click or sputter at end.
- Preview works near beginning of file.
- Preview works near end of file.
- Preview handles files shorter than the requested slice gracefully.