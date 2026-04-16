# Collaboration Message Delete Fix (v0.241.018)

Fixed/Implemented in version: **0.241.018**

## Issue Summary

Deleting a message inside a collaborative conversation failed with a 404 because the chat UI always called the legacy personal message delete endpoint.

## Root Cause

- Shared messages use the collaboration message store, not the personal `cosmos_messages_container`.
- The delete button for the current user's shared messages still posted to `/api/message/<message_id>`, so the backend looked in the wrong container and returned `Message not found`.
- The shared delete flow also reused the personal thread-delete confirmation modal even though collaborative replies are not backed by the same retry/thread model.

## Files Modified

- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_collaboration_message_delete_fix.py`

## Code Changes

1. Added a collaboration helper that deletes a shared message from the collaboration container and recalculates `message_count`, `last_message_preview`, and `last_message_at`.
2. Added a dedicated shared-message delete route at `/api/collaboration/conversations/<conversation_id>/messages/<message_id>`.
3. Published a `collaboration.message.deleted` live event so other participants' open chat views remove the deleted message without a manual refresh.
4. Updated the chat UI to route shared-message deletes to the collaboration API instead of the personal message delete endpoint.
5. Switched shared user-message deletes to the single-message confirmation flow instead of the personal thread-delete modal.

## Validation

- Added a functional regression covering the helper behavior, the collaboration delete route contract, the published live delete event, and the frontend endpoint wiring.
- Focused editor diagnostics on the modified JavaScript, Python, and markdown files completed without errors.

## User Impact

- Deleting your own message in a collaborative conversation now succeeds instead of returning `Message not found`.
- Shared conversation previews stay in sync after deletion.
- Other participants with the shared conversation open see the deleted message disappear via the collaboration event stream.