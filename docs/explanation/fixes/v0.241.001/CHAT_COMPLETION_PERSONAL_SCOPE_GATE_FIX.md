# Chat Completion Personal Scope Gate Fix

Fixed/Implemented in version: **0.239.133**

## Issue Description

Personal chat responses could complete and save successfully after the user navigated away, but no completion notification appeared and no green unread dot was shown when returning to the chat page.

## Root Cause Analysis

The streaming completion path decided whether to create chat-completion notifications by checking `active_group_id` and `active_public_workspace_id` from the request/session state.

Those workspace identifiers can stay populated even when the actual conversation being completed is still a personal chat. In that case, the route incorrectly skipped the personal unread-state and notification writes.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_completion_notifications.py`
- `functional_tests/test_chat_stream_background_execution.py`
- `functional_tests/test_streaming_only_chat_path.py`

### Code Changes Summary

- Added `is_personal_chat_conversation(...)` to classify the completed conversation from its saved `chat_type`.
- Updated the streaming completion path to use conversation metadata instead of active workspace session values when deciding whether to create personal unread-state and notification side effects.
- Added debug logging for the non-personal skip path to make future scope mismatches easier to diagnose.
- Bumped the application version to `0.239.133`.

### Testing Approach

- Extended the chat completion notification regression to verify the streaming completion path uses the personal-conversation helper instead of the old active-workspace gate.
- Updated the streaming route regressions so their version assertions stay aligned with the current app version.

## Validation

### Before

- Personal chats could complete and persist the assistant answer without receiving completion-side unread state or notifications.
- A stale active group or public workspace in session could suppress personal notifications incorrectly.

### After

- Personal chat completion side effects are now keyed off the saved conversation type.
- Personal chats continue to receive unread markers and completion notifications even if unrelated workspace session state is populated.