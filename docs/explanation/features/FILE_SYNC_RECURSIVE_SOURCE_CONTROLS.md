# File Sync Recursive Source Controls

Implemented in version: **0.241.056**

Fixed/Implemented in version: **0.241.056**

## Overview

File Sync source management now supports explicit recursive folder control, SMB connection testing before save, and a more structured source form for selecting fixed tags. The application version was updated in `application/single_app/config.py` to track this feature work.

## Dependencies

- File Sync must be enabled by an administrator.
- Redis Cache must be configured before sync runs are effective.
- SMB sources require the `smbprotocol` package.
- Directory user search in Admin Settings uses Microsoft Graph access already used by SimpleChat directory user helpers.

## Technical Specifications

- Administrators can allow or disable recursive File Sync sources with `file_sync_allow_recursive_sources`.
- Each source stores a `recursive` boolean. When disabled, the SMB scanner reads only files directly under the configured UNC path.
- Folder-derived tags continue to use each file's relative path from the configured UNC root, so parent folder mode tags the file's immediate containing folder rather than the root share path.
- New connection-test endpoints validate UNC path and credentials without saving source changes.
- The workspace source form fetches existing workspace tags and lets users select fixed tags as chips while still allowing new tag names.

## File Structure

- `application/single_app/functions_file_sync.py` - recursive source normalization, recursive-aware SMB walking, and SMB connection testing.
- `application/single_app/route_backend_file_sync.py` - per-scope connection-test APIs and admin user search API.
- `application/single_app/static/js/workspace/workspace-file-sync.js` - source form recursive switch, tag selector, schedule slider, and test connection button.
- `application/single_app/templates/admin_settings.html` - recursive admin control and searchable user allow/block controls.
- `application/single_app/static/js/admin/admin_settings.js` - admin user search, bulk add, and chip list behavior.

## Usage Instructions

Administrators enable File Sync and choose whether recursive sources are allowed. Workspace managers can then add or edit SMB sources, turn recursive scanning on or off per source, test connectivity before saving, select fixed tags, and choose whether missing remote files should be kept or deleted locally.

## Testing and Validation

- Functional coverage: `functional_tests/test_file_sync_capability.py`.
- UI smoke coverage: `ui_tests/test_workspace_file_sync_ui.py`.
- Source-level connection tests are intentionally shallow and check top-level directory access without walking the entire share.

## Known Limitations

- Connection testing validates access to the configured root path only; it does not guarantee every nested folder can be scanned.
- Recursive scans can still hit max file, byte, and run limits configured by administrators.