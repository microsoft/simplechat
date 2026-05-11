# Multi-File Tabular Distinct URL Analysis Fix

Issue description: Workspace chat could call tabular tools against multiple selected workbooks, but the final answer still depended on LLM planning and synthesis. In multi-file distinct SharePoint/site questions, the route could underuse successful tool results from later files and answer from only one workbook.

Version implemented: 0.240.052

Fixed in version: 0.240.052

Root cause analysis: The existing tabular flow used one-file analytical tools correctly, but multi-file coverage across selected workbooks was still heuristic. The route delegated repeated per-file execution to the SK planner and reviewer recovery path, which could enrich one workbook more than another and hand the outer model separate tool summaries instead of one deterministic combined result.

Technical details

Files modified:
- application/single_app/route_backend_chats.py
- application/single_app/config.py
- functional_tests/test_tabular_multi_file_distinct_url_union.py

Code changes summary:
- Added a narrow deterministic multi-file route branch for distinct URL/site questions.
- Added schema-based sheet and column selection for URL/location-style workbook columns.
- Added route-side union and exact de-duplication of per-file distinct URL results before final prompt handoff.
- Rewired all existing workspace and chat tabular analysis call sites to go through the new multi-file-aware wrapper before falling back to the existing SK planner.

Testing approach:
- Added a functional test that validates multi-file mode detection, sheet and column selection, combined exact distinct-value union behavior, and route wiring.

Impact analysis:
- Single-file tabular behavior still falls through to the existing SK planner.
- The new deterministic path only applies to a narrow multi-file distinct URL/site question shape, which limits risk to the rest of tabular analysis.

Validation

Before:
- Multi-file distinct SharePoint/site questions could produce correct per-file tool executions but still answer from only one workbook.

After:
- Multi-file distinct SharePoint/site questions can union per-file results in the route before the final model response.

Related functional tests:
- functional_tests/test_tabular_multi_file_distinct_url_union.py