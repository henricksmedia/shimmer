Refactor the artifact cleaning engine so the full mix is never aggressively processed through the STFT pipeline.

Architecture:

1. The low/mid band must bypass the STFT artifact cleaning engine completely.
2. Only the high-frequency band enters the artifact cleaning engine.
3. Convert the high band to Mid/Side:
   Mid = (Left + Right) / sqrt(2)
   Side = (Left - Right) / sqrt(2)
4. Process Side more aggressively than Mid.
5. Keep Mid gentle or bypassed depending on mode.
6. Decode Mid/Side back to Left/Right before recombining with the low/mid bypass.

Update the STFT defaults:
- n_fft = 4096
- hop_length = 1024
- 75% overlap
- Hann window or existing COLA-safe equivalent

Consolidate the old artifact stages into two macro controls:

1. Surgical De-noising
   Governs:
   - Tone Killer
   - De-checkerboard
   - Denoise

2. Dynamic Tonal Control
   Governs:
   - Shimmer
   - De-harsh
   - FlickerTamer

Remove steady_state_mode from the engine path. Full-song mastering must use transient-aware gating instead.

Implement mode/intensity mapping:

Clean:
- Mid cleaning: 10–20%
- Side cleaning: 45–60%

Loud:
- Mid cleaning: 5–10%
- Side cleaning: 35–50%

Warm:
- Mid cleaning: 10–15%
- Side cleaning: 40–55%

Vocal:
- Mid cleaning: 0–10%
- Side cleaning: 45–65%

Rescue:
- Mid cleaning: 15–25%
- Side cleaning: 65–85%

Natural:
- Mid cleaning: 0–5%
- Side cleaning: 20–35%

Add a removed-signal output:
removed_high = original_high_band - cleaned_high_band

For M/S:
removed_mid = original_mid - cleaned_mid
removed_side = original_side - cleaned_side
removed_lr = decode_ms(removed_mid, removed_side)

Return both:
- cleaned audio
- removed signal for auditioning

Do not damage center vocals, snare, kick, bass, or lead instruments.