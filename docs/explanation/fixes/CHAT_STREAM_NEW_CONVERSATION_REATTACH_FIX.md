# Chat Stream New-Conversation Reattach Fix

Fixed/Implemented in version: **0.239.191**

`config.py` updated to `VERSION = "0.239.191"`.

## Issue Description

Streaming chat requests could start without an incoming `conversation_id`, which meant the replayable stream session was not registered even though the backend later created a real conversation id for the same request.

That left the reconnect endpoints unable to find the first in-flight reply for brand-new conversations when the stream had started from a null or empty conversation id.

## Root Cause Analysis

The stream registry keyed active sessions by `user_id` and `conversation_id`, but the streaming route attempted to register the session before the request had a finalized conversation id.

Later in the same request, the generator created a UUID for the new conversation and persisted it to Cosmos DB. Status and reattach requests used that finalized id, but the registry had never recorded a live session under the same key.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_stream_new_conversation_reattach.py`

### Code Changes Summary

- Finalized a conversation id at `/api/chat/stream` request entry before registering the replayable stream session.
- Reused the same finalized id throughout the streaming generator and compatibility bridge instead of generating a later replacement id.
- Kept new-conversation persistence logic, but changed it to persist the already-finalized id rather than inventing a new one mid-stream.
- Added a single automatic frontend recovery attempt that probes the stream status endpoint and reattaches when a live stream disconnects unexpectedly.
- Bumped the application version to `0.239.191`.

### Testing Approach

- Added `functional_tests/test_chat_stream_new_conversation_reattach.py` to verify that the backend finalizes a conversation id before registering the stream session.
- Verified the chat client contains a single automatic reattach path for unexpected streaming interruptions.

## Validation

### Before

- A streamed first reply could begin without a replayable session when the request arrived with a null or empty conversation id.
- The backend later created a real conversation id, but the active stream registry had nothing stored under that final key.
- The reconnect UX depended on the user manually reopening the conversation, and the first reply path remained fragile.

### After

- The backend finalizes a conversation id before registering the stream session, so status and reattach lookups use the same key the whole time.
- New-conversation streams and existing-conversation streams now share the same registry contract.
- The client makes one automatic recovery attempt before falling back to the existing interrupted-stream UI.

### Impact Analysis

This fix closes the stream identity gap for brand-new conversations without changing the existing session registry model or the persisted conversation schema. The backend remains conversation-scoped, and reconnect behavior becomes more resilient without introducing a second stream identifier.