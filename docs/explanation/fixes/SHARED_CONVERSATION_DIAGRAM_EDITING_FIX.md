# Shared Conversation Diagram Editing Fix

## Issue

Editing a diagram in a **shared conversation** failed. The editor opened and rendered normally,
but every operation that tried to store something — changing the flow direction or spacing,
saving an edited source, or asking the AI to change the diagram — returned:

> Conversation not found

Personal conversations were unaffected, so the failure only appeared once a conversation had
been shared.

**Fixed in version: 0.261.044**
(Inline diagram editing was introduced in 0.261.043.)

## Root cause

A shared conversation is not a personal conversation with extra fields. It is stored in a
different set of Cosmos containers and served by a different family of routes:

| | Personal | Shared |
|---|---|---|
| Conversation | `cosmos_conversations_container` | `cosmos_collaboration_conversations_container` |
| Messages | `cosmos_messages_container` | `cosmos_collaboration_messages_container` |
| Routes | `/api/...` | `/api/collaboration/...` |

The three block-revision routes added in 0.261.043 lived only in `route_backend_chats.py` and
authorized through `_authorize_personal_conversation_access`, which reads the *personal*
conversation container. Given a shared conversation's id, that read finds nothing, raises
`LookupError`, and the route answers `404 Conversation not found`.

The editor itself worked because reading is a different path: the V2 client loads a shared
thread's messages through `fetchCollaborationMessages`, so the diagram, its stored revisions and
the whole editor panel rendered from data that had already been fetched correctly. Only the
writes were pointed at the wrong endpoint family.

`chatStore` already tracks which family a conversation belongs to, in `activeConversationKind`,
and every other conversation-scoped action already branches on it. The block-revision actions
were the exception.

### The second, quieter half of the bug

Fixing only the routing would have produced a subtler wrong result.

A shared conversation's messages are **mirrors**. Each one carries `source_conversation_id` and
`source_message_id` pointing at a message in the personal container, and:

- the shared AI request is delegated to the personal chat path using the **source** conversation
  id (`_build_collaboration_stream_request_payload`),
- the conversation export reads the source message,
- the conversation's owner reads the source conversation directly.

So an edit written only to the shared mirror would be visible to whoever was reading the shared
thread, while the model, the export and the owner all continued to see the original diagram.

This is the same problem masking already had, and it is solved the same way — see
`_sync_collaboration_mask_metadata_to_source`, which the new
`_sync_collaboration_block_revisions_to_source` sits directly beside.

## Files modified

| File | Change |
|---|---|
| `application/single_app/route_backend_collaboration.py` | Three shared block-revision routes, the source-sync helper, the shared save/broadcast helper, and a shared originating-request lookup |
| `application/v2_ui/src/lib/collaboration.ts` | Typed wrappers for the three shared routes |
| `application/v2_ui/src/stores/chatStore.ts` | The three actions branch on conversation kind; handler for the new broadcast event |
| `application/v2_ui/src/lib/collaborationEvents.ts` | `collaboration.message.block_revised` event plumbing |
| `application/single_app/config.py` | Version bump |

No change was needed to `functions_message_block_revisions.py`. Both route families import the
same storage rules, so the caps, pruning, fingerprint checks and fence-breakout refusal cannot
drift between personal and shared conversations.

## Code changes

### Authorization

The shared routes use `assert_user_can_participate_in_collaboration_conversation` rather than an
ownership comparison. A participant is not the owner of the underlying source conversation and
would fail a plain ownership check even though they are a legitimate member — which is precisely
why the personal helper rejected them.

Participation rather than mere visibility is required, matching the mask route: editing a
diagram changes what everyone in the thread sees, so it is not something a pending invitee
should be able to do.

### Endpoint selection

The client picks the endpoint family from the conversation's kind rather than trying one and
falling back:

```ts
const shared = isCollaborativeConversation(get(), conversationId);
const result = shared
    ? await addCollaborationBlockRevision(conversationId, messageId, body)
    : await addMessageBlockRevisionApi(messageId, { conversation_id: conversationId, ...body });
```

The request and response shapes of the two families are deliberately identical, so the same body
is sent either way and only the call site differs.

### Write-through and broadcast

`_save_collaboration_block_revisions` performs the three steps that must happen together — write
the shared message, mirror the revisions to the source message, publish the event — so no route
can accidentally do one without the others.

The `collaboration.message.block_revised` event carries only the revision map, not the whole
message. Nothing else about the message changed, and replacing the whole message would clobber
whatever local state the reader's copy already holds.

## Testing

`functional_tests/test_v2_diagram_editor.py` grew four checks:

| Check | Guards against |
|---|---|
| `test_a_shared_conversation_can_be_edited` | The original bug: shared routes exist, authorize by participation, and read/write the collaboration containers |
| `test_a_shared_edit_reaches_the_model` | The quieter half: every shared write path mirrors to the source, and the delegation that relies on is still in place |
| `test_the_client_picks_the_right_endpoint_family` | The client branching on conversation kind for all three actions |
| `test_a_shared_edit_is_broadcast_to_the_other_readers` | The event reaching the other participants |

The endpoint-family check bounds each action's text at the start of the next action rather than
using a fixed window. An earlier draft used a generous fixed window that overlapped the
following action, which meant a branch deleted from one action was satisfied by its neighbour's.
That was verified by deliberately removing the branch from `restoreBlockRevision` alone and
confirming the test now fails on exactly that action.

## Validation

```
test_v2_diagram_editor.py            18/18   (14 before, plus 4 shared-conversation checks)
test_message_block_revisions.py      18/18
test_block_revision_assist.py          8/8
test_v2_rich_rendering.py            13/13
route_tests/ (all three)              12/12
npx tsc -b --noEmit                  clean
npm run build                        succeeds
```

## Before and after

| | Before | After |
|---|---|---|
| Editor opens in a shared conversation | Yes | Yes |
| Direction / spacing change | `Conversation not found` | Applied and stored |
| Source edit saved | `Conversation not found` | Applied and stored |
| Ask AI | `Conversation not found` | Applied and stored |
| Model sees the edited diagram | n/a | Yes, via the source mirror |
| Export carries the edited diagram | n/a | Yes, via the source mirror |
| Other participants see the edit | n/a | Live, without reloading |
