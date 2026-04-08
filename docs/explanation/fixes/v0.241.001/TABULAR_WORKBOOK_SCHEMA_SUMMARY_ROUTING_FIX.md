# Tabular Workbook Schema Summary Routing Fix

## Fix Title
Workbook-structure questions now use a schema-summary tabular mode instead of being forced through analytical-only tool retries.

## Issue Description
Selected or cited Excel workbooks were always routed into the analytical mini Semantic Kernel pass. That worked well for value lookups, aggregations, and grouped analysis, but workbook-summary prompts such as asking what worksheets exist, what each worksheet represents, and how they relate were not true analytical questions.

## Root Cause Analysis
- The tabular mini-agent was intentionally hardened to allow only analytical functions during its retry path.
- Workbook-summary prompts still triggered that same analytical path, even though the correct tool for those questions is `describe_tabular_file()`.
- As a result, the model sometimes chose analytical functions like `aggregate_column()` just to satisfy the forced tool-use requirement, which then failed on multi-sheet workbooks because no `sheet_name` was supplied.
- When the mini-agent failed, the outer fallback prompt still told the final GPT pass to use plugin functions even though that stage could not actually invoke them.

## Version Implemented
Fixed in version: **0.239.115**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/route_backend_chats.py` | Added workbook-schema intent detection, schema-summary execution mode, and safer fallback prompt handling |
| `functional_tests/test_tabular_workbook_schema_summary_mode.py` | Added regression coverage for workbook-summary intent routing, fallback prompts, and citation preservation |
| `application/single_app/config.py` | Version bump to 0.239.115 |

## Code Changes Summary
- Added a narrow workbook-structure intent heuristic so prompts about worksheets, tabs, workbook summaries, and cross-sheet relationships route into a schema-summary tabular mode.
- Extended the mini tabular SK executor with a `schema_summary` mode that allows `describe_tabular_file()` and treats it as a successful tool-backed result.
- Kept the existing analytical-only path unchanged for value lookup, aggregation, filtering, and grouped-analysis questions.
- Updated the workspace fallback prompt so the final GPT pass no longer gets impossible instructions to call plugin tools after the mini SK pass has already failed.
- Preserved `describe_tabular_file()` citations when they are the only successful tabular tool calls.

## Testing Approach
- Added `functional_tests/test_tabular_workbook_schema_summary_mode.py`.
- Re-ran the focused tabular regression suite to confirm the analytical path stayed intact:
  - `functional_tests/test_tabular_analysis_rejects_discovery_only.py`
  - `functional_tests/test_tabular_tool_error_retry_and_thoughts.py`
  - `functional_tests/test_tabular_multisheet_workbook_support.py`
  - `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`

## Impact Analysis
- Workbook-summary questions should now reach the correct tabular tool path with fewer retries and lower latency.
- Analytical questions keep the stricter analytical-only guardrails that were added to prevent discovery-only answers.
- When the mini SK pass still fails, the outer fallback is now more honest about using schema-only context rather than implying that more tool calls will happen.

## Validation
- Before: workbook-summary questions could trigger repeated `aggregate_column()` failures on multi-sheet workbooks and then fall back through a contradictory prompt.
- After: workbook-summary questions route to `describe_tabular_file()`-based schema summarization, while analytical questions remain on the analytical-only path.