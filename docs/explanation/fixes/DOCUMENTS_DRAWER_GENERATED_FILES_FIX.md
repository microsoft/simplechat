# Documents Drawer Generated Files Fix

**Version: 0.261.302**

Fixed in version: **0.261.302**, recorded in
`application/single_app/config.py`.

This affects the React V2 branch (`paullizer-react-v2-ui`) and deployments built
from it.

## Issue

In V2 chat, a user asked for a CSV file of every state and its capital. Orchestrate
rendered `us_states_and_capitals.csv`, and the reply showed a **Files** card marked
**Completed** with **Download CSV**. The conversation drawer's **Documents** tab still
said "No documents used yet".

Images a conversation produced did appear in the drawer. The CSV did not, and neither
did any other file a reply produced: a Word, PDF or PowerPoint file a plan rendered,
an export, or an Analyze summary.

## Root cause

The **Documents** tab had three sources:

- **Used in answers**: the document citation aggregates stored on the conversation
  (`used_documents`, `legacy_used_documents` and `linked_workspace_documents`).
- **Media**: every image, video and audio clip the thread shows. This is why images
  appeared.
- **Generated**: added in 0.261.255 for shared conversations only. It listed the
  documents agents created with the SimpleChat upload actions (Markdown, Word and
  PowerPoint), which `/api/collaboration/conversations/<id>/generated-documents` reads
  from the actions' results. `useGeneratedDocuments` was turned off for any other
  conversation.

A file a reply produces is recorded on the reply, not on the conversation. A plan's
files are in `metadata.orchestration.outputs`, with the committed download records in
`generated_artifacts`. Exports, Analyze summaries, comparison workbooks and research
ledgers are in `generated_tabular_outputs` and `generated_analysis_artifacts`. Only the
cards in the thread read these, so nothing passed them to the drawer. In a personal
conversation, a document an agent created with a SimpleChat upload action was not
listed anywhere.

## Changes

### Every file a reply produced is listed, in any conversation

`lib/conversationGeneratedFiles.ts` reads the loaded messages with the same readers the
thread's file cards use: `readGeneratedArtifacts`, `normalizeOrchestrationAttempt`
with `committedOrchestrationArtifact`, and the live plan run state the cards poll. The
drawer therefore lists exactly what the thread shows:

- A fully masked reply and a reply a workflow reply replaced list nothing.
- A plan's files are hidden while any part of their reply is masked, as their cards are.
- Downloads under saved Analyze findings follow those findings' availability.
- A plan's committed file is listed once, as its file card, not again as a loose record.
- A file several replies show, such as one a retry reused, is listed once, under the
  first reply that showed it.

Every format a plan can render is covered: CSV, Excel, Word, PDF, PowerPoint, Markdown,
text, JSON, XML and YAML, plus any format an export or analysis file declares.

A file that is not ready is listed with its status rather than left out, so it is not
mistaken for one that was never made. Only a ready file offers **Download**.

| Status shown | When |
| --- | --- |
| None (ready) | The file can be downloaded. |
| Waiting, Rendering, Automatic retry scheduled | A plan's file is still being produced. |
| Generating | A background export is still running. |
| Failed, Cancelled | The file was not produced. |
| Awaiting approval, Declined, Expired | A file generated in a shared conversation is held for the owner's approval, or was refused. |
| Unavailable, Download details unavailable, Status unavailable | Current access to the file cannot be confirmed, or its download record or state has not arrived. |

Downloads use the routes the cards already use: `/api/chat_artifacts/download`, with
its approval and publication checks, or `/api/workspace_documents/download` for a copy
saved to the personal workspace.

### A background export that finishes updates the drawer

A background export's card polls the run and replaces itself with the files the run
produced. It now also records the run's status and those files in
`stores/generatedExportRunStore.ts`, which the drawer reads. Without this, the drawer
would list a finished export as still generating until the conversation was reopened.

### Documents agents create are listed in personal conversations

Two routes in `route_backend_conversations.py` give personal conversations what shared
conversations already had:

- `GET /api/conversations/<conversation_id>/generated-documents`
- `GET /api/conversations/<conversation_id>/generated-documents/<document_id>/download`

Both require sign-in and a user role, and call
`_authorize_personal_conversation_read` before anything is read, so only the
conversation's owner gets an answer. `_list_personal_conversation_generated_documents`
then reads the messages the thread shows, filtered as `/api/get_messages` filters them:
deleted messages, the assistant artifact store, hidden generated chat files and replaced
thread attempts are left out. A citation stored in compact form is rebuilt from its
artifact record first, because the created document's id is in the full tool result.
`collect_generated_documents`, the shared conversation's reader, does the rest, so both
kinds of conversation list documents by the same rules, and a masked message's
documents stay hidden.

The list carries no group ids. The download serves only a document this conversation
produced, through `authorize_generated_document_download` and
`build_document_download_response`, so the workspace's own download rules apply: the
document's owner with personal downloads allowed, or a document-managing group role with
downloads allowed for that group. Failures return fixed messages, and a content
screening refusal returns its public message.

`lib/generatedDocuments.ts` picks the personal or shared route by the conversation's
kind, so a list read from one family of routes is never downloaded through the other.
The list is requested only when the thread can hold such a document: a reply whose tool
calls include an upload action, or an agent's reply that finished in this tab, whose
tool calls are not loaded until the conversation is read again.

It is read again whenever the replies the thread shows change: a reply arrives or is
deleted, another attempt of an answer is shown, or a reply is masked or unmasked. A
reply count would miss the last two, because they leave the count unchanged. Only
documents whose reply the thread shows, and does not fully mask, are listed or counted,
so a document from an attempt that is no longer shown never lingers with a **Show in
conversation** that leads nowhere. A shared conversation's list is read only once the
reader has joined: while an invitation can still be accepted the server would refuse
it, so it is not requested, and joining reads it straight away. A refused or failed
read is not kept, so the drawer asks again the next time it opens, and a conversation
opened again after another one is read afresh.

### One Generated section, counted by the Documents button

The drawer's **Generated** section merges both kinds into one list in conversation
order. Each row shows an icon for its kind of file, its name, its type with rows and
size (for example "CSV file · 50 rows · 1006 B"), and a status when it is not ready.
**Preview** opens Markdown and any file that carries a preview, **Download** saves a
ready file, and **Show in conversation** scrolls to the reply that produced it.

The badge on the header's **Documents** button counts the documents answers used plus
every file and document the conversation produced, each once by document id. Media is
not counted. `stores/generatedDocumentsStore.ts` holds one copy of the agent-document
list for the badge and the drawer, so opening the drawer does not request it again.

The empty state now reads "No documents yet" and "Documents used or created while
answering will be listed here."

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/route_backend_conversations.py` | Personal generated-documents list and download routes, and the visible-message reader behind them. |
| `application/single_app/functions_collaboration_generated_documents.py` | Docstring covers personal conversations. |
| `application/single_app/config.py` | Version `0.261.302`. |
| `application/v2_ui/src/lib/conversationGeneratedFiles.ts` | New. Collects every file the replies produced, merges agent documents, gates the request and counts the badge. |
| `application/v2_ui/src/lib/generatedDocuments.ts` | New. Reads and downloads agent documents through the personal or shared route. |
| `application/v2_ui/src/lib/collaboration.ts` | The shared conversation's file fetch moved to `generatedDocuments.ts`. |
| `application/v2_ui/src/stores/generatedDocumentsStore.ts` | New. The shared agent-document list and the generated-files hook. |
| `application/v2_ui/src/stores/generatedExportRunStore.ts` | New. Background export progress shared with the drawer. |
| `application/v2_ui/src/components/chat/DrawerAssets.tsx` | One Generated section for both kinds of file. |
| `application/v2_ui/src/components/chat/ConversationDrawer.tsx` | Uses the new section and empty-state text. |
| `application/v2_ui/src/components/chat/GeneratedArtifactCard.tsx` | Shares its preview dialog and records background export progress. |
| `application/v2_ui/src/pages/ChatPage.tsx` | The Documents badge counts generated files. |
| `docs/reference/chat-controls.md` | New Documents drawer section. |
| `docs/reference/logging-tags.md` | New `[CONVERSATION_GENERATED_DOCUMENTS]` tag. |

No setting, deployment or data change is needed.

## Validation

### Tests

- `functional_tests/test_v2_drawer_generated_files_logic.mjs` runs the real collector.
  It covers the reported CSV with its download route, each format a plan can render
  with its label, every status, live run state over the saved snapshot, exports,
  Analyze files, background exports, approval-held files, masked and replaced replies,
  saved Analyze gating, de-duplication, ordering with agent documents, the request gate,
  what makes the agent-document list read again, which agent documents stay listed,
  and the badge count.
- `functional_tests/test_personal_conversation_generated_documents.py` runs the real
  route helper against a fake container with the real message, deletion and
  generated-document readers. It checks that deleted, replaced, masked and hidden
  messages are skipped and that compact citations are rebuilt. It also checks the
  routes' decorators, that the owner check runs before any read, that downloads are
  scoped to the conversation, and that no response carries exception text.
- `ui_tests/test_v2_drawer_generated_files.py` mounts the real drawer and chat page in
  Chromium with production CSS. It lists the reported CSV, a rendering PDF, a failed
  workbook, an agent's Word brief and an Analyze summary in conversation order. It
  downloads the CSV and the brief through their routes and previews the summary. It
  scrolls to the reply that produced a file, keeps the empty state, and checks that the
  header badge counts generated files while sharing one request with the drawer. A
  background export that finishes while the conversation is open becomes downloadable
  in the drawer. Showing another attempt or masking a reply re-reads the agent documents
  and hides what the thread no longer shows; a refused list is asked again when the
  drawer reopens; and returning to a conversation reads its list afresh.
- `ui_tests/test_v2_collaboration_ux.py` now gives its reply the upload citations its
  documents come from, which the shared list requires. It also checks that an invited
  reader's drawer makes no request the server would refuse, and that joining lists the
  documents without reopening the drawer.

These regression tests were checked against the code before the fix: the attempt and
masking, refused-list and invitation tests fail on the earlier version of the shared
store, and the background export test fails without the export card's report to the
drawer.

The route policy suites, the existing drawer, media and shared generated-document
tests, the V2 type check and production build, and the related V2 UI suites (planning
retry, orchestration outputs, media galleries, new chat reset, sidebar scroll and saved
output publication) pass.

### Before and after

| Before | After |
| --- | --- |
| A plan's CSV, Word, PDF or PowerPoint file was only on its card in the thread. | It is listed in the drawer with its status, and downloads from there when ready. |
| Exports and Analyze files were only on their cards. | They are listed too. |
| Agent documents were listed in shared conversations only. | They are listed in personal conversations as well. |
| The Documents badge counted only documents answers used. | It also counts what the conversation produced. |

## Limitations

- The classic chat page is unchanged.
- A background export's progress reaches the drawer through its card in the thread,
  which polls the run while the conversation is open.
- Whether an agent document can be downloaded is decided when the list is read, so a
  change to the download settings shows the next time it is read, for example when the
  conversation is opened again. The download itself always rechecks.

## Related

- [V2 shared conversation experience](../features/V2_COLLABORATION_UX.md)
- [V2 media galleries and viewer](../features/V2_MEDIA_GALLERIES_AND_VIEWER.md)
- [Chat controls reference](../../reference/chat-controls.md)
