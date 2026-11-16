# Chat Context Picker

Choosing which documents a message is grounded in, and seeing that choice before
you send it.

**Implemented in version:** 0.261.089
**Updated in version:** 0.261.414 (`application/single_app/config.py`)
**Workspace sidebar implemented in version: 0.261.395.**
**Inline answers implemented in version:** 0.261.096
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

### Conversation-owned selections

Fixed/Implemented in version: **0.261.414**
(`application/single_app/config.py`).

Unsent source selections and uploads belong to the conversation where they were
chosen. Opening another chat displays its own selection or no selection, not the
sources from the previous chat. Returning in the same browser tab restores the
original pending selection, including its **Search all documents** choice.

Removing a source or sending the turn keeps that local selection empty on return;
old message metadata does not silently reattach it. These pending selections live
only in tab memory. They do not move stored files or add browser-refresh draft
persistence.

Restored sources use recorded filenames/titles. Missing details are resolved only
for the selected documents, through their authorized workspace scope. An unavailable
name is shown explicitly rather than presented as a GUID filename. A delayed response
cannot undo a removal or add a source to the chat opened afterward.

See [Conversation attachment isolation fix](../fixes/V2_CONVERSATION_ATTACHMENT_ISOLATION_FIX.md).

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

From **0.261.395**, the main composer's **Documents** panel has a workspace
directory on the left and available sources on the right. Personal, group and
eligible public workspaces appear individually, including public collections
not shown by a classic directory preference. In Orchestrate, open
**Manual controls → Documents** when those controls are available.

**Search all documents** searches every accessible workspace, subject to the
conversation's scope lock. It is not limited to your personal files or the active
workspace. New chats keep document search off until you enable it or select a
source. **Choose sources** lets you combine whole workspaces, individual documents
and tags from a particular workspace. Browsing a workspace does not select it.
**Turn off / clear** removes selections and disables document search.

Search matches workspace names, document titles, filenames and tags, not document
contents. Both columns narrow together: a matching document keeps its workspace
in the directory, and a matching workspace name includes that workspace's
documents. Editing the query resets browsing to all matching workspaces.
Clicking a workspace then narrows the right column without hiding the other
matching workspaces. Choices remain selected while you search, browse or load
more results.

On phones, the directory collapses above the results. Workspace and document
pages load independently, so the complete directory is not limited by the
smaller `#` suggestion menu. Loading failures show a retry action rather than
pretending there are no matches. Held documents remain unavailable for selection.

From **0.261.404**, source discovery reuses the existing Document Access Index
and its invalidation-aware cache rather than running grouped queries over the
source collections. If backfill or repair readiness cannot be established, or
an index query fails, only the affected personal, group, or public source
collection is read directly. A successful empty indexed result does not trigger
fallback. Both paths preserve the same matching and paging behavior; returned
documents are revalidated against live metadata before they can be selected.
See [Document sources DAI fallback fix](../fixes/V2_DOCUMENT_SOURCES_DAI_FALLBACK_FIX.md).

Old public-only conversations and **Chat with all public** launches become
**Choose sources** with the currently eligible public workspaces selected.
Those are explicit workspace choices, not a hidden public-only mode.
See [Public-only chat compatibility](V2_AGGREGATE_PUBLIC_CHAT.md).
Inline answers, restricted/shared editors and image-reference pickers retain
their existing selection controls.

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

The main personal-chat composer sends versioned `document_source_selection`:
`mode: "all"` with no source entries, or `mode: "selected"` with workspace,
document and tag entries. Every selected entry carries a personal, group or
public scope; group/public scopes also carry a workspace ID.

All selected entries form an **additive union**. Selecting a workspace includes
its currently available documents; selecting two tags includes documents with
either tag in its owning workspace. A tag never applies across other workspaces
just because its spelling is the same. Adding a document alongside a workspace
does not accidentally restrict the whole workspace to that document.

The server reauthorizes the intent before execution and on retrieval. It builds
per-index union filters inside existing access checks, separates cache identities
by admitted sources, and constrains direct document reads too. All-accessible
mode resolves current eligible workspaces again on retry/edit; selected workspace
sets do not silently acquire newly created workspaces.

Legacy/restricted editors continue using the following compatibility contract:

| Chip kind | Legacy request field |
| --- | --- |
| Document | `selected_document_ids` |
| Tag | `tags`, which becomes `tags_filter` |
| Workspace | `doc_scope` plus `active_group_ids` / `active_public_workspace_ids` |

**Legacy documents and tags are additive.** When a message carries both, the request
sends `document_filter_mode: "union"`. The server's default is `intersection`,
which requires a chosen document to *also* carry every chosen tag — so a document
chip beside an unrelated tag chip would match nothing at all.

**Legacy multiple tags are combined with AND.** This remains the behavior of
`build_tags_filter`; canonical main-composer source unions do not change it.

Any selected context makes the request use document search, including a tag or
workspace selected without individual documents. The message does not need an
inline `#` reference for those IDs, filters, and scopes to reach the server.

## Orchestration

Chips travel to the planner as seeds, and each kind lands differently:

| Chip kind | Effect on a plan |
| --- | --- |
| Document | Replaces the candidate probe only when all selected sources are individual documents. Mixed document/workspace/tag unions retain the scoped probe. |
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

### References in inline answers

When the planner asks a follow-up question, its answer editor supports the same `#`
references and selection/mention distinction as the main composer. References belong to
that answer, not to an unsent message in the main composer or another question.

For a file question, you can choose the planner's suggestions or supply a different
accessible file. An uploaded file becomes a reference only after the upload succeeds and
processing finishes. Workspace-backed uploads retain their document identity;
conversation-only attachments retain their conversation/file identity instead of being
treated as workspace documents.

The accepted references are carried through replanning and execution. An optional note
beside a choice can also have references, but a tag or workspace alone does not answer a
question that requires a particular file. Access is resolved again on the server, so a
visible chip is never itself proof of permission.

Covered by `functional_tests/test_v2_elicitation_answers.py` and
`ui_tests/test_v2_elicitation_composer.py`.

## Files

| File | Purpose |
| --- | --- |
| `lib/chatContext.ts` | The context item model, independent selection/mention attachments, and derived request fields |
| `lib/chatContextTokens.ts` | The `#[…]` grammar and reconciliation of inline mentions without losing independent selections |
| `lib/contextMentions.ts` | Cross-scope search for documents, tags and workspaces |
| `lib/chatContextHandoff.ts` | Reading and building the workspace hand-off |
| `lib/composerAttachmentDrafts.ts` | Per-conversation pending attachment/source ownership, retention, and recovery |
| `lib/documentTitles.ts` | Cached id-to-title resolution for plan steps |
| `components/chat/ContextChips.tsx` | The chip row and its condensing |
| `components/chat/ComposerHighlight.tsx` | Inline rendering of `#[…]` in the message box |
| `components/chat/ContextMenu.tsx` | The `#` menu |
| `components/chat/DocumentPickerPopover.tsx` | The Documents button's picker |
| `components/chat/WorkspaceDocumentPicker.tsx` | Main-composer synchronized directory/results and independent paging |
| `lib/documentSourceSelection.ts` | Canonical intent serialization and restoration |
| `application/single_app/document_source_selection.py` | Strict selection contract, union filters and direct-read scope |
| `application/single_app/functions_document_source_discovery.py` | Authorized complete metadata discovery and selection admission |

## Testing

| Test | Covers |
| --- | --- |
| `functional_tests/test_v2_chat_context_tokens.mjs` | Token grammar: parsing, insertion, removal, reconciliation, collisions |
| `functional_tests/test_v2_chat_context_request.ts` | Chip-to-request mapping, filter mode, scope resolution |
| `functional_tests/test_v2_chat_context_picker.py` | Hand-off destination, composer wiring, chat metadata parity; bundles and runs the TypeScript checks |
| `ui_tests/test_v2_chat_context_selection.py` | Real workspace, picker, inline mention, removal, and send workflows |
| `functional_tests/test_v2_document_source_selection.py` | Scoped unions, sharing, admission, locks, paging and metadata failure |
| `functional_tests/test_v2_document_source_discovery_imports.py` | Real DAI-first discovery, readiness/source fallback, Redis cache behavior, live screening and SQL compatibility in both import orders and Python modes |
| `functional_tests/test_v2_document_source_runtime.py` | Real retrieval filters/cache identities, SDK-shaped direct reads and replay |
| `ui_tests/test_v2_public_chat_scope.py` | Public migration, synchronized filtering, disabled state and responsive themed layouts |

See [V2 Context Selection Pills Fix](../fixes/V2_CONTEXT_SELECTION_PILLS_FIX.md)
for the behavior change introduced in 0.261.094.

## Known limitations

- Public workspace documents have no single-document endpoint, so resolving one
  by id alone falls back to scanning the visible list. References arriving from
  within the app carry their records directly and are unaffected.
- The inline rendering relies on a backdrop matching the message box's text
  metrics. If it cannot be drawn the box remains fully usable, just unstyled.
