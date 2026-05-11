# Tabular Prompt Budget Fallback Fix

Fixed/Implemented in version: **0.240.013**

Related config.py update: `VERSION = "0.240.013"`

## Issue Description

Large tabular tool results could still overflow the outer model handoff budget even after successful tool execution, because the fallback synthesis path was serializing too many full sample rows and large cell values into the computed-results prompt.

## Root Cause Analysis

- The fallback path in `route_backend_chats.py` relied on compact summaries, but row samples and overlap summaries could still carry very large cell values.
- Prompt-fit checks were based on structural limits only, so repeated large row payloads could still produce an oversized handoff or a fallback that lacked a clear truncation signal.
- The computed-results rescue path needed deterministic compaction so successful tabular evidence stayed usable without recreating the original request-size problem.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_raw_tool_fallback.py`

### Code Changes Summary

- Added prompt-safe compaction for tabular fallback values so long cell content is truncated before overlap summaries or tool result summaries are serialized.
- Updated compact fallback payload generation to mark `result_summary_truncated` when row content was shortened for the prompt budget.
- Kept the computed-results handoff cap and prompt-budget regression coverage in place so large tabular fallbacks remain bounded.

### Testing Approach

- Functional regression: `functional_tests/test_tabular_raw_tool_fallback.py`

## Validation

### Before

- Large row payloads could dominate the fallback summary even after other prompt-budget safeguards were added.
- The fallback regression for large rows could still fail, or the fallback could fit only without an explicit truncation signal.

### After

- Overlap summaries and tool result summaries compact large cell values before prompt serialization.
- Large raw fallback summaries stay within the regression budget and explicitly indicate truncation when compaction was required.
- Successful tabular tool executions remain available as computed evidence even when the inner synthesis step fails.