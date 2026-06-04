# OneDrive File Sync

Implemented in version: **0.241.128**
Global connector identity management updated in version: **0.241.129**

## Overview

OneDrive File Sync adds a personal-workspace source type for pulling files from a user's OneDrive into SimpleChat's existing document processing and Azure AI Search indexing pipeline. The sync is one-way from OneDrive into SimpleChat.

## Dependencies

- Microsoft Graph application permissions for file access, such as `Files.Read.All`, granted to an admin-managed global File Sync identity.
- Existing File Sync prerequisites, including enabled File Sync settings and Redis readiness.
- Existing document processing services for extraction, chunking, embeddings, and indexing.

## Technical Specifications

- Source type: `onedrive`.
- Scope: personal workspaces only. Group and public workspace source creation is rejected for OneDrive.
- Authentication: Microsoft Graph application token acquired from an admin-managed global File Sync identity with client-secret credentials. Existing app registration configuration remains as an upgrade fallback.
- Change state: OneDrive drive item IDs are used for stable remote identity, and Graph `eTag`/`cTag` values are stored as remote change tokens before content checksum fallback.
- Content handling: changed files are downloaded to a temporary file, hashed with SHA-256, and passed through `process_document_upload_background()` like SMB and Azure Files sources.
- Metadata: synced documents keep `file_sync` metadata including source type, relative path, remote size, remote modified time, remote change token, content hash, and web URL when available.

## File Structure

- `application/single_app/functions_file_sync.py` - OneDrive provider helpers, selected path normalization, browse support, and provider dispatch.
- `application/single_app/route_backend_file_sync.py` - source browse APIs for creating and editing sync sources.
- `application/single_app/static/js/workspace/workspace-file-sync.js` - personal-only OneDrive source option, selected folders/files UX, browse modal, and moved include-subfolders control.
- `application/single_app/templates/admin_settings.html` - OneDrive source visibility control.
- `functional_tests/test_file_sync_onedrive_personal.py` - static regression coverage.

## Usage Instructions

1. Ensure File Sync is enabled and Redis is configured.
2. In Admin Settings, create a global workspace identity for File Sync using client-secret authentication and grant that app registration Microsoft Graph application file permissions.
3. In a personal workspace, open Sync, add a source, and choose OneDrive.
4. Leave selected folders/files empty to sync the OneDrive root, or browse/add specific folders and files.
5. Use Include subfolders to control recursive sync for selected folders.

## Testing and Validation

- Functional coverage: `functional_tests/test_file_sync_onedrive_personal.py`.
- Related UI smoke coverage: `ui_tests/test_workspace_file_sync_ui.py`.
- Existing Azure Files and File Sync static coverage was updated to version `0.241.129`.

## Known Limitations

- OneDrive sync uses a global connector identity with application permissions, so tenant administrators must consent to the required Graph permissions.
- OneDrive is intentionally limited to personal workspaces.
- Native Google Workspace files are not handled by this connector; Google Workspace should use a separate provider adapter with export handling.

## Version Tracking

- `application/single_app/config.py` was updated to `0.241.129` for the global connector identity update.
