Refactor the tone-match/corrective EQ flow.

Problem:
If tone-match EQ runs after artifact cleaning, it can boost harsh AI peaks that the cleaner just removed.

New rule:
Calculate the 1/3-octave tone curve from the raw, unprocessed input analysis only. Apply a bounded static correction before surgical artifact cleaning.

Requirements:
1. Analyze raw input before any artifact cleaning.
2. Calculate a static tone curve once.
3. Apply the curve before the high-band STFT cleaning engine.
4. Do not recalculate tone match after cleaning.
5. Do not allow post-clean automatic EQ to boost harshness back in.

Bounds:
- Max boost: +2.0 dB
- Max cut: -3.0 dB
- Smoothing: 1/3 octave
- Harsh high-frequency boost limiting from 5 kHz to 12 kHz

Acceptance criteria:
- Tone curve is based only on raw input.
- EQ cannot exceed boost/cut bounds.
- Harshness bands are boost-limited.
- No post-clean tone-match pass exists unless manually invoked in a future advanced mode.