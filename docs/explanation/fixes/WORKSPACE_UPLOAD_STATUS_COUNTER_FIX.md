# Workspace Upload Status Counter Fix

Fixed in version: **0.261.005**

## Issue

During large workspace uploads, the temporary progress summary could display a high failed count, such as `Uploaded 77/204, Failed: 127`, even when most of those documents later appeared in the document list and finished successfully.

## Root Cause

The progress summary counted browser upload request responses, but its wording implied final document processing results. If a request did not confirm cleanly while the backend had already queued the document, the summary could permanently show that request as failed even though the document row later became the authoritative final state.

## Technical Details

Files modified:

- `application/single_app/templates/group_workspaces.html`
- `application/single_app/static/js/workspace/workspace-documents.js`
- `application/single_app/static/js/public/public_workspace.js`
- `ui_tests/test_workspace_upload_request_status_copy.py`
- `application/single_app/config.py`

The upload progress summary now says `Queued` for confirmed requests and `Upload requests not confirmed` for request-level failures. When all upload requests settle, the final status directs users to the refreshed document list for final processing status instead of leaving a stale failed count.

## Validation

Added UI regression coverage that checks personal, group, and public workspace upload summaries no longer use the misleading `Uploaded ... Failed` counter wording. VS Code diagnostics reported no errors for the changed JavaScript/template files, and `config.py` compiled successfully.
