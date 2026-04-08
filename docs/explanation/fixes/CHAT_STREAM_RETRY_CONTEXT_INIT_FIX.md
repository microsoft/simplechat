# CHAT STREAM RETRY CONTEXT INIT FIX

Fixed/Implemented in version: **0.240.080**

Related config.py update: `VERSION = "0.240.081"`

## Issue Description

Normal streaming chat requests could fail before any assistant output was generated with `NameError: name 'is_retry' is not defined`.

## Root Cause Analysis

- The streaming `/api/chat/stream` route referenced `is_retry` and `retry_thread_attempt` during assistant thread-alignment setup.
- That route never initialized the retry/edit context variables that already existed in the non-streaming `/api/chat` path.
- As a result, even normal streamed messages that were not retries could crash when the code reached `assistant_thread_attempt = retry_thread_attempt if is_retry else 1`.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_stream_retry_context_init_fix.py`

### Code Changes Summary

- Added streaming-route initialization for `retry_user_message_id`, `retry_thread_id`, `retry_thread_attempt`, `is_retry`, and `is_edit` before compatibility and generator logic use them.
- Updated streaming compatibility-mode selection to reuse the initialized `is_retry` flag rather than recomputing retry detection inline.
- Added retry/edit debug logging for the streaming path so future regressions are easier to diagnose.
- Bumped the application version to `0.240.080`.

### Testing Approach

- Functional regression: `functional_tests/test_chat_stream_retry_context_init_fix.py`

## Validation

### Before

- `/api/chat/stream` could throw a `NameError` for `is_retry` on ordinary streamed messages.
- Streaming chat stopped before the assistant response was persisted or returned.

### After

- `/api/chat/stream` initializes retry/edit context before assistant thread logic references it.
- Normal streaming chat messages no longer depend on undefined retry variables.