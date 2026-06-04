# Chat Inline Chart YAML Streaming Fix

Fixed in version: **0.241.126**

## Issue Description

Normal chat chart responses could display raw `simplechart` source text instead of an inline chart card when the assistant emitted a YAML-style chart block. During streaming, incomplete chart fences were also rendered as visible text before the chart block finished.

## Root Cause Analysis

The inline chart renderer only parsed JSON payloads inside `simplechart` fenced blocks. If the assistant emitted a YAML-like block such as `chartType: pie`, parsing failed and the markdown renderer treated the block as ordinary code. Incomplete streaming fences were not hidden because the chart extractor only matched closed fences.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-inline-charts.js`
- `application/single_app/config.py`
- `ui_tests/test_chat_inline_chart_rendering.py`

Code changes:

- Added a constrained YAML-like parser for the chart block shape produced by chat responses.
- Normalized generic `kind: chart` values through `chartType` so `chartType: pie` renders correctly.
- Honored Chart.js-style legend options under `options.plugins.legend`.
- Replaced incomplete `simplechart` fences with a chart status card so raw chart source is not visible during streaming.
- Added UI coverage for completed YAML-style charts and pending chart blocks.

## Validation

Test coverage:

- `ui_tests/test_chat_inline_chart_rendering.py`

Expected behavior:

- Users see a chart card instead of YAML chart text when a completed chart block is present.
- Users see a pending chart card, not raw chart source, while a chart block is still streaming.
- Completed chart messages still render correctly after the stream finishes or the message is reloaded.