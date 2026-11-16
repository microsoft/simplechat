# V2 Stream Cancelled When Leaving a Conversation

**Fixed in version:** 0.261.050

## Issue

In the V2 interface, sending a message and then opening a different conversation while the
answer was still being generated destroyed the answer. Returning to the original thread
showed the question with no reply, and the response never arrived.

The symptom depended on timing in a way that made it look intermittent. Leaving during the
"thinking" phase, before the assistant had produced its first token, meant no reply was ever
saved at all. Leaving later left a truncated one.

The V1 (classic) interface does not behave this way: a generation continues after a thread
switch, is reattached to when the thread is reopened, and several conversations can be
generating at once.

## Root cause

This was a cancellation bug, not a reconnection bug. The reconnect machinery was working
correctly; it was being asked to reattach to a stream that had already been cancelled.

Leaving a conversation reached a real server-side cancellation:

1. `chatStore.ts` — `selectConversation` and `startNewConversation` both opened with
   `get().stopStreaming()`.
2. `chatStore.ts` — `stopStreaming` POSTs `/api/chat/stream/cancel/<conversation_id>`
   before aborting the local reader.
3. `route_backend_chats.py` — `chat_stream_cancel_api` calls
   `stream_session.request_cancel(...)`.
4. `route_backend_chats.py` — `request_cancel` sets `cancel_requested`, which is surfaced
   by `is_cancel_requested()` and threaded through the generation loop as its
   `cancel_requested` callback. The agent genuinely stops.

Because the cancel was destructive, `resumeChatStream` then found the stream in a terminal
state, `pending` was false, and it correctly declined to reattach. There was nothing left to
reattach to.

### Why the timing changed the symptom

The stream cancel event is built two different ways depending on when the cancel lands:

* Before any content: `message_persisted=False` — no assistant message is written.
* After content has started: `partial_content=...` with
  `message_persisted=bool(payload.get('message_id'))` — a partial answer is saved.

That is why leaving early looked like the response was never generated, while leaving later
produced a truncated one.

### Why detaching is safe

`build_background_stream_response` is documented as running "SSE generation in background
execution so it survives disconnects". Dropping the reader does not stop the work. Only an
explicit cancel does. The two had been conflated.

## Fix

Separate *stop reading* from *stop generating*. Only the Stop button means the second one.

### Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/stores/chatStore.ts` | Added module-level `detachActiveStream()`; `stopStreaming` now cancels then delegates teardown to it; `selectConversation` and `startNewConversation` call it instead of `stopStreaming` |
| `application/v2_ui/src/components/layout/Sidebar.tsx` | Corrected a comment whose stated rationale — that resetting loses the reply — is no longer true |
| `application/single_app/config.py` | Version `0.261.049` -> `0.261.050` |

`detachActiveStream()` aborts the in-flight reader, clears `activeStreamController` and
`streamingConversationId`, and resets `streaming`, `streamingContent`, and `reconnectPhase`.
It issues no cancel request.

The state reset belongs in the helper rather than at the call sites: neither
`selectConversation` nor `startNewConversation` sets `streaming: false` in its own state
update, so omitting it would leave the composer showing Stop for a stream nothing is
reading.

`stopStreaming` is unchanged from the user's point of view. It still addresses
`streamingConversationId` through the correct cancel route for personal or shared
conversations, and the Stop button remains its only caller.

## Behaviour after the fix

* Leaving a conversation mid-generation detaches. The answer finishes and is saved.
* Reopening that conversation resumes the live stream through `resumeChatStream`, or shows
  the completed reply if generation finished while away.
* Several conversations can be generating at once, matching V1. V2 still displays only the
  one on screen; the others complete in the background and are flagged by the existing
  unread marker.
* Stop still cancels, exactly as before.
* Leaving a shared conversation no longer cancels a generation other participants are
  waiting on.

An abandoned generation now runs to completion instead of being cancelled. This is
deliberate and matches V1 — it is what makes the answer still be there on return.

## Validation

`functional_tests/test_v2_stream_leave_without_cancel.py` (12 tests) covers:

* `selectConversation` and `startNewConversation` do not reach `cancelStream`.
* `detachActiveStream` issues no cancel, still aborts the reader, clears the ownership
  marker, and clears `streaming` so the composer stays usable.
* `stopStreaming` still cancels and the Stop button is still wired to it.
* `cancelStream` has exactly one call site in the store.
* Server premises: the cancel route reaches `request_cancel`, `request_cancel` sets
  `cancel_requested`, the generation loop checks `is_cancel_requested()`, the pre-content
  cancel path reports `message_persisted=False`, and streaming survives disconnects.
* V1 parity: `chat-conversations.js` reattaches on select and never cancels;
  `reattachStreamingConversation` opens its stream without a cancel endpoint.

The assertions were confirmed to fail against the pre-fix code, so they detect the
regression rather than merely describing the current implementation.

`functional_tests/test_v2_stream_reconnect.py` (10 tests) continues to pass, confirming the
reconnect contract this fix depends on is intact.

## Related

* `docs/explanation/fixes/` — reconnect behaviour is covered by
  `functional_tests/test_v2_stream_reconnect.py`
* `application/single_app/route_backend_chats.py` — stream session registry, cancel, status,
  and reattach routes
