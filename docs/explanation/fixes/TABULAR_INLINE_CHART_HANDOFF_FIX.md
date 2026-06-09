# Tabular Inline Chart Handoff Fix

Fixed in version: **0.241.166**

## Issue Description

Users could ask tabular analysis questions that computed grouped totals successfully, but the final answer could return unsupported chart syntax such as Mermaid instead of a SimpleChat inline chart. For example, a request for category totals from a workbook followed by a pie chart could produce a Markdown table plus a plain `pie showData` code block that the chat UI does not render.

## Root Cause Analysis

SimpleChat inline charts render only `simplechart` fenced blocks produced by the conversation chart capability. The tabular analysis mini-kernel in `route_backend_chats.py` computes workbook aggregations through tabular tools, but grouped tabular tool results were handed to the final model as text without a deterministic chart handoff. When the model chose Mermaid syntax, the frontend correctly treated it as ordinary code because Mermaid is not part of the inline chart renderer.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_chart_operations.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_inline_chart_handoff.py`

### Code Changes Summary

- Added deterministic conversion from successful grouped tabular invocations into conversation chart citations.
- Supported chart handoff for both workspace-search tabular analysis and chat-uploaded tabular files.
- Wired the handoff into both streaming and non-streaming chat response paths.
- Strengthened reusable chart guidance to prefer SimpleChat `simplechart` blocks and avoid Mermaid, matplotlib, Vega, or other unsupported chart code when the user wants an inline chart.
- Updated the app version from `0.241.165` to `0.241.166`.

### Testing Approach

- Added `functional_tests/test_tabular_inline_chart_handoff.py` to validate that grouped category totals create a `simplechart` pie citation rather than Mermaid output.
- The test also checks that all four tabular success paths call the chart handoff helper.

## Validation

### Expected Behavior

When a tabular analysis request asks for a chart and grouped tabular results are available, SimpleChat now appends a chart citation containing `chart_markdown` with a `simplechart` fenced block. Existing backend append logic then includes that chart block in the assistant response and streaming delta.

### User Experience Improvements

- Chart requests over CSV/XLSX analysis now render through the SimpleChat inline chart renderer.
- The model can still explain the computed totals, but the visual chart no longer depends on the model choosing the exact supported fence syntax.

### Impact Analysis

The fix is scoped to successful grouped tabular tool results (`group_by_aggregate` and `group_by_datetime_component`). It does not add Mermaid rendering or change frontend chart behavior.