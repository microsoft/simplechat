# Conversation Contents Drawer

## Overview

The conversation contents drawer provides a compact index of persisted user messages in the active chat. It helps users navigate long conversations without manually scrolling through the transcript.

Implemented in version: **0.250.074**

### Dependencies

- Existing authorized chat message loading
- Local Bootstrap 5 off-canvas runtime and Bootstrap Icons
- Existing current-user settings API

## Technical specifications

### Architecture

The feature is derived entirely from messages already loaded into the chat DOM. It does not add a conversation-index API or a second datastore. `chat-conversation-contents.js` observes persisted user-message elements, renders labels with `textContent`, and tracks the message nearest the current scroll position.

The application setting `enable_conversation_contents_drawer` is the authoritative global gate and defaults to `true`. The user setting `conversationContentsDrawerEnabled` also defaults to `true`; it is only effective while the admin gate is enabled.

### Interface behavior

- The chat header exposes an accessible contents button after at least one persisted user message is available.
- Desktop viewports reserve space for a persistent right-side drawer.
- Tablet and mobile viewports use a Bootstrap off-canvas drawer.
- Labels use the first meaningful plain-text line, normalize whitespace, and truncate at 72 characters.
- Messages without usable text receive an ordered fallback such as `User message 3`.
- Selecting an entry scrolls and focuses the source message, applies a temporary highlight, and marks the entry as the current location.
- Mutation and scroll observers refresh entries after loads, sends, edits, timeline replacement, and conversation switching.

### Files

- `application/single_app/functions_settings.py`
- `application/single_app/functions_conversation_contents.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/route_backend_users.py`
- `application/single_app/route_frontend_chats.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/profile.html`
- `application/single_app/templates/chats.html`
- `application/single_app/static/js/chat/chat-conversation-contents.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/css/chats.css`

## Usage

1. In **Admin Settings**, leave **Enable Conversation Contents Drawer** enabled or turn it off globally.
2. When globally enabled, users can open **Profile > Settings > Conversation Navigation** and choose whether the drawer appears for their account.
3. In Chat, select the list icon in the conversation header and choose a user-message label to jump to that point.

## Testing and validation

- `functional_tests/test_conversation_contents_drawer_settings.py` validates global and user defaults, persistence wiring, validation, and gate precedence.
- `ui_tests/test_chat_conversation_contents_drawer.py` covers filtering, ordering, safe and truncated labels, fallback labels, navigation, focus, live updates, conversation replacement, keyboard closing, and desktop/mobile layouts.
- The contents list is generated locally from authorized messages and inserts user-authored labels only through safe text APIs.

### Known limitations

- The initial implementation indexes user messages only.
- Search, grouping, generated summaries, and assistant-message entries are not included.
- Only messages currently loaded into the active timeline can appear in the contents list.
