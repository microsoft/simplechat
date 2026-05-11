# TABULAR CONTEXTUAL CELL SEARCH FIX

Fixed/Implemented in version: **0.240.039**

Related config.py update: `VERSION = "0.240.039"`

## Header Information

- Issue description: Workbook questions about embedded SharePoint links could still miss valid results when whether a URL counted depended on the surrounding text in the original cell rather than the URL text itself.
- Root cause analysis: The planner understood URL extraction, but it still treated `get_distinct_values(extract_mode='url')` as sufficient even when the relevant category signal lived in the full cell text. The raw fallback handoff also sampled only a handful of matching rows, so modest search cohorts could lose the context the outer model needed.
- Version implemented: 0.240.039

## Technical Details

- Files modified: `application/single_app/route_backend_chats.py`, `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`, `application/single_app/config.py`, `functional_tests/test_tabular_raw_tool_fallback.py`, `functional_tests/test_tabular_relational_analysis_helpers.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`
- Code changes summary: Clarified that `filter_rows` is the text-search tool for context-sensitive cell matching, updated reviewer and main analysis prompts to search/filter the original text column before classifying embedded URLs, and preserved complete small filter/query row sets in the raw fallback handoff when they fit the prompt budget.
- Testing approach: Added regression coverage for full row-context preservation in fallback summaries and updated prompt/version checks for the new contextual search guidance.
- Impact analysis: Context-dependent workbook questions can now preserve the original matching cell text instead of forcing the outer model to infer category membership from extracted URLs alone.

## Validation

- Test results: Focused tabular regressions verify prompt guidance, reviewer recovery wiring, full small-row fallback preservation, and the updated version checks.
- Before/after comparison: Before the fix, reviewer recovery could jump straight to URL extraction and the fallback handoff sampled only a few matching rows. After the fix, the planner is told to search/filter the original text column first when context matters, and modest row cohorts can survive the handoff intact.
- User experience improvements: Questions like counting SharePoint sites from mixed `Location` cells can retain the cell context needed to include URLs whose host/path text does not itself contain the qualifying keyword.