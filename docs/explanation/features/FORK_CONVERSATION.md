# Fork Conversation

## Overview

**Implemented in version: 0.250.074**

Fork Conversation lets a user branch a personal conversation from a persisted
assistant response without changing the source conversation. The fork contains
the active message history from the beginning through the selected assistant
message, inclusive, and opens immediately as an independent conversation.

### Purpose

- Preserve the original conversation while exploring an alternate direction.
- Avoid manually recreating useful earlier context.
- Keep copied messages and dependent assistant artifacts independent from the
  source records.

### Dependencies

- Personal conversations stored in Azure Cosmos DB.
- The existing chat message action menu, Bootstrap modal and toast components,
  and conversation-list selection APIs.
- Existing authenticated personal-conversation ownership checks.

## Technical Specifications

### Architecture

1. The assistant message action is rendered only for a persisted, completed
   assistant message in an active personal conversation.
2. A Bootstrap confirmation modal submits the source conversation ID and
   selected message ID.
3. The backend authorizes ownership and resolves the authoritative persisted
   timeline. The client does not send message history or a timestamp boundary.
4. Active messages through the selected assistant response and supported
   dependent assistant artifact records are copied with new identifiers.
5. Conversation, message, artifact, reply, and thread references are remapped
   to the destination identities.
6. Blob-backed attachments and generated files are copied to destination blob
   paths so deleting either conversation cannot affect the other.
7. Destination messages are written before the conversation record is
   published. Failed writes trigger destination cleanup, preventing a partial
   fork from appearing in the conversation list.
8. The client adds and selects the returned conversation, then refreshes the
   conversation feed.

### API

`POST /api/conversations/<conversation_id>/fork`

Request:

```json
{
  "message_id": "persisted-assistant-message-id"
}
```

Successful response (`201`):

```json
{
  "conversation_id": "new-conversation-id",
  "title": "Fork of Source title",
  "message_count": 4
}
```

The endpoint can return:

- `400` for a missing message ID or a non-assistant fork point.
- `403` when the current user does not own the source conversation.
- `404` when the selected message is not on the active persisted timeline.
- `409` when the source is not an eligible personal conversation or changes
  during the operation.
- `500` when destination persistence fails.

### Security and authorization

- Source ownership is revalidated at the API boundary.
- Group, public, and collaborative conversation types are rejected.
- Stored context is eligible only when it remains personal to the same owner.
- The selected message must belong to the authorized source conversation and
  must be an active assistant message.
- Source conversation and message snapshots are checked again before writes to
  detect concurrent changes.
- The server queries the authoritative history and ignores client-supplied
  timelines or timestamps.

### Preserved and reset state

The fork preserves personal context, tags, strict mode, classification, scope
lock state, supported model/agent selections, message content, attachments,
citations, and assistant artifact metadata. It assigns new conversation,
message, artifact, and thread identifiers, and copies blob-backed message files
to independent destination paths.

Pin, hidden, unread, Cosmos system, streaming, and other destination lifecycle
state is reset. The source conversation and all later messages remain
unchanged.

### Files

- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/templates/chats.html`
- `functional_tests/test_conversation_fork.py`
- `ui_tests/test_chat_conversation_fork.py`

## Usage

1. Open a personal conversation containing a completed assistant response.
2. Open the response's **More actions** menu.
3. Select **Fork conversation**.
4. Confirm the operation.
5. Continue in the newly opened `Fork of <source title>` conversation.

The action is unavailable for streaming or transient assistant messages and for
group, public, or collaborative conversations.

## Testing and Validation

### Coverage

- Inclusive assistant boundary and exclusion of later or inactive messages.
- Stable ordering when timestamps match.
- Independent and remapped message, artifact, reply, conversation, and thread
  identifiers.
- Source immutability.
- Missing, non-assistant, inactive, foreign, and non-personal fork requests.
- Concurrent source changes and failed-write cleanup.
- Browser action visibility, confirmation and cancellation, failure feedback,
  duplicate-click prevention, list insertion, and fork activation.

### Performance

Forking reads the source partition twice to verify a stable snapshot, then
writes only records included through the selected boundary. The destination
conversation is not listed until all destination message writes complete.

### Limitations

- Only personal, single-user conversations are supported.
- Group, public, and collaborative conversations require separate resource and
  participant authorization designs.
- Cross-container atomic transactions are not available. The implementation
  uses publish-last behavior plus cleanup to provide an atomic user experience.
