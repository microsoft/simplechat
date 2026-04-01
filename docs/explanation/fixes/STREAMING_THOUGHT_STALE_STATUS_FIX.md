# Streaming Thought Stale Status Fix

## Fix Title
Streaming thought placeholders now stay scoped to the active assistant response instead of briefly showing the previous response's final thought.

## Issue Description
In back-to-back streaming chats, the next assistant placeholder could briefly display the final status from the prior response, such as a trailing model completion thought. Users would see the wrong thought badge while the new Semantic Kernel execution was just starting.

## Root Cause Analysis
- The streaming UI started conversation-level pending-thought polling even though the streaming response already delivered live thought events over SSE.
- That polling endpoint returns the latest recent thoughts for the conversation, so during the startup gap before the new response wrote its first thought, the client could receive the previous message's final thought.
- The streaming thought renderer updated a temporary assistant placeholder using a broad temp-message lookup instead of an explicitly tracked active streaming target.

## Version Implemented
Fixed in version: **0.239.181**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/static/js/chat/chat-streaming.js` | Removed streaming-mode reliance on pending-thought polling and bound live thought updates to the active temporary assistant placeholder |
| `application/single_app/static/js/chat/chat-thoughts.js` | Added per-stream thought session tracking and exact placeholder targeting for streaming thought renders |
| `application/single_app/route_backend_chats.py` | Added `message_id` to streaming thought SSE payloads so live thought events carry stable assistant-message identity |
| `functional_tests/test_streaming_thought_finalization.py` | Added regression coverage for message-scoped streaming thought updates |
| `application/single_app/config.py` | Version bump to 0.239.181 |

## Code Changes Summary
- Started an explicit streaming-thought session when a temporary assistant placeholder is created.
- Cleared that session on completion, error, or interrupted stream paths.
- Routed SSE thought events to the current placeholder by exact temporary message ID instead of searching for any `temp_ai_` node.
- Tracked backend `message_id` values for live thought events and ignored mismatched thought payloads.
- Stopped starting the conversation-level pending-thought polling flow for streaming chat responses.

## Testing Approach
- Extended `functional_tests/test_streaming_thought_finalization.py` with assertions covering message-scoped thought rendering and SSE `message_id` payloads.

## Impact Analysis
- Streaming placeholders should no longer inherit the previous response's terminal thought during quick consecutive prompts.
- The streaming path now relies on its native SSE thought feed instead of mixing conversation-level polling into the same UI state.
- The existing content-start guards remain in place, so live thoughts still cannot replace real streamed answer content once content begins.

## Validation
- Before: a new streaming response could begin with the prior response's final thought badge.
- After: a new streaming response stays on its neutral placeholder until its own live thoughts arrive, and those thoughts only render on the active placeholder.