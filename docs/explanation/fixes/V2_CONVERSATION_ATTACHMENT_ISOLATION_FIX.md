# V2 Conversation Attachment Isolation Fix

Fixed/Implemented in version: **0.261.414**

The application version is recorded in `application/single_app/config.py`.

## Issue

Switching quickly between V2 conversations could leave an image or file selected
in a conversation where the user had not attached it. The unexpected document
chip could show a GUID instead of its filename. Sending the next message could
then include that unintended document as a source.

The reproduced problem was client-side selection contamination, not a file being
moved between storage locations. This fix does not relocate or delete uploaded
files, rewrite old messages, or repair previously saved selections automatically.

## Root cause

The main composer kept one local draft while the selected conversation changed.
Its navigation effect removed upload chips and explicit image references but left
restored document, tag, and workspace context in that draft.

Restoration read `document_source_selection` from the last user message. When the
next conversation had no saved selection, it returned without replacing the old
context. When a selection did exist, it reconstructed each document with its ID
as `file_name`, producing the GUID label and tooltip.

Related asynchronous paths had incomplete ownership checks:

- Failed-send recovery could restore a sent draft into any empty composer belonging
  to the same account.
- Upload ownership distinguished conversation IDs but not successive unsaved
  **New chat** drafts, whose IDs are all null.
- Message and metadata reads checked the conversation ID without checking the
  navigation generation, so an old A response could overwrite a later visit to A
  after visiting B.
- A send handler could hold an older render's selection while navigation or a
  selection edit had already changed the authoritative draft.

## Technical changes

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/composerAttachmentDrafts.ts` | Retains attachment/source selections in tab memory by account, conversation kind, and conversation ID; unsaved drafts also use the navigation epoch. Tracks revisions, aliases upload/first-send-created IDs, and scopes recovery and deletion cleanup. |
| `application/v2_ui/src/components/chat/Composer.tsx` | Reads the active conversation's attachment slice immediately, restores historical sources only when no local selection exists, and checks current ownership/revision before sending. Resolves missing names without re-adding removed sources. |
| `application/v2_ui/src/components/chat/ComposerEditor.tsx` | Includes draft ownership in upload lifetimes. Interrupted transfers remain actionable only in their original draft; processing checks resume against the original reference. Validates the returned conversation before linking local previews. |
| `application/v2_ui/src/lib/documentSourceSelection.ts` | Uses matching conversation upload/document metadata for titles and filenames. Keeps IDs separate from display names and uses an explicit unavailable-details label when necessary. |
| `application/v2_ui/src/stores/chatStore.ts` | Guards relevant message/metadata results and errors with the navigation epoch, clears queued reference handoffs during navigation, binds created conversations to the originating attachment draft, and forgets drafts after successful removal. |
| `ui_tests/fixtures/orchestration/harness_entry.tsx` | Resets the retained attachment cache between isolated browser scenarios. |
| `ui_tests/test_v2_new_chat_reset.py` | Supplies the real composer's empty pending-credential and guided-question reads in the shared synthetic API fixture, reused by the new attachment suite. Strict unexpected-request checks remain enabled. |
| `application/single_app/config.py` | Updates `VERSION` to `0.261.414` after integrating the current V2 base. |

### Ownership and retention

Unsent upload selections, document/tag/workspace context, explicit references, and
document-search selection belong to their conversation. Switching to another
conversation displays that conversation's own selection or an empty selection.
Returning restores the original unsent selection.

A deliberately empty local selection is meaningful. Removing a chip or sending
a turn does not let an older saved message silently repopulate it on the next visit.
The retention is limited to the current browser tab's runtime; it adds no
localStorage or server-side draft persistence and does not redesign text, prompt,
or model preferences.

Unfinished byte transfers still cancel when leaving their editor. Returning to the
original conversation shows the interrupted selection with **Retry** and **Remove**.
If the server already returned a processing document reference, the original
draft can resume its status check without uploading another copy.

### Names, failures, and authorization

Restoration first uses the original upload/file message and the conversation's
merged document metadata. Missing names can be loaded through the existing
personal or explicitly scoped group/public document-detail readers. Only selected
documents are requested; labeling a chip does not enumerate every workspace.

Late lookups enrich only a still-selected matching source. They cannot select a
new document, undo removal, or update another conversation. If details cannot be
loaded, the chip says **Document details unavailable** and the notification
explains that the source can be removed and chosen again through **Documents**.
Search is never broadened as a fallback.

Names remain escaped React text. IDs and scopes retain their original identity,
and the server continues authorizing sources for each request. No route, permission,
capability toggle, or browser asset dependency is added.

## Validation

The original two browser reproductions failed before the application changes:
one retained an attachment in an unrelated conversation, and the other rendered
the document GUID as its filename.

`functional_tests/test_v2_chat_attachment_isolation.mjs` executes the real ownership,
revision, recovery, adoption, account-boundary, scope, and display-name helpers.
`ui_tests/test_v2_chat_attachment_isolation.py` exercises the real sidebar, composer,
stores, and request builders with intercepted APIs, including:

- Images and other files, with workspace-backed and conversation-only uploads.
- Leaving and returning, different saved selections, explicit removal, and Search all.
- Delayed message/metadata/name responses and A-to-B-to-A navigation.
- Processing and interrupted transfers, successive null-ID new drafts, and account changes.
- Failed-send recovery, including returning before rejection settles.
- Manual and Orchestrate request isolation and upload-created conversation adoption.
- Navigation and Send in the same event, plus long markup-like filenames as inert text.

The targeted browser suite passes **26 scenarios**. The executable helper checks
and TypeScript type check pass.

| Check | Result |
| --- | --- |
| `node .\functional_tests\test_v2_chat_attachment_isolation.mjs` | Passed. |
| `npm --prefix .\application\v2_ui run build` | Passed, including TypeScript compilation. The existing large-bundle advisory remains. |
| `python -m pytest .\ui_tests\test_v2_new_chat_reset.py .\ui_tests\test_v2_chat_attachment_isolation.py -q --tb=short` | 33 passed after completing the shared API fixture. |
| `python -m pytest .\ui_tests\test_v2_chat_attachment_isolation.py .\ui_tests\test_v2_new_chat_reset.py .\ui_tests\test_v2_guided_user_input.py -q --tb=short` | 40 passed after integrating the current V2 base at version `0.261.414` and its pending-question read contracts. |
| Context-picker and new-chat functional checks, excluding the confirmed obsolete source-literal assertion below | 16 passed, 1 deselected. |
| `python .\functional_tests\test_docs_app_surface_coverage.py` | 7/7 checks passed; the committed inventory is current. |
| `python .\functional_tests\test_docs_site_quality.py` | 6/6 documentation source checks passed. |
| Changed-line XSS sink validation | Passed for all 6 changed application files. |
| Whitespace validation | Passed. |

The broader affected-browser run passed all **133 test bodies**, including upload
status, clipboard, context selection, new-chat, image preview, inline-answer, and
image-reference coverage. Four teardown errors exposed a missing empty
pending-credential response in the existing shared synthetic API. That fixture was
completed without relaxing unexpected-request or console-error checks, and both
of its consuming suites were then re-run clean, as recorded above.

### Existing legacy harness limitations

An exploratory legacy functional run also found failures outside this fix:

- `functional_tests/test_v2_new_chat_reset.py` has an orchestration-map source-literal
  assertion that also fails against unchanged `HEAD` source.
- `functional_tests/test_v2_prompt_attachment_persistence.py` has closed backend
  namespaces missing `conversation_reference_resolution`,
  `stream_conversation_reference_resolution`, and `current_public_chat_scope`.
  That harness and the affected backend route modules are unchanged by this fix.

Those failures are not suppressed or repaired here. The directly affected context
and new-chat functional checks pass with the confirmed obsolete literal assertion
excluded. Real-browser checks cover the changed main-composer and shared-editor
behavior independently of those legacy backend harnesses.

## Before and after

| Before | After |
| --- | --- |
| A document selected in A could remain selected in B. | B displays only B's selection; returning to A restores A's pending selection. |
| A restored image/document chip could show a GUID as its filename. | It shows the recorded filename/title, or an explicit unavailable-details state. |
| A late failed send could refill a different empty composer. | Recovery is bound to the original draft and cannot overwrite a subsequent edit. |
| Repeated New chat clicks could retain one null-ID upload owner. | Each unsaved new draft has its own generation. |
| An older render could submit stale source selections. | Send requires the current owner and selection revision. |

## Related documentation

- [Chat context picker](../features/CHAT_CONTEXT_PICKER.md)
- [Upload documents in chat](../../guides/upload-documents-in-chat.md)
