# Tabular Year Trend And Summary Guardrails Fix

Fixed in version: **0.239.038**

## Issue Description

Broad tabular questions against workbook data could still produce weak behavior in two places:

1. Year-based trend intent was under-inferred in the direct datetime fallback logic, even though the plugin already supports `year` grouping.
2. Broad summaries could still mention speculative parser or follow-up analysis failures that were not the main requested outcome.

This showed up with the Superstore workbook where yearly profit analysis should be computable from `Order Date`, but the response still mentioned a parameter parsing issue.

## Root Cause Analysis

- The route-level `infer_datetime_component()` helper recognized hour, weekday, month, quarter, week, and date intent, but not year, yearly, or annual intent.
- The plugin-level `_try_numeric_conversion()` step converted already-parsed Excel datetime columns into numeric values before the datetime grouping logic ran, which broke valid workbook date columns like `Order Date`.
- The mini-agent system prompt strongly required computed analysis, but it did not explicitly forbid narrating hypothetical or secondary failures when the user asked for a broad business summary.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_datetime_component_analysis.py`

### Code Changes Summary

- Added `year`, `years`, `yearly`, `annual`, and `annually` keyword inference to the route datetime-component helper.
- Preserved datetime and timedelta columns during the plugin numeric-conversion pass so Excel date columns remain usable for datetime grouping.
- Expanded the tabular tool prompt text to frame `group_by_datetime_component` as the trend-analysis tool for year, quarter, month, week, day, and hour groupings.
- Added a stronger prompt guardrail telling the tabular mini-agent not to mention hypothetical follow-up analyses, parser errors, or failed attempts unless the user explicitly asks about failures and real tool error output exists.
- Extended the existing datetime regression test to cover yearly grouping behavior and the new prompt guidance.

### Testing Approach

- Reused the existing datetime component functional test file.
- Added an in-memory yearly grouping scenario modeled on workbook-style date columns like `Order Date`.
- Verified route prompt text contains the new yearly trend guidance and speculative-failure guardrail.

## Impact Analysis

- Improves reliability for yearly or annual time-series questions on CSV and Excel files.
- Reduces the chance of broad tabular summaries surfacing distracting parser-error commentary when the user did not ask for failure details.
- Keeps the tabular tool behavior generic rather than special-casing the Superstore workbook.

## Validation

### Test Results

- `functional_tests/test_tabular_datetime_component_analysis.py`

### Before

- Year intent was not part of the direct datetime inference keywords.
- Excel datetime columns could be converted away from datetime dtype before grouping.
- The prompt left more room for broad summaries to mention hypothetical or secondary parsing failures.

### After

- Yearly and annual phrasing now map to `year` grouping intent.
- Excel datetime columns remain intact for yearly and other datetime-component grouping.
- The prompt explicitly steers the model toward computed findings only, without narrating unrelated failed attempts.