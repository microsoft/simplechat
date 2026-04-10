# TABULAR REVIEWER AUTO FOLLOW-UP FIX

Fixed/Implemented in version: **0.240.042**

Related config.py update: `VERSION = "0.240.042"`

## Header Information

- Issue description: Multi-sheet workbook analysis could stop after an intermediate analytical result, such as whole-cell distinct `Location` values, even when the user asked for a search-first answer with matching rows and canonical SharePoint site counts.
- Root cause analysis: Reviewer recovery executed only the calls proposed by the LLM and then immediately handed those results to the outer model. If the first successful call returned partial evidence instead of the final reasoning inputs, the outer model still lacked the row context or extracted site list needed to answer confidently.
- Version implemented: 0.240.042

## Technical Details

- Files modified: `application/single_app/route_backend_chats.py`, `application/single_app/config.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`, `functional_tests/test_tabular_raw_tool_fallback.py`, `functional_tests/test_tabular_relational_analysis_helpers.py`
- Code changes summary: Added controller-side follow-up planning for reviewer recovery. After the first successful analytical call, the route now inspects the returned payload and can automatically schedule a second-step `search_rows` call for literal topic context plus a `get_distinct_values` extraction call for embedded URLs or sites when the question still needs canonical identifiers.
- Testing approach: Added regression coverage for derived reviewer follow-up calls and updated the related version assertions in the focused tabular recovery suites.
- Impact analysis: The route can now iterate over collected tabular evidence without introducing extra plugins. This keeps the tabular plugin surface stable while letting the controller gather search hits and extracted identifiers before the final model reasons across the results.

## Validation

- Test results: Focused reviewer-recovery and tabular fallback suites validate the new follow-up derivation path alongside the updated version checks.
- Before/after comparison: Before the fix, reviewer recovery could stop at whole-cell distinct values and the outer model would answer that the exact count was not available. After the fix, reviewer recovery can add row-context search results and canonical URL extraction results before building the computed handoff.
- User experience improvements: Questions like SharePoint site counting now have a better chance of returning concrete counts and the matching evidence rows instead of a cautious schema-only or partial-data answer.