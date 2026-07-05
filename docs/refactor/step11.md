Implement Shimmer’s three generated master variants.

For each selected Finish Style and Strength, create:

1. Balanced
   - Moderate cleaning
   - Conservative loudness
   - Transparent default

2. Cleaner
   - Stronger artifact suppression
   - Slightly stronger de-harshing
   - Same or slightly lower loudness target than Balanced
   - Should not be automatically louder

3. Louder
   - Similar cleaning to Balanced
   - More loudness drive
   - More peak control
   - Should not be automatically cleaner

Requirement:
Keep the variants meaningfully distinct.

Return metadata for each:
- variant_name
- finish_style
- strength
- target_lufs
- measured_lufs
- ceiling_dbtp
- limiter_gain_reduction
- processing_summary
- preview_url or binary payload
- removed_signal_preview if available

Acceptance criteria:
- User receives three playable master options.
- Original remains unchanged.
- Each variant can be A/B compared.
- Each variant can expose removed-signal audition.
- User can export the selected variant.