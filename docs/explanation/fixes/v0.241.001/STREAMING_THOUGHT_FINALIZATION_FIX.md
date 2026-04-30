# Streaming Thought Finalization Fix

## Fix Title
Streaming chat responses now finalize reliably even when SSE events arrive across chunk boundaries or trailing thought events arrive after answer text has started streaming.

## Issue Description
In streaming mode, some responses would briefly show the full assistant answer and then revert to the final pulsing thought badge. The UI could remain stuck on that thought placeholder until the page was refreshed, even though the backend had already saved the assistant message.

## Root Cause Analysis
- The streaming client parsed each `reader.read()` chunk independently and split it by newline, which is not safe for SSE because a single event can arrive across multiple network chunks.
- When the final `done` event was split across chunks, the client could miss it and never finalize the temporary streaming message.
- The streaming thought renderer also replaced the entire temporary message body. If a late thought event arrived after answer text had already started rendering, it could overwrite the visible answer with the pulsing thought badge.

## Version Implemented
Fixed in version: **0.239.116**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/static/js/chat/chat-streaming.js` | Added buffered SSE frame parsing, explicit incomplete-stream handling, and content-start tracking for the temporary streaming message |
| `application/single_app/static/js/chat/chat-thoughts.js` | Prevented streaming thoughts from replacing the temporary message once answer content has begun streaming |
| `functional_tests/test_streaming_thought_finalization.py` | Added focused regression coverage for buffered SSE parsing and late-thought overwrite guards |
| `application/single_app/config.py` | Version bump to 0.239.116 |

## Code Changes Summary
- Added a stateful SSE buffer so JSON payloads are parsed only after a full SSE event block is available.
- Flushed the decoder and processed any trailing event data when the stream closes.
- Added a fallback error path when a stream ends without completion metadata so the UI does not hang indefinitely on the temporary placeholder.
- Marked the temporary streaming message once real answer content starts rendering.
- Ignored subsequent streaming-thought placeholder renders after that point so answer text stays visible until finalization replaces the temporary message with the permanent assistant message.

## Testing Approach
- Added `functional_tests/test_streaming_thought_finalization.py`.
- Re-ran the existing thoughts feature structural coverage to confirm the edited modules still expose the expected thought integration points.

## Impact Analysis
- Streaming responses should now remain stable on screen after answer text begins rendering.
- Split SSE frames should no longer prevent the final `done` payload from being processed.
- If the server ever closes a stream without completion metadata, the user now sees a partial-response warning instead of a permanent pulsing placeholder.

## Validation
- Before: final streamed answers could be replaced by the last thought badge and remain stuck until refresh.
- After: answer text remains visible once content starts, and the temp streaming message either finalizes correctly or degrades into an explicit interrupted-stream state.