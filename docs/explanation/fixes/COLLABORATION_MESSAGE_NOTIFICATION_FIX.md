# Collaboration Message Notification Fix (v0.241.016)

Fixed/Implemented in version: **0.241.016**

## Issue Summary

Shared conversations showed short-lived yellow toast notices on the chat page, but those alerts disappeared quickly and did not leave a persistent notification in the notifications inbox. Users could miss a new shared message or tag if they were not actively looking at the conversation when the toast appeared.

## Root Cause

- The collaboration event stream only produced browser toasts for the currently open shared conversation.
- Shared-message posts did not create notification-service records, so nothing appeared on the notifications page or in the bell badge.
- Opening a collaborative conversation had no mark-read endpoint for collaboration notifications, so there was no inbox lifecycle equivalent to the existing personal AI completion flow.

## Files Modified

- `application/single_app/functions_notifications.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/config.py`
- `functional_tests/test_collaboration_message_notifications.py`
- `ui_tests/test_chat_collaboration_ui_scaffolding.py`

## Code Changes

1. Added a new `collaboration_message_received` notification type in the notification service.
2. Added a collaboration notification helper that creates a deep link to `/chats?conversationId=...`, matching the existing chat-completion navigation pattern.
3. Added recipient fan-out for shared-message posts so accepted personal-collaboration participants and eligible group-collaboration members receive personal inbox notifications, excluding the sender.
4. Preserved mention context in the notification metadata so tagged recipients get a stronger inbox title.
5. Added a shared `mark-read` collaboration API and wired chat activation to clear collaboration notifications when the recipient opens the shared conversation or is already actively viewing it.

## Validation

- Added a functional regression covering helper deep links, recipient fan-out, group recipient resolution, and the collaboration mark-read route.
- Updated the collaboration UI scaffolding test to assert that shared conversation activation calls the collaboration mark-read endpoint.
- Focused diagnostics were run on the modified Python, JavaScript, and documentation files.

## User Impact

- Shared-message alerts now persist in the notifications inbox instead of disappearing with only a short toast.
- Notification clicks deep-link back into the shared conversation just like personal AI completion notifications.
- Shared notifications clear when the user opens the collaborative conversation, keeping the bell badge aligned with what the user has actually read.