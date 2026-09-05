# Chat Context Picker

Choosing which documents a message is grounded in, and seeing that choice before
you send it.

**Implemented in version:** 0.261.089
**Updated in version:** 0.261.094 (`application/single_app/config.py`)
**Interface:** V2 only. The classic interface is unchanged.
**Dependencies:** `enable_user_workspace` for personal documents,
`enable_group_workspaces` and `enable_public_workspaces` to reach those scopes.

## Overview

The V2 composer's **Documents** button used to be a plain on/off switch. Turning
it on meant "search my documents"; there was no way to say *which* documents,
and nothing on screen said what a message would actually look at. Choosing
documents in the workspace and pressing **Chat** navigated to the classic
interface.

This release replaces that with a context picker built around three ways of
naming something, all feeding one visible list:

- Type `#` in the message box and search.
- Open the **Documents** button's picker and tick items.
- Select documents or a tag in the workspace and press **Chat**.

## What a reference looks like

Every chosen reference becomes a **chip above the message box**, grouped by
workspace, with a remove button. References chosen from the **Documents** menu
or a workspace **Chat** action stay in that row without changing your message.
You can select a contract, for example, and simply type "Summarize the renewal
terms" without its name being added to the sentence.

Only choosing a suggestion through **`#`** inserts an inline reference such as
`#[Q3 Contract.pdf]`, highlighted inside the message box. This is useful when the
wording matters: "compare `#[Q3 Contract.pdf]` against `#[Q2 Contract.pdf]`".
The inline text remains part of the sent message.

Selection and inline mentions have separate lifetimes:

- Typing or editing your message does not remove independently selected chips.
- Deleting an inline mention removes its chip if the mention was its only source.
  If you also selected that item through a menu or workspace, its chip stays.
- Using `#` for an already selected item adds its inline reference without adding
  a second chip.
- Removing or deselecting a chip also removes any inline mentions associated
  with it. A chip that was never mentioned inline does not change your text.
- Typing `#[Something]` by hand does **not** create a chip or turn an independent
  selection into an inline mention. The name alone does not establish a reference.

These rules apply to documents, tags, and whole-workspace references. Context
selections clear with the draft when you send; they are carried in that turn's
request rather than left attached to the next message.

### Condensing

Chips render individually while there are five or fewer, showing the document
name with the rest of its detail on hover. Past that, each workspace collapses to
a single chip reading, for example, `Marketing · 7 documents`, which opens on
click for per-item removal. Workspace grouping containers only appear when more
than one workspace is involved.

## The `#` menu

Typing `#` at the start of a word opens a search over:

- **Documents**, across your personal workspace, every group you belong to, and
  every public workspace you have made visible — searched in parallel.
- **Tags**, from each scope's tag vocabulary.
- **Workspaces**, which add the whole workspace as context rather than pinning
  the documents in it at the moment you chose it.

The search is debounced, and each scope is requested independently: a group whose
index is briefly unavailable does not empty the menu of your personal documents.

`#` mid-word does not open the menu, so `C#` and `issue#42` are left alone, and a
`#` followed by a space is treated as prose.

## The Documents picker

Clicking **Documents** opens a panel upward over the composer containing:

- A search box, focused on open.
- **Search all my documents**, which is the original on/off behaviour: find
  whatever is most relevant rather than a fixed list.
- Checkbox lists grouped by workspace.

Ticking specific documents moves the request from relevance search to an explicit
selection. The button shows a count once anything is chosen. The selection
appears in the chip row only, leaving an empty or already-written message unchanged.

## Handing off from the workspace

Selecting documents in **My workspace → Documents** and pressing **Chat** now
opens the V2 composer with those documents already referenced. Tags have a chat
action of their own, which carries the tag as a filter rather than as the list of
documents that happened to carry it when you clicked. Both handoffs add chips
without inserting text, even if you start writing before the selection finishes
loading.

The link uses the same query vocabulary as the classic interface
(`search_documents`, `doc_scope`, `document_ids`, `tags`), so a link built by
either interface is readable by both. The parameters are cleared once applied, so
reloading does not silently re-apply a selection you have since cleared.

## How it reaches the server

| Chip kind | Request field |
| --- | --- |
| Document | `selected_document_ids` |
| Tag | `tags`, which becomes `tags_filter` |
| Workspace | `doc_scope` plus `active_group_ids` / `active_public_workspace_ids` |

Two behaviours are worth knowing about:

**Documents and tags are additive.** When a message carries both, the request
sends `document_filter_mode: "union"`. The server's default is `intersection`,
which requires a chosen document to *also* carry every chosen tag — so a document
chip beside an unrelated tag chip would match nothing at all.

**Multiple tags are combined with AND.** A document must carry every tag you
select. This is the server's existing behaviour (`build_tags_filter`) and is
unchanged here.

Any selected context makes the request use document search, including a tag or
workspace selected without individual documents. The message does not need an
inline `#` reference for those IDs, filters, and scopes to reach the server.

## Orchestration

Chips travel to the planner as seeds, and each kind lands differently:

| Chip kind | Effect on a plan |
| --- | --- |
| Document | Replaces the planner's candidate probe. You answered "which documents", so it works from your choice rather than guessing at one. |
| Tag | **Scopes** the probe rather than replacing it. A tag says which shelf; the probe still decides which documents on that shelf are worth naming. |
| Workspace | Bounds where the probe and every search step in the run may look. |

Your tags stay in force for the whole run, not just the first step. A step is free
to choose its own search query, but not to widen the shelf you narrowed to.

In the other direction, documents are listed on each step of the plan **by name**
rather than by id — deciding whether it picked the right contract is the reason
the plan is shown before it runs, and a bare uuid does not support that decision.
Documents you chose are marked as yours, so the ones actually worth checking are
the ones the planner introduced. Documents can be removed from a step, which
narrows the plan. Adding one is deliberately not offered inline: widening a plan
goes back through planning, so a request never skips the reasoning and permission
check that produced it.

Names are display only. The server labels a plan with the names the composer sends
and decides what you may read from the ids, so a renamed document is still exactly
the document it was.

See [Chat Orchestration](CHAT_ORCHESTRATION.md) for the planner side.

## Files

| File | Purpose |
| --- | --- |
| `lib/chatContext.ts` | The context item model, independent selection/mention attachments, and derived request fields |
| `lib/chatContextTokens.ts` | The `#[…]` grammar and reconciliation of inline mentions without losing independent selections |
| `lib/contextMentions.ts` | Cross-scope search for documents, tags and workspaces |
| `lib/chatContextHandoff.ts` | Reading and building the workspace hand-off |
| `lib/documentTitles.ts` | Cached id-to-title resolution for plan steps |
| `components/chat/ContextChips.tsx` | The chip row and its condensing |
| `components/chat/ComposerHighlight.tsx` | Inline rendering of `#[…]` in the message box |
| `components/chat/ContextMenu.tsx` | The `#` menu |
| `components/chat/DocumentPickerPopover.tsx` | The Documents button's picker |

## Testing

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_chat_context_tokens.mjs` | Token grammar: parsing, insertion, removal, reconciliation, collisions |
| `functional_tests/test_v2_chat_context_request.ts` | Chip-to-request mapping, filter mode, scope resolution |
| `functional_tests/test_v2_chat_context_picker.py` | Hand-off destination, composer wiring, chat metadata parity; bundles and runs the TypeScript checks |
| `ui_tests/test_v2_chat_context_selection.py` | Real workspace, picker, inline mention, removal, and send workflows |

See [V2 Context Selection Pills Fix](../fixes/V2_CONTEXT_SELECTION_PILLS_FIX.md)
for the behavior change introduced in 0.261.094.

## Known limitations

- Public workspace documents have no single-document endpoint, so resolving one
  by id alone falls back to scanning the visible list. References arriving from
  within the app carry their records directly and are unaffected.
- V2's group and public workspace *pages* are still placeholders. The picker
  reaches documents in those workspaces regardless, through their APIs.
- The inline rendering relies on a backdrop matching the message box's text
  metrics. If it cannot be drawn the box remains fully usable, just unstyled.
