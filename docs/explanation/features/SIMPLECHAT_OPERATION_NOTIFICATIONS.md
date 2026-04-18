# SimpleChat Operation Notifications

Implemented in version: **0.241.030**

## Overview and Purpose

SimpleChat workspace actions now create inbox notifications when they create a group, add a user to a group, or create a conversation. This complements the workflow priority modal by leaving a durable notification trail in the notifications experience.

Related config update:
- `application/single_app/config.py` now reports version `0.241.030`.

Dependencies:
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/functions_notifications.py`
- `application/single_app/semantic_kernel_plugins/simplechat_plugin.py`
- `application/single_app/templates/notifications.html`

## Technical Specifications

Coverage:
- Group creation creates a personal notification for the creator.
- Direct group member additions create a notification for the added user and a separate confirmation notification for the acting owner or admin.
- Group conversation creation fans out personal notifications to the current group membership with deep links into the new conversation.
- Personal conversation creation through the SimpleChat plugin creates a notification for the acting user, while the standard manual new-chat route stays quiet to avoid noise.
- Personal collaborative conversation creation notifies the creator and each invited participant.

Notification types:
- `group_created`
- `group_member_added`
- `conversation_created`

Navigation behavior:
- Group notifications link to `/manage_group/<group_id>` or `/chats?conversationId=<id>` with group context metadata.
- Conversation notifications use deep links that the chat page already understands.

## Usage Instructions

Examples that now create notifications:
1. A workflow uses the SimpleChat action to create a new group.
2. A workflow or user action adds a member to that group.
3. A workflow or user action creates a new group or collaborative conversation.

Users can review these events from the Notifications page and navigate directly from the notification entry.

## Testing and Validation

Functional coverage:
- `functional_tests/test_simplechat_operation_notifications.py`

Validation focus:
- creator notifications for group creation
- actor and recipient notifications for member additions
- conversation creation notifications for workflow-driven SimpleChat actions