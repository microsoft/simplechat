# TABULAR EXHAUSTIVE RESULT LIMIT ESCALATION FIX

Fixed/Implemented in version: **0.240.049**

Related config.py update: `VERSION = "0.240.049"`

## Header Information

- Issue description: Reviewer recovery could stop at a limited `search_rows` or `get_distinct_values` result even when the user explicitly asked for the full list of rows, URLs, sites, or other distinct values.
- Root cause analysis: The controller already derived follow-up calls for row context and URL extraction, but it treated the first limited slice as sufficient. That left full-list questions stuck at the original `max_rows` or `max_values` cap and, in some cases, reused the row cap as the final distinct-value cap.
- Version implemented: 0.240.049

## Technical Details

- Files modified: `application/single_app/route_backend_chats.py`, `application/single_app/config.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`
- Code changes summary: Added controller helpers that detect explicit exhaustive-result questions, parse returned row/value counts, and rerun `search_rows`, `filter_rows`, `query_tabular_data`, or `get_distinct_values` with higher limits when the current result is only a partial slice. The planner and reviewer guidance now also tell the route to escalate `max_rows` or `max_values` before answering when `total_matches > returned_rows` or `distinct_count > returned_values`.
- Testing approach: Extended the reviewer-recovery regression suite with partial-row and partial-distinct-value rerun cases, and updated the prompt-guidance/version coverage in the related tabular route tests.
- Impact analysis: Full-list workbook questions can now continue past an initial preview-sized slice and gather the complete modest cohort needed for a confident answer, instead of stopping at the first 25-result boundary.

## Validation

- Test results: Focused tabular reviewer-recovery, prompt-guidance, and all-scope source-context regressions cover the new limit-escalation path and the `0.240.049` version bump.
- Before/after comparison: Before the fix, reviewer recovery could find the right sheet and even the right pattern, but still answer from a capped subset. After the fix, the controller can detect that the current result is incomplete for a full-list question and rerun with a larger limit before the final answer is composed.
- User experience improvements: Users asking for complete site lists, URL inventories, or other exhaustive workbook results are less likely to receive answers that silently reflect only the first capped slice of tool output.