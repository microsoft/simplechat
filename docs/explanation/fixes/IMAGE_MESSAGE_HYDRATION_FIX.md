# Image Message Hydration Fix

Fixed/Implemented in version: **0.241.024**

## Overview

Generated images were being stored successfully, but the chat renderer could still fail to display them after streaming or after a refresh. Collaborative conversations also attempted to mirror the raw generated-image payload into the collaboration message store, which could exceed the Cosmos DB item-size limit and interrupt the shared AI stream before the final image message was emitted.

## Root Cause

- The shared non-AI renderer only kept message bodies that still had visible plain text after HTML stripping. Image bubbles render as an `<img>` tag, so the renderer dropped the entire message body even when a valid image source existed.
- Single-user and uploaded-image storage duplicated chunking logic across multiple routes, which made reassembly and response handling harder to keep consistent.
- Collaboration mirroring reused legacy image metadata and then copied generated image content directly into the collaboration message document, which broke the intended lightweight-reference design and could trigger `RequestEntityTooLarge` in Cosmos DB.
- The collaboration stream bridge still emitted the mirrored collaboration message content directly for image completions instead of using a collaboration-specific image endpoint, so the live shared response path stayed inconsistent with the message reload path.
- The collaboration stream completion transformer reassigned `updated_conversation_doc` inside its nested closure, which made Python treat that name as a local variable and raised `cannot access local variable 'updated_conversation_doc'` before the mirrored image response could be saved.

## Files Modified

- `application/single_app/functions_image_messages.py`
- `application/single_app/collaboration_models.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_frontend_chats.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/route_frontend_conversations.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `functional_tests/test_base64_image_handling.py`
- `functional_tests/test_chunked_image_storage.py`
- `functional_tests/test_large_image_api.py`
- `functional_tests/test_collaboration_image_reference.py`
- `ui_tests/test_chat_generated_image_rendering.py`
- `application/single_app/config.py`

## Code Changes

1. Added a shared helper for image document chunking, conversation-response hydration, binary decoding, and image-content reassembly.
2. Replaced the duplicated chunking logic in generated-image storage and uploaded-image storage with the shared helper.
3. Replaced the duplicated image reassembly logic in both conversation message endpoints with the shared helper so refresh behavior stays consistent.
4. Added a collaboration image URL builder and a collaboration image endpoint that serves the actual source image content on demand.
5. Stopped collaboration image mirroring from copying raw base64 content or inline data URLs into the collaboration message record.
6. Updated the collaboration serializer and live stream bridge so shared image responses always use the collaboration image endpoint instead of the mirrored placeholder content.
7. Updated the shared chat renderer so image messages always keep their visible image markup even when the message body contains no plain text.
8. Fixed the collaboration stream completion closure so synced conversation state uses dedicated local names instead of shadowing `updated_conversation_doc` inside the nested transformer.

## Validation

- Added helper-backed functional regressions for base64 decoding, chunked storage, large-image reassembly, and collaboration image references.
- Added a UI regression that appends image messages through the shared chat renderer and verifies both single-user and collaboration image bubbles remain visible.
- Verified editor diagnostics were clean for the touched Python and JavaScript files.

## User Impact

- Generated images now display again in single-user chat instead of rendering only the surrounding metadata and actions.
- Refreshing a conversation now consistently rehydrates chunked images through the shared image helper.
- Collaborative image responses no longer try to persist oversized base64 payloads inside the collaboration container.
- Shared image-generation streams now complete with a collaboration image URL instead of failing during the mirror step.
- Participants in collaborative conversations now load mirrored images through a collaboration-specific image endpoint backed by the original source message.
- Shared image-generation streams no longer fail on the `updated_conversation_doc` closure scoping bug during collaboration completion.