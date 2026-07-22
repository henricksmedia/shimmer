Refactor the mastering chain.

Goal:
Make Shimmer loudness-safe, true-peak-safe, and transparent. Remove iterative limiting.

Requirements:

1. Remove all max_iterations limiter loops or repeated gain-reduction passes.

2. Use pyloudnorm to measure integrated loudness after artifact cleaning and recombination.

3. Calculate a single static gain offset:
   gain_db = target_lufs - current_lufs
   gain_linear = 10 ** (gain_db / 20)

4. Apply this static gain once.

5. Add dual-stage peak control:
   - Stage 1: gentle soft peak shaper catching approximately the top 1–2 dB
   - Stage 2: 4x oversampled lookahead true-peak limiter

6. Limiter must be single-pass, lookahead, and oversampled.

7. Ceiling:
   - WAV/FLAC: -1.0 dBTP
   - MP3/M4A/AAC/OGG: -1.5 dBTP

8. Add a function:
   get_export_ceiling_dbtp(export_format)

9. Default loudness targets:
   - Natural: -16 LUFS
   - Clean: -14 LUFS
   - Warm: -14 LUFS
   - Vocal: -14 LUFS
   - Rescue: -13 LUFS
   - Loud: -11 LUFS

10. Avoid default -9 LUFS. If a future UI offers ultra-loud targets, it must warn users about distortion risk.

Acceptance criteria:
- No iterative limiter loop remains.
- Static LUFS gain is applied once.
- Limiter runs once.
- True peak ceiling is enforced.
- Lossy exports receive extra ceiling headroom.
- Mastering chain returns useful stats:
  current_lufs
  target_lufs
  gain_db
  ceiling_dbtp
  estimated_true_peak
  limiter_gain_reduction