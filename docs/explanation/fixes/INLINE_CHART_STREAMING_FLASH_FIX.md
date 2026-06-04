# Inline Chart Streaming Flash Fix

Fixed/Implemented in version: **0.241.141**

## Issue Description

Inline charts could render before the assistant response finished, then visibly flash while additional streamed text continued to arrive after the chart block.

## Root Cause Analysis

The streaming renderer replaced the full assistant message HTML on every content chunk. When a complete `simplechart` block was already present, that replacement destroyed the hydrated Chart.js canvas and immediately recreated it, causing repeated visual flashes until the response completed.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/static/js/chat/chat-inline-charts.js`
- `ui_tests/test_chat_inline_chart_rendering.py`
- `application/single_app/config.py`

Code changes summary:

- Streaming updates now preserve already-hydrated inline chart DOM nodes when the rendered chart specification is unchanged.
- Preserved chart nodes keep the same canvas and Chart.js instance while surrounding text continues to stream.
- Unused preserved chart nodes are destroyed through the shared chart cleanup helper to avoid leaking Chart.js instances.
- Duplicate image proposal hydration calls in the streaming loop were removed while touching the same refresh path.

## Validation

Validation commands:

- `node --check application/single_app/static/js/chat/chat-streaming.js application/single_app/static/js/chat/chat-inline-charts.js`
- `python -m py_compile application/single_app/config.py ui_tests/test_chat_inline_chart_rendering.py`
- `python -m pytest ui_tests/test_chat_inline_chart_rendering.py -q`

Expected behavior:

- A chart that appears before the full response finishes remains visually stable while later text streams in.
- The chart is not re-created when the chart spec is unchanged.
- Incomplete chart blocks still show the existing pending chart placeholder until the chart source is complete.