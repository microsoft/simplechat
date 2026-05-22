# Chat Stream Stop Control

## Overview

The chat stream stop control lets users stop an in-progress AI response from the active assistant message. It applies to standard chat streams, agent streams, document-action stream wrappers, and collaborative conversation streams.

Implemented in version: **0.241.097**

Updated in version: **0.241.098** to use a compact, icon-only circular Stop control aligned with the other chat message action buttons.

## Dependencies

- `application/single_app/route_backend_chats.py` for active stream lifecycle state and cancellation.
- `application/single_app/route_backend_collaboration.py` for collaboration stream cancellation proxying.
- `application/single_app/static/js/chat/chat-streaming.js` for the message-local Stop button and stopped-response rendering.
- `application/single_app/config.py` version updated to `0.241.098` with the Stop control refinement.

## Technical Specifications

Active stream sessions now support a `cancel_requested` state and a terminal `canceled` state. The frontend posts to `/api/chat/stream/cancel/<conversation_id>` for personal streams and `/api/collaboration/conversations/<conversation_id>/stream/cancel` for collaborative streams. The streaming generator checks cancellation at key checkpoints and while reading model or agent chunks.

When cancellation is acknowledged, the stream emits a terminal SSE payload with `done: true`, `cancelled: true`, the partial content, and any persisted assistant message metadata. If partial content exists, the backend saves it as an incomplete assistant message with cancellation metadata.

## Usage Instructions

Users click the circular stop-icon button on the currently streaming assistant message. The button changes to a stopping state while the backend cooperatively stops the response. The chat message then renders any partial response with a visible stopped banner.

## Testing and Validation

- Functional coverage: `functional_tests/test_chat_stream_stop_control.py` validates backend route/session wiring, collaboration proxying, frontend stop-button wiring, and version traceability.
- UI coverage: `ui_tests/test_chat_stream_stop_button.py` verifies the Stop button posts to the cancel endpoint and renders a stopped partial response from a mocked stream.

Known limitation: blocking pre-processing work can only stop at the next cancellation checkpoint, so some document or research operations may take a short moment before the stopped terminal event appears.