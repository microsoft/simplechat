# TABULAR GENERAL COHORT DISCOVERY FIX

Fixed/Implemented in version: **0.240.043**

Related config.py update: `VERSION = "0.240.043"`

## Header Information

- Issue description: A workbook question could work on one file and fail on another with the same structure when the recovery planner guessed the wrong cohort column, such as interpreting "CCO locations" as `Location contains CCO` instead of discovering that `CCO` appears in another column.
- Root cause analysis: Reviewer recovery reused speculative filters from the first analytical call. When that call returned zero matches, the controller repeated the same assumption instead of broadening to collect row context and letting the data reveal which column actually expressed the cohort.
- Version implemented: 0.240.043

## Technical Details

- Files modified: `application/single_app/route_backend_chats.py`, `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`, `application/single_app/config.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`, `functional_tests/test_tabular_raw_tool_fallback.py`, `functional_tests/test_tabular_relational_analysis_helpers.py`
- Code changes summary: Generalized reviewer follow-up planning so zero-match same-column filters trigger a broader `search_rows` discovery step without the speculative filter. The controller can then inspect returned rows, infer a better cohort column, and run a second deterministic `get_distinct_values` extraction step. It also now iterates follow-up planning across multiple rounds instead of stopping after one automatic call.
- Additional robustness: Added plugin-side fallback handling for reviewer-style null literals such as `Location != null` and `Location == null`.
- Testing approach: Added route-helper regression coverage for broad discovery and cohort-column inference, plus plugin regression coverage for reviewer-style null literals.
- Impact analysis: Questions about distinct URLs, sites, and other embedded identifiers are less dependent on workbook-specific wording or lucky column guesses. The controller now uses returned evidence to refine the next analytical call.

## Validation

- Test results: Focused reviewer-recovery, multisheet guidance, source-context, raw fallback, and relational-helper suites validate the new broad-search and refinement behavior.
- Before/after comparison: Before the fix, the controller could repeat `Location contains CCO` and conclude there were no SharePoint sites. After the fix, it can broaden the search, inspect the matching rows, infer the actual cohort column, and then extract the canonical site list from the correct subset.
- User experience improvements: The same question shape can now work across multiple workbooks with similar schemas even when the cohort term is represented in a different column than the value being counted or listed.