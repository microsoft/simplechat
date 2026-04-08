# Chat Stream Background Bridge Restore Fix

Fixed/Implemented in version: **0.239.132**

## Issue Description

Leaving the chat page during a streamed response could still cause the assistant answer to disappear entirely from the conversation, with no completion notification and no unread marker when returning later.

## Root Cause Analysis

The active `route_backend_chats.py` route had drifted back to returning `stream_with_context(generate())` directly for both streaming entry points. That made the request-bound SSE generator the owner of assistant generation again, so browser navigation could terminate the stream before final assistant persistence and notification side effects ran.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_completion_notifications.py`

### Code Changes Summary

- Restored a queue-backed `BackgroundStreamBridge` to decouple SSE delivery from the background chat worker.
- Wrapped the worker with `copy_current_request_context()` so existing request/session-dependent logic remains available during background completion.
- Routed both the main streaming path and compatibility streaming path through the background bridge helper.
- Advanced the application version to `0.239.132` to match the active streaming regression suite.

### Testing Approach

- Reused the existing streaming background execution regression to verify the bridge class, executor submission, fallback thread path, and route wiring.
- Updated the chat completion notification regression to validate the current app version after the restore.

## Validation

### Before

- Chat logs could show intermediate tool work but never reach final assistant persistence.
- Returning to the conversation could show only the user message because the response died with the detached request.
- Completion notifications and unread dots were skipped because the finalization block never ran.

### After

- Streaming chat work is executed in background execution and only relayed through the HTTP response.
- Browser disconnects detach the consumer without canceling the background worker.
- Final assistant persistence, unread state, and completion notifications remain reachable after navigation away from the chat page.