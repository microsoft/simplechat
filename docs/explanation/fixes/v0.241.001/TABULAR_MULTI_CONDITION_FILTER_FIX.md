# TABULAR MULTI-CONDITION FILTER FIX

Fixed/Implemented in version: **0.240.037**

Related config.py update: `VERSION = "0.240.037"`

## Header Information

- Issue description: Workbook questions that depended on two literal column conditions could still miss the right analytical call, even after reviewer recovery and distinct-value handoff improvements.
- Root cause analysis: The deterministic tabular plugin exposed only one structured filter for `get_distinct_values`, `count_rows`, and `filter_rows`, which pushed the model toward broad `query_tabular_data` expressions or under-filtered counts.
- Version implemented: 0.240.037

## Technical Details

- Files modified: `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`, `application/single_app/route_backend_chats.py`, `application/single_app/config.py`, `functional_tests/test_tabular_relational_analysis_helpers.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`
- Code changes summary: Extended the shared tabular filter helper and the main analytical plugin functions to accept an optional second structured filter, wired that support through cross-sheet execution, and updated route-side planner guidance so reviewer recovery and the main prompt prefer multi-condition filtered analytical calls over broad query fallbacks.
- Testing approach: Added focused plugin-level regressions for cross-sheet distinct/count/filter calls that combine `Business Unit contains CCO` with `Location contains sharepoint`, then updated the related route/version regression checks.
- Impact analysis: Questions like “how many discrete SharePoint sites appear in CCO locations?” can now be expressed as deterministic tool arguments instead of fragile query heuristics.

## Validation

- Test results: Focused tabular regressions verify the second-filter path on distinct counts, row counts, and row retrieval, plus the updated prompt/version checks.
- Before/after comparison: Before the fix, the model often fell back to a broad query or a partially filtered count because the plugin only accepted one structured filter. After the fix, the same cohort can be represented directly with two explicit filter clauses.
- User experience improvements: Workbook questions that depend on multi-column text matching are more likely to produce exact, tool-backed answers without adding route-specific heuristics.