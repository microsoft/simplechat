# TABULAR ANALYSIS HEARTBEAT FIX

Fixed in version: **0.241.136**

## Overview

Long-running tabular requests could appear complete too early in the chat progress card even though backend analysis was still active. Users saw a `100%` tabular card and "Workbook evidence ready" while the Semantic Kernel tabular loop continued retrying or preparing the final response.

## Root Cause

- The tabular progress card treated "no currently running activities" as completion.
- The tabular retry loop logged retry reasons to the backend but did not emit a user-visible lifecycle heartbeat between attempts.
- As a result, completed tool calls could temporarily leave the UI with no running activity, causing a false completed state.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-thoughts.js`
- `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`
- `ui_tests/test_chat_tabular_thought_progress.py`

### Code Changes Summary

- Added a stable tabular lifecycle activity payload for long-running analysis and retry heartbeats.
- Emitted lifecycle thoughts when tabular analysis starts, retries, and hands off to final response synthesis.
- Threaded the lifecycle callback through `run_tabular_analysis_with_multi_file_support(...)` and `run_tabular_sk_analysis(...)`.
- Changed the chat progress renderer so tool-only tabular activity no longer auto-completes just because no tool is currently running.
- Kept export-specific wording reserved for actual tabular post-processing/export phases.

## Testing

- Functional regression updated in `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`
- UI regression updated in `ui_tests/test_chat_tabular_thought_progress.py`
- Python syntax validation via `py_compile`
- JavaScript syntax validation via `node --check`

## Validation

### Result

- Tool-only tabular analysis now stays visibly active after workbook tool calls finish and before the final response arrives.
- Retry passes now surface a visible heartbeat such as "Retrying workbook analysis (attempt X of 3)".
- The progress card no longer shows export wording for normal tabular retry/lifecycle activity.

### User Impact

- Users can distinguish between true completion and ongoing backend analysis.
- Long-running workbook analysis now remains visibly active instead of looking hung or falsely complete.
- Final completion is tied to real terminal phases such as export completion or final model response.