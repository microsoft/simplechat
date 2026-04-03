# Tabular Named-Member Share Semi-Join Fix

Fixed in version: **0.240.018**

## Issue Description

Cross-sheet ownership-share questions could compute the total cohort count correctly with `count_rows_by_related_values` but still miss the named member's count.

Example pattern:

- One sheet defines the cohort, such as `solution_engineers`
- Another sheet contains the fact rows, such as `milestones_analysis`
- The user asks for both the cohort total and one named member's share of that total

In that flow, the model could correctly compute the total using the normalized semi-join helper, then fall back to an exact `query_tabular_data` equality check on the fact sheet for the named member. That exact-string fallback could miss valid rows when the workbook used a different casing, alias, or canonical owner form.

## Root Cause Analysis

- `count_rows_by_related_values` returned cohort-level totals and matched/unmatched source-member samples, but not a deterministic per-source count breakdown.
- The model therefore needed a second step to answer the named-member portion of the question.
- In the failing path, that second step used a fact-sheet exact text query instead of staying on the normalized source-to-target semi-join path.

## Files Modified

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_message_artifacts.py`
- `functional_tests/test_tabular_relational_analysis_helpers.py`
- `application/single_app/config.py`

## Code Changes Summary

- Added deterministic `source_value_match_counts` output to the related-value semi-join helper so each source cohort member can be paired with its matched target row count.
- Added `_matched_source_values` to returned target-row samples for clearer explainability.
- Updated analysis prompt guidance so named-member share questions prefer the semi-join helper result or a source-side filtered rerun instead of an exact fact-sheet text query.
- Extended compact artifact summaries so the new per-source breakdown is preserved in stored tabular citations.
- Added regression assertions covering the per-source breakdown and prompt guidance.

## Testing Approach

- Updated `functional_tests/test_tabular_relational_analysis_helpers.py` to verify deterministic per-source counts for a cross-sheet solution-engineer cohort.
- Re-ran existing workbook regressions to confirm the fix did not regress multi-sheet lookup behavior.

## Validation

- `functional_tests/test_tabular_relational_analysis_helpers.py` passed.
- `functional_tests/test_tabular_multisheet_workbook_support.py` passed.
- `functional_tests/test_tabular_cross_sheet_bridge_analysis.py` passed.

## Impact Analysis

- Named-member ownership-share and percentage questions now stay on the normalized semi-join path instead of depending on a fragile exact-string fallback.
- The fix is generic to cross-sheet cohort and ownership-share questions and is not specific to a single workbook.