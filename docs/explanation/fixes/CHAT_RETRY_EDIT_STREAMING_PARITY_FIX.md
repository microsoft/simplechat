# Retry and Edit Streaming Parity Fix

Issue description: Retry and edit flows were reported as potentially not streaming with the same visible progress and responsiveness as first-send chat.

Root cause: The retry and edit frontend modules already called `sendMessageWithStreaming()`, but `/api/chat/stream` treated every retry/edit request as compatibility mode. That routed retry/edit through the legacy JSON `chat_api()` compatibility bridge, which emits only terminal SSE metadata instead of live token chunks, live thoughts, stop controls, and normal stream recovery behavior.

Fixed/Implemented in version: **0.250.106**

Related config.py update: `VERSION = "0.250.106"`

## Technical Details

Files modified:

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_retry_edit_streaming_parity.py`

Code changes:

- Kept image generation on the stream compatibility bridge.
- Removed retry/edit from compatibility-mode routing so they use the full `/api/chat/stream` generator.
- Added stream-generator retry/edit handling that reuses the already-created retry/edit user message, its thread id, previous thread id, metadata, and attempt number.
- Preserved existing retry/edit frontend behavior because `chat-retry.js` and `chat-edit.js` already call the shared streaming client.

Testing approach:

- Added a functional regression test that verifies retry/edit are not routed through compatibility mode.
- Verified the stream generator reads and reuses the prepared retry/edit user message instead of creating a duplicate user message.
- Verified retry and edit frontend modules still invoke `sendMessageWithStreaming()`.

## Validation

Test coverage:

- `functional_tests/test_chat_retry_edit_streaming_parity.py`
- `python -m py_compile application/single_app/route_backend_chats.py`

Before:

- Retry/edit requests entered `/api/chat/stream` but were immediately diverted to the legacy compatibility bridge because `compatibility_mode` included `is_retry`.
- The browser received a terminal event after processing rather than the live stream path used for first-send chat.

After:

- Retry/edit requests enter the same stream generator as first-send chat.
- The stream generator reuses the retry/edit user message created by the preparation endpoint, preserving carousel attempt/thread semantics while restoring live streaming parity.

Impact:

- Retry and edit flows now get normal streamed content, live thought updates, stop controls, and recovery behavior across model and agent paths.
- Image generation remains safely handled by the existing compatibility bridge because image generation is not supported by the token stream path.

Reference: microsoft/simplechat#963
