# Conversation Contents Drawer

## Overview

The conversation contents drawer provides a compact index of persisted user messages in the active chat. It also includes a used-documents mode so users can review the documents that have actually been cited in the conversation without opening the full details modal.

Implemented in version: **0.250.074**
Used documents mode added in version: **0.250.159**
Compact overflow-safe layout added in version: **0.250.171**
Source/cited distinction added in version: **0.250.215**

### Dependencies

- Existing authorized chat message loading
- Existing conversation metadata API (`/api/conversations/<conversation_id>/metadata`)
- Local Bootstrap 5 off-canvas runtime and Bootstrap Icons
- Existing current-user settings API

## Technical specifications

### Architecture

The contents mode is derived entirely from messages already loaded into the chat DOM. It does not add a conversation-index API or a second datastore. `chat-conversation-contents.js` observes persisted user-message elements, renders labels with `textContent`, and tracks the message nearest the current scroll position.

The documents mode uses the same conversation metadata source as the details modal but applies a different selector. Document tags remain the complete source inventory. New assistant messages persist exact cited document records, and conversation metadata maintains a compact `used_documents` aggregate for active responses. `chat-conversation-contents.js` renders exact used documents plus any explicit legacy fallback, while `chat-conversation-details.js` keeps the complete source list and marks exact matches with a **Cited** badge.

`functions_citation_tracking.py` matches final-response citation IDs without mutating full source arrays. Historical conversations without versioned tracking continue to use their existing document tags in the drawer; they are not falsely marked as exact citations in the details modal.

The application setting `enable_conversation_contents_drawer` is the authoritative global gate and defaults to `true`. The user setting `conversationContentsDrawerEnabled` also defaults to `true`; it is only effective while the admin gate is enabled.

### Interface behavior

- The chat header exposes an accessible contents button after at least one persisted user message is available.
- Desktop viewports reserve space for a persistent right-side drawer.
- Tablet and mobile viewports use a Bootstrap off-canvas drawer.
- Labels use the first meaningful plain-text line, normalize whitespace, and truncate to a maximum of 30 displayed characters including the ellipsis.
- Messages without usable text receive an ordered fallback such as `User message 3`.
- Selecting an entry scrolls and focuses the source message, applies a temporary highlight, and marks the entry as the current location.
- Mutation and scroll observers refresh entries after loads, sends, edits, timeline replacement, and conversation switching.
- The chat header exposes a separate used-documents icon once cited documents exist for the active conversation.
- Contents and Documents share the same right-side drawer. Opening either mode swaps the drawer content instead of creating side-by-side panes.
- After a streamed response completes, the drawer refreshes full conversation metadata and auto-opens Documents once per conversation when cited documents first appear.
- Document rows show title, classification, source filename when it differs from the title, cited page references, and workspace scope.
- The full conversation details modal lists every source document and marks only exact tracked use with a **Cited** badge.
- Retrieved-only documents remain available under each response's **Sources** disclosure but do not enter the strict Used documents list.
- Chunk counts and backend document IDs are intentionally omitted from the user-facing drawer.
- Both lists use compact typography and constrained grid/flex tracks so long labels and metadata truncate instead of creating horizontal scrolling.

### Files

- `application/single_app/functions_settings.py`
- `application/single_app/functions_conversation_contents.py`
- `application/single_app/functions_conversation_metadata.py`
- `application/single_app/functions_citation_tracking.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/route_backend_users.py`
- `application/single_app/route_frontend_chats.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/profile.html`
- `application/single_app/templates/chats.html`
- `application/single_app/static/js/chat/chat-conversation-details.js`
- `application/single_app/static/js/chat/chat-conversation-contents.js`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/static/css/chats.css`

## Usage

1. In **Admin Settings**, leave **Enable Conversation Contents Drawer** enabled or turn it off globally.
2. When globally enabled, users can open **Profile > Settings > Conversation Navigation** and choose whether the drawer appears for their account.
3. In Chat, select the list icon in the conversation header and choose a user-message label to jump to that point.
4. After a response cites workspace documents, select the document icon in the conversation header to view the cited-document list. If this is the first cited-document response in the conversation, the Documents mode opens automatically.

## Testing and validation

- `functional_tests/test_conversation_contents_drawer_settings.py` validates global and user defaults, persistence wiring, validation, and gate precedence.
- `functional_tests/test_document_action_conversation_scope_metadata.py` validates that source filenames survive conversation document-tag creation and refresh.
- `functional_tests/test_chat_cited_source_tracking.py` validates exact citation matching, source preservation, legacy compatibility, and active-attempt aggregation.
- `ui_tests/test_chat_conversation_contents_drawer.py` covers filtering, ordering, safe 30-character labels, fallback labels, compact cited-document rendering, documents-mode swapping, auto-open behavior, navigation, focus, live updates, conversation replacement, keyboard closing, and desktop/mobile horizontal-overflow measurements.
- `ui_tests/test_chat_scope_lock_and_conversation_details_escaping.py` verifies the full source inventory and safe exact Cited badge.
- The contents list is generated locally from authorized messages and inserts user-authored labels only through safe text APIs. The documents list also renders metadata through DOM APIs and `textContent`.

### Known limitations

- Contents mode indexes user messages only.
- New tracked responses include exact cited/used documents only; retrieved-only documents are intentionally excluded.
- Historical conversations retain the prior document list as a compatibility fallback because exact citation use was not persisted before version `0.250.215`.
- Search, grouping, generated summaries, assistant-message entries, and document filtering are not included.
- Only messages currently loaded into the active timeline can appear in the contents list.
