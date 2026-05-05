# Group Multi-User Participant Management

Fixed/Implemented in version: **0.241.034**

## Overview

Group multi-user conversations now support the same explicit participant-management workflow as personal multi-user conversations. Group chats can be created or converted into invite-managed conversations, participants can be added through the existing picker modal, and conversation-level admins can be managed from the participant list.

Dependencies:

- `application/single_app/collaboration_models.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/route_backend_collaboration.py`
- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/static/js/chat/chat-sidebar-conversations.js`

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.034"`.

## Technical Specifications

Architecture overview:

- New and converted group multi-user conversations use `scope.visibility_mode = 'invited_members'`.
- Invited users must already be current members of the underlying group.
- Legacy group collaborative conversations that still use `group_membership` remain readable through backward-compatible access checks.
- Legacy group single-user conversations can now be converted through `/api/collaboration/conversations/from-group/<conversation_id>/members`.

Configuration and file structure:

- Group participant state is tracked with the same collaboration user-state documents used by personal multi-user conversations.
- Group chat lists now serialize invite-managed membership state instead of assuming every group member has access.
- The participant picker uses current group members as candidate results for eligible group conversations.

## Usage Instructions

How to use:

- Create a new group multi-user conversation from a group context.
- Add one or more current group members through the participant picker.
- Promote accepted participants to conversation admins from the conversation details view when needed.
- Convert an existing `group-single-user` conversation by adding participants; the system migrates the conversation into collaborative storage and copies the message history.

Integration points:

- Backend invite, role, leave, delete, pin, and hide routes reuse the collaboration APIs in `route_backend_collaboration.py`.
- Frontend add-participant affordances are exposed from both the main conversation list and the sidebar.

## Testing and Validation

Test coverage:

- `functional_tests/test_group_collaboration_participant_management.py`
- `functional_tests/test_simplechat_group_multi_user_conversation.py`

Validation notes:

- Group invite validation rejects users who are not current group members.
- Invite-managed group conversations no longer notify or expose access to every group member by default.

Known limitations:

- Legacy `group_membership` collaborative conversations are still supported for backward compatibility and may coexist with newer invite-managed group conversations.