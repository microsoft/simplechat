# Chat Completion Notifications (v0.239.128)

## Overview
Chat completion notifications add background awareness for personal chat conversations. When a streamed assistant response finishes after the user has moved away from the chat, the app now creates a personal notification that deep-links back to the exact conversation and shows a green unread dot in both conversation lists until the conversation is opened.

**Version Implemented:** 0.239.128

## Dependencies
- Flask chat and conversation routes
- Cosmos DB conversations and notifications containers
- Existing notification platform in `functions_notifications.py`
- Chat SSE finalization in `static/js/chat/chat-streaming.js`
- Main and sidebar conversation list modules

## Implemented in version: **0.239.128**

## Architecture Overview

### Backend
- **Stream completion hook:** `application/single_app/route_backend_chats.py`
- **Unread-state helpers:** `application/single_app/functions_conversation_unread.py`
- **Notification helpers:** `application/single_app/functions_notifications.py`
- **Read/clear endpoint:** `POST /api/conversations/<conversation_id>/mark-read`

When a personal chat stream completes, the backend now:
- persists the assistant message as before
- marks the conversation with unread assistant-response fields
- creates a personal `chat_response_complete` notification
- stores `conversation_id` and `message_id` in notification metadata
- uses `/chats?conversationId=...` as the notification deep link

### Frontend
- **Main list module:** `application/single_app/static/js/chat/chat-conversations.js`
- **Sidebar list module:** `application/single_app/static/js/chat/chat-sidebar-conversations.js`
- **Stream finalization:** `application/single_app/static/js/chat/chat-streaming.js`
- **Styling:** `application/single_app/static/css/chats.css`, `application/single_app/static/css/sidebar.css`

The chat UI now:
- renders a green unread dot for personal conversations with unread assistant responses
- clears unread state when a conversation is opened
- immediately clears the just-created unread state if the user is still watching that conversation when streaming finishes

## Notification Behavior

### Deep-Linking
Notification clicks use the existing notification navigation flow and point directly to:

`/chats?conversationId=<conversation_id>`

`chat-onload.js` already supports this URL shape, so the destination conversation is selected automatically after the chat page loads.

### Approximate Active-View Suppression
This implementation intentionally does not add heartbeat or presence tracking. Instead:
- the backend always creates the completion notification for personal chats
- the active chat page immediately calls the new mark-read endpoint after stream completion
- this keeps the user-facing result aligned with the active-view scenario without adding presence infrastructure

## Conversation Data Shape
Personal conversation payloads now normalize these fields:
- `has_unread_assistant_response`
- `last_unread_assistant_message_id`
- `last_unread_assistant_at`

Older conversation documents that do not yet contain these fields are normalized to safe defaults in the conversation list and metadata APIs.

## Files Updated
- `application/single_app/functions_conversation_unread.py`
- `application/single_app/functions_notifications.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/static/js/chat/chat-sidebar-conversations.js`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/static/css/chats.css`
- `application/single_app/static/css/sidebar.css`
- `application/single_app/config.py`
- `functional_tests/test_chat_completion_notifications.py`

## Usage Instructions
- Start a personal chat and send a prompt that takes long enough for streaming to remain active.
- Navigate away from the chat page before the response completes.
- After completion, open Notifications and click the new AI response notification.
- The app navigates back to the exact conversation and clears the unread state.

## Testing and Validation
- **Functional test:** `functional_tests/test_chat_completion_notifications.py`

The regression test validates:
- chat-response notification creation and deep-link shape
- unread-field normalization for older conversation documents
- mark-read endpoint clearing both conversation unread state and notification read state
- frontend wiring for unread dots and mark-read calls

## Performance Considerations
- No polling was added beyond the existing notification badge polling
- The mark-read endpoint is idempotent and lightweight
- The unread indicator stores a single latest unread assistant response state, not an unread count

## Known Limitations
- First rollout is personal chats only
- Group and public chat conversations do not yet participate in this notification flow
- Presence detection is approximate rather than heartbeat-based
- The green dot indicates unread assistant completion state, not a count of unread assistant messages