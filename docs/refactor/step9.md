Add removed-signal auditioning to the Shimmer UI.

Requirement:
Expose a “Listen to Removed Signal” toggle in the player.

Purpose:
This lets the user hear what the artifact engine removed. If they hear only hash, fizz, metallic noise, or unpleasant shimmer, processing is good. If they hear vocal clarity, snare snap, cymbal body, or musical musical detail, the cleaning is too aggressive.

Frontend requirements:
1. Add playback modes:
   - original
   - master
   - removed

2. Add UI control:
   Listen to Removed Signal

3. Add helper text:
   “Removed Signal lets you hear what Shimmer stripped away. If you hear vocals, snare snap, or musical detail, reduce the cleaning strength.”

4. Removed signal may be boosted for monitoring, but the UI must clearly indicate:
   “Removed Signal is boosted for monitoring.”

5. Do not export the boosted removed signal as the master.

Backend/API requirements:
- Return or expose the removed-signal preview payload alongside mastered previews.
- Keep removed signal associated with the selected master variant.
- If removed signal is unavailable, hide or disable the toggle gracefully.

Do not break normal original/master A/B playback.