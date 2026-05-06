# Tabular Analysis Progress Fix

Fixed in version: **0.241.133**

## Issue Description

Tabular analysis requests in chat could sit on the initial `Starting tabular analysis across N file(s)` thought for the full duration of the workbook processing run. The analysis still completed, but the user did not get the expected live progress card or a clear completion state while the tabular tools were running.

## Root Cause Analysis

- `register_tabular_invocation_thought_callback()` in `route_backend_chats.py` registered tabular callbacks under a tabular-specific key.
- `PluginInvocationLogger` dispatches start and completion callbacks using the shared `user_id:conversation_id` key.
- Because the keys did not match, live tabular tool start/completion events were never delivered to the thought renderer, so the chat UI stayed on the generic start thought instead of switching to the existing tabular progress card.

## Version Implemented

- **0.241.133**

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`
- `ui_tests/test_chat_tabular_thought_progress.py`

## Code Changes Summary

- Aligned the tabular live thought callback registration key with the shared plugin logger dispatch contract.
- Added a focused backend regression that verifies the tabular callback key and confirms running/completed activity thoughts are emitted through the shared logger path.
- Added a UI regression that simulates live tabular thought updates and verifies the progress card advances from a running state to a completed state.
- Updated the application version and the touched test file headers to the release that contains the fix.

## Testing Approach

- Ran `python -m py_compile application/single_app/route_backend_chats.py`.
- Ran `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`.
- Ran `python -m py_compile ui_tests/test_chat_tabular_thought_progress.py`.
- Ran `pytest ui_tests/test_chat_tabular_thought_progress.py -q`.

## Impact Analysis

- Long-running tabular analysis now surfaces the same progress-card experience the chat UI already supports for live activity updates.
- Users can see that tabular tool work is active instead of waiting on a static start badge.
- The completion state is now visible from live tabular thought updates before the final response fully takes over the message area.

## Validation

- Before: the chat UI could remain on the generic start thought for the entire tabular run even though tool invocations were being logged.
- After: live tabular tool updates flow through the shared callback path, the progress card appears while work is running, and the final tool update drives the card to a completed state.