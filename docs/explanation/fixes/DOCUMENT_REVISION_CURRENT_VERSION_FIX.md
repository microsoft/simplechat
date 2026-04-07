# Document Revision Current Version Fix (0.240.022)

Fixed/Implemented in version: **0.240.022**

## Header Information

### Issue Description

Uploading a document with the same name created a higher revision number, but the new revision started with empty tags and default classification metadata.

Older revisions also remained visible in workspace document lists and continued to participate in chat search, which made the revision model unusable in day-to-day workspace flows.

Deleting the visible revision did not distinguish between removing only the current revision and removing every stored version of that document.

### Root Cause Analysis

The document metadata model tracked a numeric `version`, but it did not maintain a stable revision family identifier or an explicit current-version flag.

Duplicate uploads therefore behaved like unrelated documents for metadata inheritance, list filtering, search visibility, and deletion behavior.

### Version Implemented

`0.240.022`

## Technical Details

### Files Modified

- `application/single_app/functions_documents.py`
- `application/single_app/functions_search.py`
- `application/single_app/route_backend_documents.py`
- `application/single_app/route_backend_group_documents.py`
- `application/single_app/route_backend_public_documents.py`
- `application/single_app/route_external_public_documents.py`
- `application/single_app/route_enhanced_citations.py`
- `application/single_app/static/js/workspace/workspace-documents.js`
- `application/single_app/static/js/public/public_workspace.js`
- `application/single_app/templates/workspace.html`
- `application/single_app/templates/public_workspaces.html`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/config.py`
- `functional_tests/test_document_revision_current_version_fix.py`
- `ui_tests/test_workspace_family_document_revision_delete_modal.py`

### Code Changes Summary

- Added revision-family metadata so duplicate-name uploads now share a stable `revision_family_id` and explicitly mark which revision is current.
- Carried forward editable metadata such as title, abstract, keywords, publication date, authors, classification, tags, and sharing metadata when a new revision is created.
- Archived older revisions from search visibility while keeping them stored for future comparison work.
- Kept the active blob path at the existing alias shape `user-id/filename`, `group-id/filename`, or `public-workspace-id/filename` so current citations and workspace downloads keep their established path structure.
- Added hierarchical archived revision blob paths at `user-id/revision-family-id/revision-document-id/filename`, `group-id/revision-family-id/revision-document-id/filename`, and `public-workspace-id/revision-family-id/revision-document-id/filename` so prior current blobs are preserved before overwrite.
- Stored `blob_container`, `blob_path`, `archived_blob_path`, and `blob_path_mode` on document metadata and taught enhanced citations to prefer those values with legacy fallback.
- Updated personal, group, public, and external public list routes so only current revisions are returned to workspace views.
- Added revision-aware deletion so users can choose **Delete Current Version** or **Delete All Versions** from the workspace UI.
- Bumped the application version to `0.240.022`.

### Testing Approach

- Added a functional regression test that validates revision-family metadata markers, hybrid alias-plus-archive blob paths, current-only route filtering, revision-aware delete mode handling, and version/documentation alignment.
- Added a Playwright UI regression test that verifies the personal, group, and public workspace pages use Bootstrap revision delete modals instead of native browser confirms.

### Impact Analysis

- Duplicate uploads now behave like real document revisions instead of disconnected records.
- Workspace lists and chat search now focus on the current revision while older revisions remain retained in storage.
- Current document download and citation flows keep the established alias path, while older revisions now get their own preserved blob location before a new upload overwrites the alias.
- Users can remove only the visible revision without automatically deleting older revisions, or choose to remove the full revision history when needed.

## Validation

### Before/After Comparison

Before: same-name uploads reset tags and classification, older revisions stayed visible and searchable, deletion acted like a single hard delete with no revision choice, and blob storage overwrote prior binary content at the shared workspace alias path.

After: same-name uploads inherit metadata into a new current revision, older revisions are retained but hidden from workspace/search flows, deletion offers **Delete Current Version** and **Delete All Versions**, and the previous current blob is archived at `scope-id/revision-family-id/revision-document-id/filename` before the alias path is overwritten.

### Test Results

- Functional regression coverage added in `functional_tests/test_document_revision_current_version_fix.py`.
- UI regression coverage added in `ui_tests/test_workspace_family_document_revision_delete_modal.py`.
- Current enhanced citation lookups now prefer stored blob metadata and fall back to legacy alias paths for older documents that have not been revised since the hybrid scheme was introduced.