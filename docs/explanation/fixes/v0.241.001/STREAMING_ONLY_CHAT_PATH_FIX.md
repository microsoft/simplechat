# Streaming-Only Chat Path Fix

Fixed in version: **0.239.127**

## Issue Description

The chat experience still maintained two first-party execution paths:

- A streaming SSE path for normal chat responses.
- A legacy non-streaming JSON path used as a direct fallback by the main send flow, retry flow, and edit flow.

That duplication created drift between the two implementations. Features such as image generation, retry/edit behavior, and final message handling existed in the legacy path, while the product direction is to make streaming the only chat path used by the application.

## Root Cause Analysis

The frontend still posted directly to `/api/chat` from multiple modules, and the chat toolbar still presented streaming as optional. At the same time, the streaming finalizer did not fully support all terminal payload shapes already used by the legacy route, especially image results and reload-driven completion behavior.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/static/js/chat/chat-edit.js`
- `application/single_app/static/js/chat/chat-retry.js`
- `application/single_app/static/js/chat/chat-input-actions.js`
- `application/single_app/templates/chats.html`
- `application/single_app/templates/profile.html`
- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_streaming_only_chat_path.py`

### Code Changes Summary

- Removed the first-party chat UI fallback that posted directly to `/api/chat`.
- Moved retry and edit flows onto the shared streaming helper.
- Removed the chat toolbar streaming toggle so streaming is no longer presented as optional.
- Extended the streaming finalizer to support image-generation results and reload-driven completion handling.
- Added a streaming compatibility bridge in the backend for parity-sensitive requests, including image generation and retry/edit, while keeping `/api/chat` available as a temporary compatibility shim.
- Updated defaults and profile messaging to reflect streaming-only chat behavior.
- Added image-generation thought events on the streaming compatibility bridge so users see progress before the final image arrives.
- Bumped the application version to `0.239.127`.

## Testing Approach

A functional regression test was added at `functional_tests/test_streaming_only_chat_path.py` to verify:

- Main chat, retry, and edit entry points do not call `/api/chat` directly.
- The streaming helper still uses `/api/chat/stream`.
- The backend streaming route contains the compatibility bridge.
- Image-generation compatibility requests emit useful streaming thoughts before the final image payload.
- The chat template no longer includes the streaming toggle button.
- The default setting and app version were updated.

## Impact Analysis

This change makes streaming the only first-party chat path exposed by the UI while preserving legacy behaviors through the streaming endpoint for image generation and retry/edit flows. It reduces the risk of feature drift between chat implementations and provides a safer base for removing the legacy shim entirely in a later cleanup pass.

## Validation

### Before

- Main send flow could fall back to `/api/chat`.
- Retry and edit always posted to `/api/chat`.
- Image generation was blocked on the streaming route.
- The toolbar exposed streaming as an optional toggle.

### After

- First-party chat flows send through `/api/chat/stream`.
- Retry and edit are routed through the same streaming helper.
- Image-generation requests are supported through the streaming route via the backend compatibility bridge.
- Streaming is treated as required chat behavior in the UI.
