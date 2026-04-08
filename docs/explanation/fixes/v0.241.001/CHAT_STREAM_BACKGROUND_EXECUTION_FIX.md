# Chat Stream Background Execution Fix

Fixed/Implemented in version: **0.239.129**

## Issue Description

Leaving a streaming chat page before the assistant finished could stop the server-side chat execution entirely. In practice, backend logs stopped as soon as the browser disconnected, and the assistant response never reached the final persistence, unread-state, or notification paths.

## Root Cause Analysis

The normal `/api/chat/stream` implementation performed the model call and all downstream persistence directly inside the request-bound SSE generator.

That meant the request response loop was also the worker. Once the browser navigated away and the streaming response was torn down, the long-running chat work could stop with it.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_stream_background_execution.py`
- `functional_tests/test_streaming_only_chat_path.py`
- `functional_tests/test_chat_completion_notifications.py`

### Code Changes Summary

- Added a queue-backed `BackgroundStreamBridge` to decouple SSE delivery from chat execution.
- Wrapped the streaming worker with `copy_current_request_context()` so existing request/session-dependent chat logic can still run in background execution.
- Started the streaming worker through Flask-Executor when available, with a daemon-thread fallback.
- Routed both the normal streaming path and the compatibility streaming path through the same background bridge helper.
- Bumped the application version to `0.239.129`.

### Testing Approach

- Added `functional_tests/test_chat_stream_background_execution.py` to verify the background bridge, executor submission, and versioned fix documentation.
- Updated the relevant streaming and chat notification regression tests so their version checks stay aligned with the current app version.

## Validation

### Before

- Normal streaming chat execution lived inside the response generator.
- Navigating away from the chat page could terminate the in-flight assistant generation.
- Completion-side effects such as final message persistence and notifications could be skipped.

### After

- Chat generation is started in background execution and the HTTP response only relays queued SSE events.
- If the browser disconnects, the consumer detaches but the background chat worker can continue to completion.
- Final assistant persistence, unread markers, and completion notifications remain reachable even when the user leaves the page.

### Impact Analysis

This fix keeps the current streaming UX for connected users while removing the request lifecycle as the owner of the chat workload. It is intentionally minimal: the existing streaming generator remains the source of chat behavior, and the new bridge only changes how those events are delivered to the browser.