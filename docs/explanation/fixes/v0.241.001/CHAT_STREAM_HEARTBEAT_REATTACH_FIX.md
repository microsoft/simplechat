# Chat Stream Heartbeat Reattach Fix

Fixed/Implemented in version: **0.239.183**

## Issue Description

Long-running chat streams could still go quiet long enough to hit Azure App Service idle timeouts, and navigating away from a conversation meant the browser lost the live stream even though the backend worker kept running.

The original reconnect support also depended on in-process memory, so reconnecting from a different App Service or gunicorn worker could miss the active stream entirely.

## Root Cause Analysis

The streaming route sent useful SSE data only when a model token or explicit thought event was available. There was no transport-level heartbeat during long blocking phases such as tool execution or tabular analysis.

The background worker also outlived the original HTTP consumer, but the live response stream was only attached to that first request. Reopening the conversation later loaded persisted messages only and had no way to replay or rejoin the in-flight response.

The first reconnect registry stored replay state only in module globals, which made it best-effort inside a single worker process but not durable across multi-worker deployments.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/app_settings_cache.py`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_stream_background_execution.py`
- `functional_tests/test_chat_stream_heartbeat_reattach.py`
- `functional_tests/test_chat_stream_compatibility_sse_syntax.py`
- `functional_tests/test_chat_stream_debug_logging.py`
- `functional_tests/test_streaming_only_chat_path.py`
- `functional_tests/test_streaming_thought_finalization.py`

### Code Changes Summary

- Added SSE heartbeat comments so active stream connections continue emitting bytes during long idle gaps.
- Added a per-user, per-conversation active stream registry that stores in-flight SSE history for reconnecting consumers.
- Added Redis-backed session metadata and event replay through `app_settings_cache.py`, with same-process in-memory fallback when Redis is disabled.
- Added stream status and reattach endpoints so the frontend can reconnect to an active conversation stream.
- Updated the chat client to remove the hardcoded five-minute timeout, wait for saved message reload, and then attempt reattachment for pending conversations.
- Kept backend processing detached from the browser request so navigation away does not cancel server-side completion.
- Bumped the application version to `0.239.183`.

### Testing Approach

- Added `functional_tests/test_chat_stream_heartbeat_reattach.py` to verify heartbeat emission, cache-backed session replay hooks, and frontend reattach hooks.
- Updated existing streaming regression tests to reflect the new version and stream-session routing.

## Validation

### Before

- Long blocking phases could leave the SSE connection silent for too long.
- A user returning to the conversation only saw persisted messages after the stream fully completed.
- The frontend had a separate five-minute timeout path that could interrupt the visible stream.

### After

- Active stream responses emit keep-alive comment frames while waiting for the next real SSE payload.
- Reopening a conversation can reconnect to the still-running stream and replay its in-flight events.
- Redis-enabled deployments can reattach across App Service or gunicorn workers because session metadata and event history are no longer limited to a single process.
- The backend worker continues independently, and the frontend no longer imposes a hard five-minute timeout on the stream.

### Impact Analysis

This change improves resilience for long-running chat operations without changing the persisted message model. Completed replies still become the source of truth in Cosmos DB, while in-flight replies gain a durable reconnect path when Redis is enabled and still retain same-process fallback behavior when it is not.