# Chat Inline Chart Final Canvas Fix

Fixed in version: **0.241.134**

## Issue Description

Inline `simplechart` responses could render correctly while the assistant response was streaming, then become a blank chart area after streaming completed and the final saved message replaced the temporary streaming message.

## Root Cause Analysis

Final assistant messages apply message metadata through the masking state pipeline. That pipeline captured original message content after Chart.js had hydrated the chart, then restored cloned DOM nodes. Cloned canvas elements keep attributes such as `data-chart-hydrated="true"`, but they do not keep the rendered canvas pixels or the Chart.js instance. The final DOM therefore looked hydrated while the canvas was blank.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-inline-charts.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_backend_inline_chart_handoff.py`
- `ui_tests/test_chat_inline_chart_rendering.py`

Code changes:

- Added inline chart destruction/rehydration handling so restored message content cannot retain stale Chart.js state.
- Moved chart hydration to run after message masking metadata restores original content.
- Made chart hydration repair chart containers that are marked hydrated but have no live Chart.js instance.
- Added UI regression coverage for final assistant messages that include metadata.
- Updated `config.py` to version `0.241.134`.

## Validation

Test coverage:

- `functional_tests/test_chat_backend_inline_chart_handoff.py`
- `ui_tests/test_chat_inline_chart_rendering.py`

Validation performed:

- JavaScript syntax checks passed for the chart renderer and chat message renderer.
- Python compile checks passed for the updated tests and config.
- Backend inline chart handoff functional test passed.
- Manual authenticated chat validation used the model-generated prompt `make a pie chart 33% apples, 33% oranges, and 34% pears`; after streaming completed, the final chart had a live Chart.js instance and nonblank canvas pixels.