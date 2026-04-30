# Chat Completion Stream Finalization Fix

Fixed/Implemented in version: **0.239.130**

## Issue Description

Personal chat responses could finish successfully in the background, but the user would not receive a completion notification and the conversation would not show the green unread dot when returning to the chat page.

## Root Cause Analysis

The streaming `/api/chat/stream` completion path persisted the final assistant message and updated conversation metadata, but it did not mark the conversation as unread or create the personal `chat_response_complete` notification before emitting the terminal SSE payload.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_completion_notifications.py`

### Code Changes Summary

- Restored unread-state writes in the streaming completion branch using `mark_conversation_unread(...)`.
- Restored personal completion-notification creation using `create_chat_response_notification(...)`.
- Kept the behavior scoped to personal chats only by skipping group and public workspace completions.
- Added regression coverage that inspects the streaming completion path for the unread-state and notification calls.
- Bumped the application version to `0.239.130`.

### Testing Approach

- Extended `functional_tests/test_chat_completion_notifications.py` to verify the SSE completion branch includes unread-state and notification creation.

## Validation

### Before

- Background chat completion could persist the assistant message without creating a notification.
- Returning to the chat page showed no unread dot because the conversation unread fields were never written.

### After

- Personal streaming completions mark the conversation unread before the final SSE payload is sent.
- Personal streaming completions create a `chat_response_complete` notification with the conversation deep link.
- Returning to the chats page shows the green unread dot until the conversation is opened or marked read.