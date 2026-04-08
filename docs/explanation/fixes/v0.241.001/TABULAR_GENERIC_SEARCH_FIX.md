# TABULAR GENERIC SEARCH FIX

Fixed/Implemented in version: **0.240.040**

Related config.py update: `VERSION = "0.240.040"`

## Header Information

- Issue description: Tabular analysis could filter known columns or extract embedded values, but it still lacked a generic search capability for questions that ask where a topic, phrase, code, path, or other value appears anywhere in a worksheet or workbook.
- Root cause analysis: The plugin exposed `filter_rows` for one known column and `query_tabular_data` for hand-authored DataFrame expressions, but it did not provide a first-class search tool for unknown-column or whole-document matching with row context preserved.
- Version implemented: 0.240.040

## Technical Details

- Files modified: `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`, `application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`, `application/single_app/route_backend_chats.py`, `application/single_app/config.py`, `functional_tests/test_tabular_relational_analysis_helpers.py`, `functional_tests/test_tabular_raw_tool_fallback.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`
- Code changes summary: Added a new `search_rows` tabular analysis function that can search specified columns or all columns across a sheet or workbook, return matched-column metadata, optionally project only selected `return_columns`, and preserve small full result cohorts in fallback handoffs. Updated the planner and reviewer prompts to use `search_rows` when the relevant column is unclear.
- Testing approach: Added plugin-level regressions for cross-column generic search, fallback regressions for preserved small search cohorts, and updated route/reviewer/version checks.
- Impact analysis: Workbook questions can now start from a true search primitive instead of forcing the model to guess the relevant column or build a brittle query expression before it has enough context.

## Validation

- Test results: Focused tabular regressions verify generic search behavior, preserved small search cohorts in fallback summaries, and the updated reviewer/prompt/version wiring.
- Before/after comparison: Before the fix, whole-document search depended on guessing a column for `filter_rows` or writing a manual `query_expression`. After the fix, the model can call `search_rows` to search all columns or a chosen subset, then use the returned row context or selected columns to judge relevance.
- User experience improvements: Users can ask broader workbook questions about arbitrary topics or values without needing to know which column contains the answer signal.