# Tabular Computed Analysis Enforcement Fix

## Issue Description
Some analytical tabular questions still completed after a schema-only discovery call such as `describe_tabular_file`. That let the model answer from preview rows instead of using computed query, filter, aggregate, or grouped results from the full dataset.

**Version implemented:** 0.239.034

Fixed/Implemented in version: **0.239.034**

Related `config.py` update: `VERSION` was bumped to `0.239.034`.

## Root Cause Analysis
1. **Any plugin call counted as successful analysis**
   - `run_tabular_sk_analysis()` accepted the first response as long as any plugin invocation occurred.
   - Discovery calls such as `describe_tabular_file` therefore counted the same as real analytical operations.
2. **Schema discovery citations overshadowed computed analysis intent**
   - When discovery calls happened before analytical calls, citations could emphasize schema inspection rather than the computed operations that actually answered the question.
3. **Prompt guidance did not explicitly reject discovery-only behavior**
   - Even with pre-loaded schemas, the mini-agent could still call discovery helpers and stop there.

## Technical Details
### Files Modified
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_analysis_rejects_discovery_only.py`

### Code Changes Summary
- Added tabular invocation classification helpers in `route_backend_chats.py` to separate:
  - discovery functions: `list_tabular_files`, `describe_tabular_file`
  - analytical functions: `aggregate_column`, `filter_rows`, `query_tabular_data`, `group_by_aggregate`, `group_by_datetime_component`
- Updated `run_tabular_sk_analysis()` so a response is accepted only when at least one analytical tabular function ran.
- Added retry logging for discovery-only attempts so those paths are visible in diagnostics.
- Updated tabular prompt guidance to explicitly reject discovery-only tool usage.
- Filtered tabular citations so discovery-only calls are hidden when analytical tabular calls are present in the same analysis run.

### Testing Approach
- Added `functional_tests/test_tabular_analysis_rejects_discovery_only.py` to verify:
  - discovery-only calls are explicitly rejected by prompt and retry guardrails,
  - citation filtering prefers analytical calls,
  - retry evaluation can isolate new invocations from the latest attempt.

## Impact Analysis
- Analytical tabular questions are less likely to be answered from schema previews or sample rows.
- The mini-agent now has to perform a real computation before its output is trusted.
- Citations better reflect the actual analytical operations used to answer the question.

## Validation
### Before
- A single `describe_tabular_file` call could mark tabular analysis as complete.
- Users could receive answers based on preview rows with thoughts showing tabular analysis as successful.

### After
- Discovery-only tool usage triggers a retry instead of being accepted as completed analysis.
- Successful tabular analysis now requires a computed analytical call.
- When analytical calls exist, tabular citations focus on those calls instead of schema-only discovery helpers.

## Related Validation Assets
- Functional test: `functional_tests/test_tabular_analysis_rejects_discovery_only.py`
- Related fix: `docs/explanation/fixes/v0.239.033/TABULAR_DATETIME_COMPONENT_ANALYSIS_FIX.md`
- Related fix: `docs/explanation/fixes/v0.239.032/TABULAR_WORKSPACE_TRIGGER_AND_THOUGHTS_FIX.md`
