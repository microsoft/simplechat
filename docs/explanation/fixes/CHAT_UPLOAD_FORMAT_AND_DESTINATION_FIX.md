# Chat Upload Format and Destination Fix (v0.261.483)

Fixed/Implemented in version: **0.261.483**

The application version is maintained in `application/single_app/config.py` and
remains **0.261.483**.

## Issue

Chat rejected some files, including `.vsdx` diagrams, that could be uploaded
directly to a workspace. Picker lists and upload validation were maintained
separately, so they could disagree as supported formats or settings changed.
V2 could also show an unavailable-formats message when conversation metadata
had not yet loaded.

Separately, a new V2 conversation could send an upload to the active group
workspace even though the group was not selected as the chat's scope.

## Root cause

- Chat's workspace handoff and client-side pickers used format lists separate
  from workspace upload validation.
- The V2 composer needed conversation metadata to select the correct format
  list, but did not always request missing metadata.
- V2 included the active group in upload scope IDs even when the draft did not
  select that group. The upload route interpreted those IDs as group context.

## Changes

- `functions_documents.py` provides a shared, feature-aware workspace extension
  policy for chat handoff and personal, group, public, and external public
  workspace uploads. Classic workspace pickers use the configured extension
  categories.
- Classic chat receives personal and group upload formats from the backend.
  V2 receives those lists in `chat_uploads` from its bootstrap response and
  uses them for the picker, paste, drop, and retry validation.
- `.vsdx` files use the existing workspace ingestion pipeline when available.
  If the personal workspace is disabled, chat extracts Visio page text locally
  instead. `.htm` is accepted and processed alongside `.html`; existing
  `.dotx` and `.potx` template support is preserved.
- V2 loads missing conversation metadata before determining upload formats and
  offers a retry if that request fails.
- V2 derives submitted group IDs from selected draft context rather than the
  active workspace alone. A new chat with no group context therefore defaults
  to personal uploads; group-scoped conversations and explicitly selected
  group context retain group routing. Group uploads remain subject to group
  write permissions.

Audio and video depend on their respective feature settings. Chat XSD uploads
also require Enhanced Citations, source storage, and an enabled workspace.
Image-reference mode retains its narrower image restrictions. Files already
uploaded to a workspace are not moved by this change.

## Files and tests

The main changes are in `application/single_app/config.py`,
`functions_documents.py`, `route_frontend_chats.py`, the workspace upload
routes, the classic chat and workspace templates, `route_backend_v2.py`,
`application/v2_ui/src/components/chat/ComposerEditor.tsx`, and
`application/v2_ui/src/lib/chatUploads.ts`.

Regression coverage includes `functional_tests/test_chat_visio_upload.py`,
`functional_tests/test_v2_chat_context_request.ts`,
`functional_tests/test_v2_chat_context_picker.py`,
`functional_tests/test_chat_upload_group_workspace_handoff.py`, and
`ui_tests/test_v2_chat_clipboard_uploads.py`.

## Validation and impact

The V2 production build succeeded. The focused V2 context and group handoff
functional suites passed 16 tests, and the browser-asset scanner suite passed
38 tests. The V2 browser tests, including picker, drop, retry, and group-locked
scenarios, were collected but not run; a live browser upload has not been
verified for this change.

Before the fix, an active group could unexpectedly receive a new chat upload.
After the fix, the active group alone does not determine the destination.
Explicitly group-scoped uploads may be visible to members with access to that
workspace. See [Upload documents in chat](../../guides/upload-documents-in-chat.md)
for the user workflow.
