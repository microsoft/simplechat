# TABULAR REVIEWER PSEUDO QUERY REWRITE FIX

Fixed/Implemented in version: **0.240.041**

Related config.py update: `VERSION = "0.240.041"`

## Header Information

- Issue description: Reviewer recovery could regress into schema-only answers when it generated reviewer-style pseudo-pandas expressions such as `.astype(str).str.contains(...)` inside `query_expression`, because those expressions are not valid `DataFrame.query()` syntax.
- Root cause analysis: The route prompt warned the model to avoid method calls in `query_expression`, but the plugin still executed reviewer output literally. When the reviewer emitted pseudo-query syntax, analytical functions such as `get_distinct_values` failed with errors like `name 'str' is not defined`.
- Version implemented: 0.240.041

## Technical Details

- Files modified: `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`, `application/single_app/config.py`, `functional_tests/test_tabular_relational_analysis_helpers.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`, `functional_tests/test_tabular_raw_tool_fallback.py`
- Code changes summary: Added a safe fallback parser for common reviewer-style pseudo queries such as `.notnull()`, `.isnull()`, `.str.contains()`, `.str.startswith()`, `.str.endswith()`, and simple `==` or `!=` string comparisons. Analytical helpers now rewrite those limited patterns into safe filter behavior instead of failing.
- Testing approach: Added regression coverage for reviewer-style pseudo queries flowing through `count_rows` and `get_distinct_values`, then updated the related version checks.
- Impact analysis: Reviewer recovery and other analytical calls are more resilient to model-generated pseudo-pandas syntax and are less likely to fall back to schema-only answers after successful workbook discovery.

## Validation

- Test results: Focused tabular regressions verify pseudo-query rewrite behavior and the updated version checks.
- Before/after comparison: Before the fix, a reviewer plan with `Location.astype(str).str.contains(...)` failed inside `get_distinct_values`. After the fix, the same limited expression is rewritten into safe filter behavior and the analytical call can complete.
- User experience improvements: Workbook questions are less likely to regress from computed analysis back to schema-only fallback because of minor model syntax drift in `query_expression`.