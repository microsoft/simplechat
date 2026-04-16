# Collaborative Conversation UI Upgrade (v0.241.008)

Fixed and implemented in version: **0.241.008**

## Overview

This document describes the first `/chats` UI integration for collaborative conversations.
The feature keeps personal and group conversations single-user by default, then upgrades personal conversations into shared chats when participants are added.

This slice focuses on the user-visible entry points the chat page needs before explicit shared AI workflows are layered on top.

## Dependencies

- Collaborative conversation foundation routes and Cosmos containers
- Existing `/chats` page layout, sidebar loaders, and conversation details modal
- Local user settings records used for collaborator suggestions
- Existing Bootstrap modal infrastructure on the chat page

## Technical Specifications

### Architecture Overview

The chat UI now treats collaborative conversations as a first-class conversation kind within the existing personal chat experience.

The integration adds:

- a collaboration-aware conversation list merge in the main rail and sidebar
- a dedicated frontend collaboration module for message loading, event streaming, typing state, and participant management
- personal conversation upgrade support that converts a legacy personal conversation into a collaborative one when members are added

### API Endpoints

The UI integration relies on the existing collaborative conversation APIs and adds two new browser-facing helpers:

- `POST /api/collaboration/conversations/from-personal/<conversation_id>/members`
- `GET /api/user/collaboration-suggestions`

The first endpoint upgrades a legacy personal conversation and invites the selected participant in one request.
The second endpoint returns suggestions from recent collaborator settings and locally stored user records instead of live Entra lookups.

### UI Entry Points

Participant management is now available from:

- the conversation details modal
- the left-hand conversation actions in both chat conversation lists
- the `@` mention workflow in the chat composer

All participant adds use a confirmation modal before the invite or conversion request is sent.

### File Structure

Key files updated in this slice:

- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/static/js/chat/chat-conversations.js`
- `application/single_app/static/js/chat/chat-sidebar-conversations.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-conversation-details.js`
- `application/single_app/templates/chats.html`
- `application/single_app/static/css/chats.css`

## Usage Instructions

Users can continue creating and using personal conversations exactly as before.
When a participant is added to a personal conversation, SimpleChat upgrades that conversation into a collaborative conversation and keeps the user in the shared chat flow.

Collaborator suggestions are intentionally limited to recent collaborators and local user records that already exist in SimpleChat.
This keeps the feature fast and avoids adding a live directory dependency to the compose experience.

## Testing and Validation

Related tests:

- `functional_tests/test_collaboration_legacy_message_conversion.py`
- `ui_tests/test_chat_collaboration_ui_scaffolding.py`

Validated behaviors in this slice:

- legacy personal messages can be converted into collaboration-safe transcript records
- uploaded files and assistant messages preserve the expected sender semantics during conversion
- the chats page loads the collaboration modals and mention container without collaboration-specific browser errors

## Known Limitations

- explicit shared AI invocation is still a later slice
- full end-to-end collaborative UI workflows require authenticated UI environment setup and seeded conversation data
- group collaborative conversation management is not yet expanded to a distinct shared group workflow beyond the current shared-chat scaffolding