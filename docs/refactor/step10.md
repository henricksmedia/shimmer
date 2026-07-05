Refactor the Shimmer UI so it feels like an AI song finishing tool, not a pro mastering console.

Main user flow:
Upload
→ Analyze
→ Choose Finish Style
→ Choose Strength
→ Create Masters
→ Compare
→ Export

Default visible controls:
- Upload Track
- Analysis summary
- Finish Style:
  Clean
  Loud
  Warm
  Vocal
  Rescue
  Natural
- Strength:
  Light
  Balanced
  Bold
- Create Shimmer Masters
- Original/Master comparison
- Level-matched A/B
- Export Master

Advanced Drawer only:
- Surgical De-noising
- Dynamic Tonal Control
- Listen to Removed Signal
- Optional loudness/ceiling display
- Optional technical stats

Do not expose these on the main screen:
- Parametric EQ
- Multiband crossover controls
- Compressor threshold/ratio/attack/release
- Raw STFT stage controls
- Manual limiter controls
- LUFS target picker by default

The UI should communicate:
“Shimmer fixes muddy, harsh, dull, quiet, or unfinished AI songs.”

Keep the interface simple and creator-friendly while preserving advanced monitoring for technical users.