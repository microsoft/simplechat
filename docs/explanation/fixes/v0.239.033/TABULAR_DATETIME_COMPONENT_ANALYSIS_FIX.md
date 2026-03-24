# Tabular Datetime Component Analysis Fix

## Issue Description
Some tabular questions still fell back to schema-only context with the thought message `Tabular analysis could not compute results; using schema context instead`. This happened most often for time-based questions such as identifying peak hours, busiest weekdays, or monthly patterns from datetime columns.

**Version implemented:** 0.239.033

Fixed/Implemented in version: **0.239.033**

Related `config.py` update: `VERSION` was bumped to `0.239.033`.

## Root Cause Analysis
1. **The plugin lacked datetime component grouping support**
   - Existing tabular functions could aggregate and group by existing columns, but they could not directly derive `hour`, `day_of_week`, `month`, or similar components from datetime-like fields.
   - Questions like “During what hours of the day do departure queues peak?” therefore required a transformation step the plugin did not expose.
2. **The SK mini-agent could still fail even when the file triggered correctly**
   - If the model could not find a tool sequence that matched the requested transformation, the tabular analysis flow returned `None` and the chat fell back to schema-only context.
3. **There was no deterministic recovery path for common time-based questions**
   - Even when datetime columns and queue/delay metrics were clearly present, the system did not attempt a direct computed fallback.

## Technical Details
### Files Modified
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_datetime_component_analysis.py`

### Code Changes Summary
- Added datetime parsing helpers to `TabularProcessingPlugin` to support:
  - ISO datetime strings,
  - time-only strings,
  - `HHMM` and `HHMMSS` compact time formats.
- Added a new tabular plugin function: `group_by_datetime_component`
  - Supports grouping by `year`, `month`, `month_name`, `day`, `date`, `hour`, `minute`, `day_name`, `weekday_number`, `quarter`, and `week`.
  - Supports `count`, `sum`, `mean`, `min`, `max`, `median`, and `std` aggregations.
  - Supports optional pre-group filtering with a pandas query expression.
- Updated the tabular SK prompt and fallback guidance so time-based questions explicitly use `group_by_datetime_component`.
- Added a direct datetime-aware fallback in `run_tabular_sk_analysis()` so common time-based questions can still return computed results even if the SK mini-agent does not successfully plan the tool sequence.

### Testing Approach
- Added `functional_tests/test_tabular_datetime_component_analysis.py` to verify:
  - hour grouping works for ISO datetime strings,
  - compact `HHMM` values are parsed correctly,
  - route and plugin integration text references the new datetime grouping capability.

## Impact Analysis
- Time-based tabular questions now have a dedicated computation path instead of relying on schema-only reasoning.
- Questions about peak hours, busiest weekdays, and similar datetime-derived trends are much less likely to fall back to the schema preview.
- The direct fallback keeps user experience resilient even when the mini-agent does not autonomously choose the new function on the first try.

## Validation
### Before
- Tabular analysis could trigger correctly but still fail to compute answers for questions requiring datetime-derived grouping.
- Users saw the thought step `Tabular analysis could not compute results; using schema context instead` for time-based questions.

### After
- The tabular plugin can directly compute datetime component groupings.
- The chat route can recover with a deterministic datetime-based fallback for common time-oriented questions.
- Time-based questions now have a much stronger chance of returning computed results instead of schema-only context.

## Related Validation Assets
- Functional test: `functional_tests/test_tabular_datetime_component_analysis.py`
- Related fix: `docs/explanation/fixes/v0.239.032/TABULAR_WORKSPACE_TRIGGER_AND_THOUGHTS_FIX.md`
- Related thoughts documentation: `docs/explanation/features/v0.239.003/PROCESSING_THOUGHTS.md`
