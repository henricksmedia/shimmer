Implement Side-channel width compensation after high-band M/S cleaning.

Problem:
Aggressively attenuating the Side channel can collapse the stereo image toward mono.

Requirement:
Measure short-term Side energy before and after cleaning. If the Side channel is attenuated by more than 3 dB, apply gentle smoothed makeup gain to the cleaned Side channel.

Rules:
- Apply only to the high-band Side channel.
- Do not apply global stereo widening to the full mix.
- Do not blindly restore all removed energy.
- Cap Side makeup gain.
- Smooth the gain envelope to avoid pumping.

Defaults:
- attenuation threshold: 3 dB
- max makeup default: +1.5 dB
- max makeup Rescue mode: +2.5 dB
- smoothing window: 100–250 ms
- frame_size: 4096
- hop_length: 1024

Implementation:
1. Measure RMS of original_side per frame.
2. Measure RMS of cleaned_side per frame.
3. attenuation_db = original_side_rms_db - cleaned_side_rms_db
4. makeup_db = clamp(attenuation_db - 3 dB, 0, max_makeup_db)
5. Smooth makeup_db over time.
6. Expand frame envelope to sample envelope.
7. Apply to cleaned_side.

Add tests for:
- No makeup when attenuation is below threshold
- Makeup is capped
- Makeup envelope is smooth
- Side energy is partially restored without exceeding original side energy too aggressively