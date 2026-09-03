# V2 Conversation Multi-Select

## Overview

The V2 chat sidebar lets you act on several conversations at once. Hovering a row reveals a
checkbox in its left gutter; ticking it starts a selection, and a bulk bar appears above the
list offering **pin/unpin**, **hide**, **export** and **delete**. Ctrl/Cmd+click adds one
conversation to the selection and Shift+click extends a range.

**Implemented in version: 0.261.056**

### Why it exists

Before this, the rail could select conversations only in order to export them. A permanent
**Select** button sat above the list, entering it swapped every row into a checkbox, and the
only bulk action offered was Export. Pinning, hiding and deleting stayed one row at a time
through the row's own menu — despite the server having had bulk routes for all three since
the classic interface shipped them.

Tidying a long conversation list therefore meant opening the same menu once per row.

### Dependencies

None added. The feature drives three routes that already existed and are already used by the
classic interface, and reuses the packages the V2 bundle already carries (`react-dom`,
`clsx`, `lucide-react`).

## Technical specifications

### Architecture

| Module | Responsibility |
|---|---|
| `application/v2_ui/src/lib/listSelection.ts` | The selection algebra — click, Ctrl/Cmd+click, Shift+click, select-all, prune, arrow-key move. Shared with the workspace documents explorer, which re-exports it from `documentExplorer.ts`. |
| `application/v2_ui/src/lib/conversationSelection.ts` | Conversation-specific rules: split a selection into personal and shared, choose delete-vs-leave per row, decide the adaptive pin action, and word the confirmation. |
| `application/v2_ui/src/stores/chatStore.ts` | Holds `selectedConversationIds` and `selectionAnchorId`; exposes `applyConversationSelection`, `selectAllConversations`, `clearConversationSelection` and the three bulk actions. |
| `application/v2_ui/src/components/chat/ConversationRail.tsx` | The rows, the gutter checkbox, the bulk bar and the confirmation. |
| `application/v2_ui/src/components/ui/Modal.tsx` | Dialog shell, rendered through a portal. |
| `application/v2_ui/src/components/ui/ConfirmDialog.tsx` | The gate in front of a delete. |

Both libraries are free of React so their rules can be exercised directly by
`functional_tests/test_v2_conversation_multiselect_logic.ts` rather than through a renderer.

### API endpoints

No new endpoints. The client posts to routes in `route_backend_conversations.py`:

| Route | Body | Used for |
|---|---|---|
| `POST /api/delete_multiple_conversations` | `{ conversation_ids }` | Bulk delete of personal conversations |
| `POST /api/conversations/bulk-pin` | `{ conversation_ids, action: "pin" \| "unpin" }` | Bulk pin / unpin |
| `POST /api/conversations/bulk-hide` | `{ conversation_ids, action: "hide" \| "unhide" }` | Bulk hide |

All three succeed partially rather than failing whole: an id the caller may not touch comes
back in `failed_ids` and the rest of the batch still applies. The client reads the counts
rather than trusting the `200`, reports `"3 of 5 conversations deleted"` when they differ,
and re-reads the feed so the list matches the server.

### Shared conversations

The three bulk routes read the personal conversations container and compare `user_id`, so a
shared (collaborative) conversation's id posted to them is silently reported in `failed_ids`
and nothing happens to it. The client therefore splits a selection before sending anything:

- **Personal ids** go to the bulk route in a single request.
- **Shared ids** go one at a time to `/api/collaboration/*`.

Removal of a shared conversation is additionally not one operation. Only an owner can destroy
one for everybody; anybody else leaves it and the thread continues without them. The server
reports which applies through `can_delete_conversation`, and the client sends `delete` or
`leave` accordingly. A missing flag is treated as `leave`, which is the safe direction.

`removalActionFor()` is the single rule that answers this. The row menu's label, the
confirmation's wording and the request itself all read it, and the confirmation passes its
decision through to `removeConversation` rather than letting the action be decided a second
time. That matters because the rail row and the loaded conversation are two independently
refreshed copies of the same viewer-scoped flags: a role change re-reads the membership but
does not reload the feed. Left to drift, a member promoted to owner mid-session could be
shown *"Leave"* and have `delete` posted on their behalf, destroying the thread for everyone.
The two copies are now also kept in step — opening a conversation and every membership
refresh write the fresh `can_delete_conversation` / `can_leave_conversation` back onto the
rail row.

Pinning has a matching wrinkle: the collaboration route *toggles* while the personal bulk
route *sets*, so shared conversations already in the target state are skipped rather than
posted to — sending to them would flip them the wrong way.

### Interaction rules

| Gesture | Result |
|---|---|
| Click a row | Opens that conversation and clears any selection |
| Ctrl+click / Cmd+click | Adds or removes that row from the selection |
| Shift+click | Extends the selection from the anchor to the clicked row |
| Click the gutter checkbox | Toggles that row; Shift held still extends a range |
| `Escape` | Clears the selection |
| `Ctrl+A` / `Cmd+A` inside the rail | Selects every loaded conversation |

An unmodified click always opens. Keeping that invariant is deliberate: a rail whose primary
action changes according to invisible state is worse than one that occasionally drops a
selection the user can see. Once anything is selected every row shows its checkbox, so the
state is visible before a plain click discards it.

**Pin is adaptive.** The button reads *Unpin* only when every selected conversation is
already pinned; any other mix pins. A toggle over a mixed selection would leave it inverted
rather than uniform, which is never what was asked for.

**Hide is one-way**, matching the single-row action: hidden conversations drop out of the
feed and the rail has no view that lists them, so there is nothing to unhide from.

**Rename and share are deliberately absent.** Renaming is inherently single-target, and
sharing is a per-conversation membership dialog.

### Layout

Each row reserves a fixed 16px left gutter. It holds the pin marker at rest and the checkbox
on hover, on focus, or whenever a selection exists — so revealing the checkbox moves nothing,
and pinned rows pay nothing for the gutter because the pin already stood there. A pinned row
whose gutter is showing a checkbox gains a small pin beside its title, so pin state stays
visible exactly when the user is deciding whether the bulk button should pin or unpin.

The bulk bar is drawn only while something is selected, in the row the removed **Select**
button used to occupy. At rest the rail is therefore one line shorter than before. Its
leading tri-state checkbox sits in the same column as the row checkboxes below it, so it
reads as their header, and Delete is separated by a hairline rule and coloured as a danger
action so it is not adjacent to the reversible ones under a fast pointer.

### Accessibility

- Checkboxes stay mounted when visually hidden and take `focus-visible:opacity-100`, so they
  remain in the tab order and reachable without a pointer.
- `pointer-coarse:opacity-100` shows checkboxes permanently on touch devices, which have no
  hover to reveal them with.
- An `aria-live="polite"` region announces the selected count.
- The select-all checkbox carries a real `indeterminate` state; without it a partial
  selection reads as "none selected".
- `Ctrl/Cmd+A` is bound to the rail container rather than the window, so it never takes
  select-all away from the composer or from the search box's own text.

### Deletion safety

Delete now confirms — both in bulk and from a single row's menu, which previously deleted
immediately with no undo.

The dialog is worded from what will actually happen rather than from the button that was
pressed. A shared conversation the user can only step out of is never described as being
deleted, and a mixed selection reports the two counts separately: *"3 conversations will be
permanently deleted. You will be removed from the other 1, which stay available to everyone
else."*

### Selection consistency

A selection that outlived the rows it named would let a bulk delete act on conversations the
user can no longer see. It is pruned in three places:

- `loadConversations` prunes against the freshly loaded page, which is what a search does.
- `removeConversation` and `toggleHidden` drop the removed id, and clear the range anchor if
  it pointed at that row.
- `removeConversationLocally` does the same for a row taken away by a server event — a shared
  conversation deleted by its owner, or one the user was removed from.
- Every bulk action resolves its ids against the loaded list before sending, so an id with no
  row is dropped rather than posted.

## Usage instructions

There is nothing to enable. In the chat sidebar:

1. Hover a conversation. A checkbox appears at its left edge.
2. Tick it. The bulk bar appears above the list showing how many are selected.
3. Add more with further checkboxes, Ctrl/Cmd+click, or Shift+click for a run of rows.
4. Choose **Pin**, **Hide**, **Export** or **Delete** from the bar.
5. Press `Escape`, click the `×`, or click any conversation to clear the selection.

On a touch device the checkboxes are always visible, since there is no hover to reveal them.

## Testing and validation

| Test | Covers |
|---|---|
| `functional_tests/test_v2_conversation_multiselect.py` | 17 checks: route reuse, request shapes, the personal/shared split, delete-vs-leave, that the confirmation and the request cannot disagree, batch resilience, selection pruning, the hover affordance, click semantics, the bulk bar, delete confirmation, the shared algebra, dialog portalling, and local-only browser assets. |
| `functional_tests/test_v2_conversation_multiselect_logic.ts` | 51 behavioural checks over `listSelection.ts` and `conversationSelection.ts`, run under node by the test above. |
| `functional_tests/test_v2_conversation_export.py` | Bulk export still reachable from the rail; updated for the new selection API. |
| `functional_tests/test_v2_documents_explorer.py` | Guards the extraction: the explorer's 67 logic checks still pass against the shared algebra. |

Run them with:

```powershell
python .\functional_tests\test_v2_conversation_multiselect.py
python .\functional_tests\test_v2_conversation_export.py
python .\functional_tests\test_v2_documents_explorer.py
```

The TypeScript checks are skipped when `application/v2_ui/node_modules` is absent.

### Known limitations

- Bulk actions apply to **loaded** conversations only. Select-all takes the rows currently
  paged in, not everything on the server; this is deliberate, so an action never reaches
  something the user has not seen.
- Hiding cannot be undone from V2, because the rail has no hidden-conversation view.
- A bulk selection spanning many shared conversations issues one request per conversation,
  since the collaboration routes have no bulk equivalent.

## Cross-references

- Feature: `docs/explanation/features/` — conversation export, which the bulk Export button
  opens.
- Configuration: `application/single_app/config.py` (`VERSION`).
- Backend routes: `application/single_app/route_backend_conversations.py`.
