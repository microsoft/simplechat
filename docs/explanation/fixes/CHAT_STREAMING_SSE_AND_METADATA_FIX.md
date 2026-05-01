# Chat Streaming SSE And Metadata Fix

Fixed in version: **0.241.049**

## Issue Description

Streaming assistant responses could fail partway through rendering with `Error parsing SSE data` in `chat-streaming.js`, and temporary AI placeholder renders produced noisy `No metadata found for AI message` console entries. In the same streaming path, the final assistant message was rebuilt without the message metadata already written on the backend.

## Root Cause Analysis

- One agent-streaming branch in `route_backend_chats.py` emitted the literal characters `\n\n` instead of real SSE frame delimiters, which caused multiple JSON payloads to be concatenated inside one client parse block.
- `finalizeStreamingMessage` rebuilt the final message with `fullMessageObject = null`, so metadata stored in the backend assistant document was discarded during the final client render.
- `appendMessage` logged missing metadata for every temporary AI placeholder, which turned a normal temporary render into misleading console noise.

## Version Implemented

- **0.241.049**

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `functional_tests/test_chat_streaming_sse_metadata_fix.py`

## Code Changes Summary

- Corrected the agent-streaming SSE chunk emitter to use real `\n\n` separators.
- Added a defensive client-side normalizer in `chat-streaming.js` so malformed legacy escaped SSE delimiters do not break the parser if encountered.
- Included backend message metadata in final streaming payloads and passed the completed payload back into `appendMessage` as the final `fullMessageObject`.
- Removed the AI-side missing-metadata console noise for temporary placeholder messages.

## Testing Approach

- Added `functional_tests/test_chat_streaming_sse_metadata_fix.py` to validate the corrected SSE emitter contract, final metadata handoff, and removal of noisy AI metadata logging.
- Ran the new functional test locally in the repository virtual environment.

## Impact Analysis

- Streaming agent responses no longer corrupt the SSE parser when the agent chunk branch is used.
- Final streamed assistant messages preserve backend metadata for masking and other client-side metadata consumers.
- Browser console output is quieter and no longer reports a false metadata problem for temporary AI placeholders.

## Validation

- Before: agent streaming could log `Unexpected non-whitespace character after JSON` and final streamed AI messages lost metadata during re-render.
- After: streamed chunks are frame-delimited correctly, final message metadata is preserved, and temporary placeholder renders no longer emit the misleading AI metadata log.