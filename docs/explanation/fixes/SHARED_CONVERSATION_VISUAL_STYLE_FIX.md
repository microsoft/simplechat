# Shared Conversation Visual Style Fix

## Issue

In the V2 chat, clicking a colour on a Mermaid diagram or a SimpleChart chart inside a **shared
conversation** changed the block on screen and then reported:

> That change could not be saved.

The browser console showed a 404:

```
POST /api/message/<conversation_id>_<hex>/visual-style   404 (Not Found)
```

The same session logged a second 404 when a shared conversation was opened from a link:

```
GET /api/conversations/<conversation_id>/metadata        404 (Not Found)
```

Both appeared only for shared conversations. In a personal conversation, recolouring and
resizing worked as documented.

**Fixed in version: 0.261.039**

## Root cause

### The failed save

`POST /api/message/<message_id>/visual-style` in `route_backend_chats.py` authorizes the write by
resolving the conversation through `_authorize_personal_conversation_access()`, which reads the
personal conversation container:

```python
conversation_item = cosmos_conversations_container.read_item(
    item=conversation_id, partition_key=conversation_id)
# CosmosResourceNotFoundError -> LookupError -> 404 'Conversation not found'
```

A shared conversation is stored in `cosmos_collaboration_conversations_container`, and its
messages in `cosmos_collaboration_messages_container`, so that read can never succeed for one.
The request was therefore refused before it reached the message at all.

No collaboration counterpart to the endpoint existed. On the client,
`chatStore.applyVisualStyle` called the personal endpoint unconditionally, even though every
other conversation-scoped write in the same store already branches on conversation kind —
renaming, deleting, pinning, hiding, marking read, deleting a message, and masking a message all
do. Visual styling was the one write that was never given its shared-conversation path.

The feature documentation recorded this as a known limitation, but the interface offered the
control and then reported a failure, which reads as a bug rather than an unsupported case.

### The metadata 404

That one was deliberate. `resolveConversationKind()` in `chatStore.ts` needs to know which family
of endpoints a conversation belongs to before it can load it, and a conversation reached from a
link is not in the loaded conversation list, so there is no row to read a kind from. It called
the personal metadata endpoint and treated a 404 as "then it must be a shared one", falling back
to the collaboration endpoint.

The logic was correct, but the browser logs a failed request regardless of how the client handles
it, so every link to a shared conversation produced a console error.

## Changes

### Files modified

| File | Change |
|---|---|
| `application/single_app/route_backend_collaboration.py` | New `POST /api/collaboration/conversations/<conversation_id>/messages/<message_id>/visual-style` |
| `application/single_app/route_backend_conversations.py` | New `GET /api/conversations/<conversation_id>/kind` |
| `application/v2_ui/src/lib/collaboration.ts` | `setCollaborationMessageVisualStyle()` wrapper |
| `application/v2_ui/src/lib/endpoints.ts` | `fetchConversationKind()` wrapper and the `ConversationKind` wire type |
| `application/v2_ui/src/lib/collaborationEvents.ts` | `collaboration.message.visual_style_updated` handler |
| `application/v2_ui/src/lib/blockVisualStyle.ts` | Captures the conversation kind with the queued change |
| `application/v2_ui/src/stores/chatStore.ts` | Branches `applyVisualStyle` on kind, single-request kind resolution, live style updates |
| `application/single_app/config.py` | Version bump to `0.261.039` |

### The shared endpoint

Modelled on the existing `mask_collaboration_message_api`, which solves the same problem for the
same kind of per-message write:

- Guarded by `_require_collaboration_feature_enabled()` and the standard
  `@swagger_route(security=get_auth_security())`, `@login_required`, `@user_required` decorators.
- Authorized with `assert_user_can_participate_in_collaboration_conversation()` rather than the
  view-level check. The stored choice is on the shared message and therefore seen by every
  participant, so a read-only viewer must not be able to change it.
- Refuses a message whose `conversation_id` disagrees with the one in the URL, so a message id
  is not usable as a capability.
- Reuses `apply_visual_style()` from `functions_message_visual_styles.py` unchanged. Both routes
  validate through the same code, so the colour, palette, index, height and bounds rules cannot
  drift apart between personal and shared conversations. This matters because the stored values
  end up in inline `style` attributes and in Mermaid's theme configuration in a browser.
- Writes to `cosmos_collaboration_messages_container` and publishes
  `collaboration.message.visual_style_updated` on the conversation's event stream.

The styles are deliberately **not** synced back to the hidden source message the way
`_sync_collaboration_mask_metadata_to_source` syncs a mask. A mask changes what is exported and
what the model is later shown; colours change neither, and the owner reads the thread through the
shared conversation anyway.

### The kind endpoint

`GET /api/conversations/<conversation_id>/kind` answers the question the probe was asking, in one
request and without a failure:

- A personal conversation owned by the caller answers `{"kind": "personal"}`.
- Otherwise a shared conversation the caller may view answers `{"kind": "collaborative"}` plus
  the serialized conversation, which is the document the participants panel and the composer need
  next — so the single request replaces what used to be two.
- A conversation the caller may not see is reported as absent rather than forbidden. The two are
  indistinguishable to someone who should not know it exists.
- With collaborative conversations disabled by configuration, a conversation is never named as
  shared, because the collaboration endpoints would refuse everything the client then tried.

### Client changes

`applyVisualStyle` now selects the endpoint from the conversation kind. The kind is captured in
`blockVisualStyle.ts` at the moment the change is made, alongside the conversation id and for the
same reason already documented there: writes are debounced and a pending change is flushed when
the block unmounts, by which point the reader may have moved to a conversation of the other kind.

The 403 message was also wrong for a shared conversation — it read "You can only restyle blocks
in your own conversations" — and now says what is actually required.

`onMessageVisualStyleUpdated` folds a broadcast change into the open thread. It takes only the
styles from the event rather than replacing the whole message, and raises no notification: a
colour change is cosmetic, and a drag on somebody else's screen would announce itself repeatedly
for something the reader can already see happening.

## Testing

`functional_tests/test_v2_collaboration_visual_style_fix.py` — 23 checks, of which ten exercise
the two new routes against in-memory containers rather than asserting on source text:

- A shared block is restyled, the colours land in the collaboration container, metadata the
  collaboration serializer depends on survives the write, and the change is broadcast once with
  the styles attached.
- Size and colours change independently: a recolour that omits `height` keeps the stored height,
  an explicit `null` clears it, and clearing the colours leaves the block following the reader's
  default.
- A shared block refuses exactly what a personal one refuses — non-hex backgrounds, unknown
  palettes, unknown block kinds, out-of-range indexes, non-finite heights — and a refused request
  writes nothing.
- Restyling without write access is 403; a message from another conversation, or one that does
  not exist, is 404. A stored document that is not a collaborative conversation reads as 404
  rather than surfacing the `LookupError` behind it as a 500.
- The kind endpoint answers for both families, reports inaccessible conversations as absent, and
  never names a conversation as shared while collaboration is switched off.

The remaining checks cover the wiring that cannot be exercised in-process: that the client
branches on kind, that the conversation kind is captured with the queued change, that the
deep-link probe no longer depends on a 404, that the broadcast handler updates the thread without
a toast, and that the personal endpoint is unchanged.

### Results

```
python .\functional_tests\test_v2_collaboration_visual_style_fix.py    23/23 passed
python .\functional_tests\test_v2_visual_style_controls.py             16/16 passed
python .\functional_tests\test_v2_conversation_deep_link.py             8/8  passed
python .\functional_tests\test_v2_shared_conversations.py              14/14 passed
python .\functional_tests\route_tests\...                              12/12 passed
npx tsc -b --noEmit  (application/v2_ui)                               clean
npm run build        (application/v2_ui)                               clean
```

## Before and after

| | Before | After |
|---|---|---|
| Recolour a chart in a personal conversation | Saved | Saved, unchanged |
| Recolour a chart in a shared conversation | 404, "That change could not be saved" | Saved on the shared message |
| Other participants' view of that chart | Never changed | Updates live |
| Who may restyle a shared block | Nobody | Participants with write access |
| Open a link to a shared conversation | Worked, logged a 404 | Works, one successful request |
