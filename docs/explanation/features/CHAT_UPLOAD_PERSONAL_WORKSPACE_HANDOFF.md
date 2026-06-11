# Chat Upload Personal Workspace Handoff

Implementation status: **Implemented**

Documented against version: **0.241.192**

Fixed/Implemented in version: **0.241.174**

Related config.py version update: `application/single_app/config.py` is **0.241.192** for the latest lifecycle fix.

Implemented in version: **0.241.174**

## Overview

Chat uploads create file messages through `POST /upload`. Personal workspace uploads create document metadata and background processing jobs through `POST /api/documents/upload`. The implemented handoff now makes the personal workspace document the source of truth for eligible chat uploads when personal workspaces are enabled.

When the personal workspace is available, a file uploaded from the chat UI becomes a personal workspace document, gets tagged with `conversations`, stores the associated conversation ID in metadata, and appears in chat as a workspace-backed file message. The chat route does not run a second chat-local extraction or save a duplicate copy to the chat storage container for that eligible upload. When the personal workspace is not available, the existing chat-only upload flow continues without behavioral change.

Chat uploads also resolve duplicate personal workspace filenames before document metadata is created. If a user uploads `report.pdf` from multiple chats, the later workspace document gets a collision-free name such as `report (1234).pdf` or `report (1).pdf`, while the original uploaded filename remains in metadata for traceability. This mirrors File Sync's identity-first behavior: File Sync tracks a source item by path-derived identity, while chat uploads track the source by conversation and message identity and keep the workspace filename unique so separate uploads do not collapse into the workspace revision flow.

## Goals

- Preserve the existing chat upload UX: pasted, dropped, and selected files should still appear in the current conversation as uploaded file messages.
- Automatically make chat-uploaded files available to personal workspace search, document analysis, document comparison, and enhanced citation pipelines.
- Avoid requiring the user to manually select the personal workspace or re-upload the file after uploading it into chat.
- Add clear lifecycle behavior for linked documents when the conversation is deleted or the workspace document is deleted first.
- Keep fallback behavior simple: if the personal workspace path is disabled, use the current chat-only flow; if an eligible workspace handoff fails, surface the failure instead of silently storing the file in chat-local storage.
- Avoid duplicate chat-local processing and chat storage for uploads that have already been accepted into the personal workspace pipeline.
- Avoid filename collisions that would turn separate chat uploads into personal workspace document revisions.

## Dependencies

- App settings: `enable_chat_file_uploads`, `require_member_of_chat_file_upload_user`, `enable_user_workspace`, `enable_enhanced_citations`, and `enable_conversation_archiving`.
- Existing chat upload route: `POST /upload`.
- Existing personal workspace upload route: `POST /api/documents/upload`.
- Existing personal workspace delete route: `DELETE /api/documents/<document_id>`.
- Existing conversation delete routes: `DELETE /api/conversations/<conversation_id>` and `POST /api/delete_multiple_conversations`.
- Existing document tag storage and propagation through `functions_documents.py`.
- Existing chat conversation deep-link support through `/chats?conversation_id=<conversation_id>`.

## Expected User Workflow

1. A user uploads, drops, or pastes a file in the chat UI.
2. If the personal workspace is enabled and the file type is eligible, the file is queued as a personal workspace document.
3. The chat conversation shows a workspace-backed upload message with the processing progress bar visible; the uploaded file name links to the workspace document.
4. Users can expand the progress card to see status text while processing, and status details collapse by default again when processing finishes.
5. After processing completes, the Workspaces panel is activated and the completed document is selected in the document picker.
6. Questions in that conversation automatically include the linked workspace document in the workspace search/enhanced citation context.
7. The workspace document can be searched, analyzed, compared, cited, edited, tagged, or deleted through normal workspace flows.
8. The workspace document shows enough linkage metadata for the user to understand it came from a chat conversation.
9. If the user deletes the workspace document first, the delete modal warns that the document is associated with a conversation and links back to it.
10. If the user deletes the conversation first, linked workspace documents are listed in the delete dialog and only the documents the user selects are deleted with the conversation.

## Current Behavior

### Chat Uploads

`application/single_app/route_frontend_chats.py` registers `POST /upload`. The route currently:

- Enforces `enable_chat_file_uploads`, optional `ChatFileUploadUser`, login, user access, and `file_upload_required`.
- Creates a new personal conversation if no `conversation_id` is submitted.
- Saves the file to a temporary path and queues eligible files into personal workspace processing.
- Resolves a collision-free personal workspace filename before queuing eligible chat uploads.
- Creates a workspace-backed `role = file` chat message for successful workspace handoff and skips duplicate chat-local extraction/blob storage.
- Polls the personal workspace document status from the chat message and from the upload response's `workspace_document_id` so active chat cards update without a browser refresh.
- Keeps the progress bar visible while processing and collapses status text behind an expand control for in-progress and completed states.
- Activates the Workspaces panel and selects the completed personal workspace document in the document picker so the user can keep the default Search action or choose Analyze/Compare.
- Syncs final status back into chat message metadata so reloads do not show stale queued progress.
- Uses the existing chat-only extraction and blob-backed paths only when workspace handoff is not eligible because personal workspace is unavailable.
- Returns a workspace upload failure if an eligible personal workspace handoff cannot be queued.
- Updates conversation `last_updated` and may derive the conversation title from the uploaded filename.
- Returns the existing response shape expected by `static/js/chat/chat-input-actions.js`: `conversation_id` and optional `title`.

### Personal Workspace Uploads

`application/single_app/route_backend_documents.py` registers `POST /api/documents/upload`. The route currently:

- Requires `enable_user_workspace` and `file_upload_required`.
- Creates personal document metadata through `create_document()`.
- Queues `process_document_upload_background()`.
- Persists tags in the document record.
- Propagates tags to chunks and blob metadata when tags change.
- Invalidates personal search cache after upload and tag operations.

### Workspace Delete UI

`application/single_app/static/js/workspace/workspace-documents.js` already centralizes document deletion through `promptDocumentDeleteMode()`, `requestDocumentDeletion()`, and `window.deleteDocument()`. It also has a specialized File Sync warning flow. The linked-conversation warning can follow that same modal pattern.

## Implemented Behavior

For each chat upload:

1. Run the current chat upload authorization and file validation checks.
2. Ensure a personal conversation exists and is owned by the current user.
3. Check whether the personal workspace handoff is eligible.
4. If eligible, create a personal workspace document from the same uploaded temp file and queue normal workspace processing.
5. Create a lightweight workspace-backed chat file message with metadata that points to the workspace document and uses the resolved workspace filename.
6. Return the same client response shape, with optional additional fields for future UI use.
7. Skip legacy chat extraction, `file_content` storage, chat image blob storage, and chat tabular blob storage for the successful workspace-backed branch.
8. If the workspace handoff is not eligible because the personal workspace is unavailable, continue through the existing chat-only upload path. If the workspace handoff is eligible but fails, return an upload error instead of silently storing the file in chat-local storage.

Eligibility should be conservative:

- `enable_user_workspace` is true.
- The authenticated user is allowed to upload files through the existing gates.
- The file extension is supported by personal workspace ingestion.
- Required workspace dependencies are configured enough to create metadata and queue processing.
- The request is for a personal chat conversation. Collaboration and group chat upload handoff should be separate follow-up work.

## Data Model

The workspace document should use existing document metadata wherever possible, plus explicit linkage fields. Tags are useful for search/filtering, but lifecycle logic should not depend only on user-editable tags.

Implemented personal document fields:

```json
{
  "source_type": "chat_upload",
  "source_subtype": "personal_conversation_attachment",
  "created_from_chat_upload": true,
  "conversation_id": "<conversation_id>",
  "conversation_title_at_upload": "<conversation title>",
  "chat_message_id": "<message_id>",
  "chat_upload_delete_with_conversation": true,
  "chat_upload_link_state": "linked",
  "chat_upload_linked_at": "<utc iso timestamp>",
  "chat_upload_original_filename": "<uploaded filename>",
  "chat_upload_workspace_filename": "<resolved unique workspace filename>",
  "source_original_file_name": "<uploaded filename>"
}
```

Implemented chat message metadata:

```json
{
  "workspace_attachment": {
    "scope": "personal",
    "document_id": "<document_id>",
    "conversation_id": "<conversation_id>",
    "link_state": "linked",
    "processing_status": "queued"
  }
}
```

Implemented tags on the personal workspace document:

```json
[
  "conversations"
]
```

The conversation ID is stored in explicit metadata fields such as `conversation_id`, `conversation_url`, and `chat_message_id`. Lifecycle and search association logic must use those metadata fields, not a user-visible tag.

## Tag Ramifications

Using normal document tags means the `conversations` tag will naturally flow into:

- Personal workspace document lists.
- Personal workspace tag filters.
- Chat workspace tag filters.
- Azure AI Search chunk metadata as `document_tags`.
- Blob metadata when enhanced citations are enabled.

The conversation ID is intentionally not added as a tag because UUID-like tags clutter folder and tag pickers without helping normal workspace organization. The metadata fields remain authoritative for finding linked documents, showing conversation warnings, and deleting selected documents with a conversation.

Optional tag-definition metadata can still identify the reserved `conversations` tag as system-generated:

```json
{
  "conversations": {
    "color": "#6c757d",
    "created_at": "<utc iso timestamp>",
    "is_system": true,
    "system_tag_type": "chat_upload"
  }
}
```

The first implementation can skip hidden tag UI if that is too much surface area. The important product rule is that only the general `conversations` tag should be visible to users; per-conversation linkage belongs in metadata.

## Backend Implementation Plan

### Shared Upload Helper

Avoid calling one Flask route from another. Factor the workspace upload internals into a helper that both `POST /api/documents/upload` and `POST /upload` can use.

A likely helper shape:

```python
def create_personal_workspace_document_from_upload(
    *,
    user_id,
    temp_file_path,
    original_filename,
    tags=None,
    source_metadata=None,
):
    """Create document metadata, queue background processing, and return the document record."""
```

The helper should own:

- `secure_filename()` handling or receive a sanitized filename from the caller.
- Document metadata creation with tags and source metadata.
- Background processing queue setup.
- Search cache invalidation.
- Structured logging.

### Chat Upload Route

`POST /upload` keeps the current fallback behavior in place, but the eligible workspace branch now replaces the old chat-local file processing path:

- Queue the workspace document from a temp-file copy.
- Resolve a unique personal workspace filename before calling `create_document()` so separate chat uploads do not enter the workspace revision path solely because their display names match.
- Create a `role = file` message with `file_content_source = workspace`, `workspace_document_id`, and `metadata.workspace_attachment`.
- Return immediately after writing the workspace-backed message.
- Avoid writing `file_content`, chat image blobs, or chat tabular blobs for the successful workspace-backed branch.
- Refresh chat progress from `GET /api/documents/<document_id>` and normalize the response before reading `status` and `percentage_complete`.
- Start a completion watcher from the upload response's `workspace_document_id` so live status updates do not depend only on the rendered card hydration path.
- When processing completes successfully, collapse the progress/status details and select the completed document in the Workspaces document picker without changing the current document action from Search.
- After background processing finishes or fails, sync the linked chat message's `metadata.workspace_attachment` from the workspace document record so message reloads preserve the current status.

If the workspace branch is unavailable because the personal workspace is disabled, the route falls back to the existing chat-only extraction/storage path. If the workspace branch is eligible but cannot be safely queued, the route returns an upload error instead of falling through to chat-local storage.

### Automatic Conversation Context

Creating a workspace document is not enough by itself if the user still has to select that document manually. The chat answer pipeline should automatically include linked workspace documents for the active conversation.

Recommended behavior:

- Add a helper that returns active, fully processed workspace document IDs linked to a conversation and owned by the current user.
- Merge those IDs with explicit `selected_document_ids` before search-only document retrieval in both regular and streaming chat routes.
- Keep explicit user selections and Assigned Knowledge restrictions respected.
- Exclude linked documents that are still processing, failed, deleted, or unlinked.
- Include metadata in capability usage logs so administrators can distinguish user-selected documents from auto-linked chat-upload documents.

Document actions need a small UX decision:

- Search can safely include all ready linked documents automatically.
- Analyze should offer linked chat-upload documents as preselected candidates, but should still respect document action limits.
- Compare should not silently choose comparison pairs. It can make linked documents easy to pick, but the user should choose source and target when multiple linked files exist.

## Delete Lifecycle

### Conversation Deleted First

Single and bulk conversation deletion live in `application/single_app/route_backend_conversations.py`. Single conversation metadata now includes `linked_workspace_documents`, which is built from personal workspace documents where `created_from_chat_upload` is true and `conversation_id` matches the conversation being deleted.

The single conversation delete modal lists those linked workspace documents with checkboxes. The default state keeps every workspace document. Users can select one document or use select all, and only those selected document IDs are sent to `DELETE /api/conversations/<conversation_id>` as `delete_workspace_document_ids`.

Implemented policy:

- If no workspace documents are selected, all linked workspace documents remain in the personal workspace and continue to follow the document retention policy.
- If one or more workspace documents are selected, the backend validates them against the current user and conversation before calling `delete_document_revision(..., delete_mode="all_versions")`.
- Single hard delete still removes chat-scoped blob-backed attachment files and chat messages.
- Bulk conversation delete retains linked workspace documents because there is no per-document selection dialog in the bulk flow.
- Archive-enabled conversation delete retains linked workspace documents by default, but still deletes workspace documents that the user explicitly selects in the delete dialog.
- Lifecycle decisions use explicit metadata fields, not tags.

### Workspace Document Deleted First

`DELETE /api/documents/<document_id>` should inspect the target document before showing or completing deletion.

Recommended flow:

1. The delete request detects `created_from_chat_upload = true` and an active `conversation_id`.
2. If the client did not already confirm the linked delete, return `409` with a structured payload.
3. `workspace-documents.js` shows the existing `documentDeleteModal` with a linked-conversation warning.
4. The modal shows the conversation ID and a link to `/chats?conversation_id=<conversation_id>`.
5. If the user confirms, the delete request continues and marks the chat message link state as `workspace_document_deleted`.

Example `409` response:

```json
{
  "error": "conversation_linked_document_delete_requires_confirmation",
  "message": "This document is associated with a conversation.",
  "conversation_id": "<conversation_id>",
  "conversation_url": "/chats?conversation_id=<conversation_id>",
  "document_id": "<document_id>"
}
```

The chat attachment should remain visible after workspace deletion, but the metadata should show that workspace processing is no longer available. If the first implementation keeps legacy chat file content, the existing chat link can continue to open. If a later implementation makes chat attachments workspace-only, the UI must show a clear deleted-document state.

## Failure Modes

- Workspace disabled: use the existing chat-only flow.
- Workspace document creation fails before metadata is written: log the failure and return an upload error so the user does not unknowingly create a chat-local attachment.
- Workspace metadata is created but background processing fails: keep the chat attachment, show the document processing error in the workspace, and keep the link state as `linked_failed_processing` or equivalent.
- Chat message creation fails after workspace document creation: delete the newly created workspace document or mark it as `orphaned_chat_upload` and surface it in logs. Prefer rollback for a clean user experience.
- User deletes the conversation while workspace processing is still running: stop polling for selected documents that are deleted with the conversation, retain unselected documents, and make background processing tolerate missing metadata.
- User deletes or renames the `conversations` tag: lifecycle behavior must still work because metadata fields remain authoritative.
- User shares a linked workspace document: conversation delete should retain the document by default or require an explicit policy decision.
- Re-uploading the same filename in any chat: create a new workspace document with a collision-free filename and keep each chat message linked to its corresponding document ID.

## Permissions And Security

- Keep `POST /upload` guarded by `enable_chat_file_uploads`, optional `ChatFileUploadUser`, login, `user_required`, and `file_upload_required`.
- Do not use the workspace route decorator as the only guard for handoff; check `enable_user_workspace` inside the chat route and fall back when it is false.
- Do not expose raw settings to the frontend when adding UI state.
- Ensure linked-document lookup verifies `document.user_id == current_user_id`.
- Ensure conversation lookup verifies `conversation.user_id == current_user_id`.
- Do not allow user-supplied `conversation_id` to link a document to another user's conversation.
- Treat conversation ID metadata as association data, not an authorization boundary.

## Frontend Plan

### Chat UI

The upload client still accepts the existing `conversation_id` and optional `title` response shape. When the server also returns `workspace_document_id`, the client starts a completion watcher, updates the visible chat card as processing advances, and selects the completed personal workspace document in the Workspaces document picker.

Optional chat enhancements:

- Add a subtle workspace indicator to uploaded file messages when a workspace document exists.
- Show processing state if the workspace document is still being indexed.
- Offer an "Open in Workspace" action for linked documents.
- Show a clear state if the workspace document was deleted but the chat attachment remains.

### Workspace UI

Extend the existing document delete modal pattern:

- Add `promptConversationLinkedDocumentDeleteAction(deleteInfo)` next to `promptSyncedDocumentDeleteAction(deleteInfo)`.
- Reuse `documentDeleteModalBody.replaceChildren(...)` to avoid unsafe HTML string assembly.
- Include the conversation ID as text and link to `/chats?conversation_id=<id>`.
- Continue supporting current-only and all-versions delete choices after the user acknowledges the conversation link.

## Testing Plan

Functional tests should cover:

- Chat upload with personal workspace enabled creates both a chat message and a personal workspace document.
- Chat upload with personal workspace disabled uses the existing chat-only flow.
- Workspace document has the `conversations` tag only; the conversation ID is stored in metadata.
- Repeated chat uploads with the same filename resolve distinct workspace filenames before document creation.
- Workspace document chunks receive the same tags after processing.
- Chat message metadata stores the linked workspace document ID.
- Chat answer search automatically includes ready linked workspace documents for the active conversation.
- Conversation delete modal lists linked workspace documents with individual and select-all choices.
- Conversation hard delete deletes only the selected linked workspace documents and chunks.
- Conversation hard delete retains unselected linked workspace documents so they follow the document retention policy.
- Conversation archive-enabled delete retains linked workspace documents.
- Bulk conversation delete retains linked workspace documents unless a future explicit bulk selection flow is added.
- Workspace document delete first returns a linked-conversation warning payload and then deletes after confirmation.
- The warning payload rejects attempts to delete another user's linked document or link to another user's conversation.
- Tag deletion or rename does not break lifecycle cleanup because metadata fields are authoritative.

UI tests should cover:

- Uploading from chat still renders an attachment or image in the message list.
- The workspace document appears in the personal workspace list after upload.
- The workspace delete modal shows the conversation ID and navigable conversation link for linked documents.
- The chat page opens from `/chats?conversation_id=<conversation_id>`.

## Staged Implementation

1. Add shared workspace-upload helper and chat-upload handoff metadata.
2. Create linked workspace documents in compatibility mode while preserving current chat message content.
3. Add automatic linked-document inclusion to chat search context.
4. Add selectable linked-document deletion to the single conversation delete flow and retain linked documents during bulk deletes.
5. Add workspace delete warning and link-state updates.
6. Add optional UI affordances: workspace indicator in chat messages and hidden/reserved tag behavior.
7. Revisit storage duplication once behavior is stable, then decide whether some chat file types can become workspace-reference-only.

## Open Decisions

- Should the reserved `conversations` tag be hidden from normal tag management, or remain visible as a useful high-level folder/filter?
- Should archive-enabled conversation deletion delete linked workspace documents, retain them, or be controlled by a new setting?
- When a chat-uploaded document is edited, shared, or revised in the workspace, should it remain selectable for deletion with the conversation or require an additional warning?
- Should linked workspace documents be automatically included only for search, or also preselected for analyze flows?
- Should group and collaborative conversations get similar workspace handoff behavior later, and if so should they target group workspaces instead of personal workspaces?

## References

- `application/single_app/route_frontend_chats.py` - current chat upload route.
- `application/single_app/route_backend_documents.py` - personal workspace upload, delete, and tag APIs.
- `application/single_app/functions_documents.py` - document metadata, chunk saving, tag propagation, and delete helpers.
- `application/single_app/route_backend_conversations.py` - single and bulk conversation delete lifecycle.
- `application/single_app/static/js/chat/chat-input-actions.js` - chat upload client contract.
- `application/single_app/static/js/workspace/workspace-documents.js` - workspace upload and delete modal flows.
- `application/single_app/static/js/chat/chat-onload.js` - chat conversation deep-link support.
