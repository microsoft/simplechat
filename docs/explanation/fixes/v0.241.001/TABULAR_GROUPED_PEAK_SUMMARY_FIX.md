# Tabular Grouped Peak Summary Fix

## Issue Description
Peak-style analytical questions such as `During what hours of the day do departure queues peak?` still depended too heavily on the model interpreting raw grouped output. The plugin could group by hour, but it did not return explicit highest and lowest group summary fields, and datetime parsing relied too much on generic inference for common US-style timestamps.

**Version implemented:** 0.239.036

Fixed/Implemented in version: **0.239.036**

Related `config.py` update: `VERSION` was bumped to `0.239.036`.

## Root Cause Analysis
1. **Grouped outputs lacked explicit extremes**
   - `group_by_datetime_component` and `group_by_aggregate` returned grouped data, but not direct highest and lowest group summaries.
   - For peak-style questions, the model had to infer the answer from raw JSON instead of using clearly labeled summary fields.
2. **Common US-style datetime strings were not parsed as explicitly as they should be**
   - Real data such as the FAA sample file uses values like `5/14/2026 8:31:36 AM`.
   - The plugin relied on generic fallback parsing too early, which is weaker and noisier than handling common formats directly.
3. **The tabular prompt did not teach the model to use grouped summary fields**
   - Even when grouped results were available, the prompt did not explicitly steer peak-style questions toward the strongest summary outputs.

## Technical Details
### Files Modified
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_grouped_peak_summary.py`

### Code Changes Summary
- Improved `_parse_datetime_like_series()` to explicitly handle common date and datetime formats before generic fallback parsing.
- Added `_build_grouped_summary()` so grouped outputs can expose:
  - `highest_group`
  - `highest_value`
  - `lowest_group`
  - `lowest_value`
  - `average_group_value`
  - `median_group_value`
  - `second_highest_group`
  - `second_highest_value`
- Extended `group_by_aggregate()` to support:
  - `median`
  - `std`
  - `top_n`
  - `sort_descending`
  - grouped summary fields and ranked `top_results`
- Extended `group_by_datetime_component()` to return grouped summary fields alongside `top_results`.
- Updated the tabular SK prompt so peak-style questions explicitly use the grouped summary fields.

### Testing Approach
- Added `functional_tests/test_tabular_grouped_peak_summary.py` to verify:
  - artifact-style `M/D/YYYY h:mm:ss AM/PM` timestamps group correctly by hour,
  - grouped datetime outputs return highest and lowest summaries,
  - grouped aggregate outputs return generic peak summaries,
  - the route prompt mentions the new grouped summary guidance.

## Impact Analysis
- Peak-style questions are easier for the model to answer correctly because the plugin now returns explicit extremes.
- Common tabular files with US-style date/time strings are parsed more reliably.
- The enhancements remain generic and reusable for any grouped categorical or time-based tabular analysis.

## Validation
### Before
- The plugin could compute grouped values but forced the model to infer peaks from raw grouped JSON.
- Timestamp parsing depended more than necessary on generic datetime inference.

### After
- Grouped tools return explicit highest and lowest summary fields for peak-style interpretation.
- Artifact-style timestamps like those observed in the FAA CSV are parsed directly by known formats.
- The route prompt now encourages the model to use the summary fields when answering peak and busiest questions.

## Related Validation Assets
- Functional test: `functional_tests/test_tabular_grouped_peak_summary.py`
- Related fix: `docs/explanation/fixes/v0.239.035/TABULAR_TOOL_CALL_THOUGHTS_FIX.md`
- Related fix: `docs/explanation/fixes/v0.239.033/TABULAR_DATETIME_COMPONENT_ANALYSIS_FIX.md`
