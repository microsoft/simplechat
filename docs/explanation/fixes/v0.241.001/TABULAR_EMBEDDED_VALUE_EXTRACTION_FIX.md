# TABULAR EMBEDDED VALUE EXTRACTION FIX

Fixed/Implemented in version: **0.240.038**

Related config.py update: `VERSION = "0.240.038"`

## Header Information

- Issue description: Workbook questions about SharePoint sites, links, or other identifiers embedded inside composite text cells could return inflated or misleading distinct counts because the plugin counted whole-cell strings instead of extracted matches.
- Root cause analysis: `get_distinct_values` only deduplicated the full rendered cell value. When a cell contained descriptive prefixes plus a URL or other embedded identifier, the tool returned distinct cell strings instead of distinct extracted matches.
- Version implemented: 0.240.038

## Technical Details

- Files modified: `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`, `application/single_app/semantic_kernel_plugins/plugin_invocation_logger.py`, `application/single_app/route_backend_chats.py`, `application/single_app/config.py`, `functional_tests/test_tabular_relational_analysis_helpers.py`, `functional_tests/test_tabular_raw_tool_fallback.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`
- Code changes summary: Extended `get_distinct_values` with generic embedded extraction support for URLs and regex matches, added optional `url_path_segments` normalization for higher-level URL roots, updated planner guidance to prefer extraction over whole-cell distinct counts for embedded identifiers, and improved plugin invocation logs with compact structured summaries.
- Testing approach: Added focused regressions for embedded URL extraction, regex extraction, raw fallback metadata preservation, and the updated prompt/version checks.
- Impact analysis: Questions like counting SharePoint sites in filtered workbook rows can now extract and deduplicate canonical URLs instead of miscounting composite cell text.

## Validation

- Test results: Focused tabular regressions verify embedded URL extraction, regex extraction, raw fallback metadata preservation, and the updated route/version checks.
- Before/after comparison: Before the fix, a tool call such as `get_distinct_values(column='Location')` could report many distinct composite cell strings without isolating the embedded SharePoint URLs. After the fix, the same filtered cohort can extract normalized URL roots or regex matches and return deterministic distinct counts.
- User experience improvements: Embedded identifiers inside descriptive text cells are now analyzable with a reusable plugin capability rather than ad hoc heuristics.