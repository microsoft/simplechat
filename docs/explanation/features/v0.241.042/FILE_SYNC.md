# File Sync Capability

Implemented in version: **0.241.042**

## Overview

File Sync lets workspace managers configure SMB sources that copy remote files into SimpleChat document workspaces. The first implementation supports personal, group, and public workspaces with one-way sync from SMB into SimpleChat.

Fixed/Implemented in version: **0.241.042**

Related config.py version update: `application/single_app/config.py` was updated to `0.241.042`.

## Dependencies

- Redis Cache must be enabled before File Sync can be enabled.
- SMB access uses `smbprotocol`.
- Key Vault secret storage is used for SMB passwords when `enable_key_vault_secret_storage` and `key_vault_name` are configured.
- Existing document ingestion, versioning, tagging, search indexing, and activity logging services are reused.

## Technical Specifications

### Architecture

- File Sync source records are stored in scope-specific Cosmos containers partitioned by the owning workspace id.
- File Sync item state and run history are stored in scope-specific containers partitioned by `source_id`.
- The backend never treats `source_id` as an authorization boundary. Routes resolve the active user/workspace context and then read the source from the expected partition.
- Scheduled runs are coordinated by the existing Cosmos-backed distributed background task lock.

### Cosmos Containers

- `personal_file_sync_sources`, partition `/user_id`
- `group_file_sync_sources`, partition `/group_id`
- `public_file_sync_sources`, partition `/public_workspace_id`
- `personal_file_sync_items`, `group_file_sync_items`, `public_file_sync_items`, partition `/source_id`
- `personal_file_sync_runs`, `group_file_sync_runs`, `public_file_sync_runs`, partition `/source_id`

### API Endpoints

- Personal: `/api/file-sync/personal/sources`
- Group: `/api/file-sync/group/sources`
- Public: `/api/file-sync/public/<public_workspace_id>/sources`
- Source update/delete/sync/history endpoints are available below each source route.

### Configuration

Admin settings include:

- Global enable/disable toggle
- Per-scope toggles for personal, group, and public workspaces
- Allow/block lists for users, groups, and public workspaces
- Per-workspace source limit
- Minimum schedule interval
- Max files and bytes per run
- Concurrent run limit
- Default remote-delete policy
- File Sync debug logging toggle

## Usage Instructions

1. Enable and configure Redis Cache in Admin Settings.
2. Enable File Sync in Admin Settings.
3. Enable the desired workspace scopes and optional allow/block lists.
4. Open a workspace Sync tab.
5. Add an SMB source with UNC path, credentials, filters, tags, and optional schedule.
6. Run Sync manually or let the scheduler pick up due sources.

## Sync Behavior

- New remote files create new SimpleChat documents.
- Changed remote files create new SimpleChat document versions through the existing same-name upload versioning behavior.
- Tags can be assigned directly and derived from parent or full folder paths.
- Include/exclude patterns and file type filters restrict which files are ingested.
- Remote deletes never delete the SMB file. Depending on policy, SimpleChat can keep its copy or hard-delete its synced copy.
- Deleting a synced SimpleChat document can mark the remote path ignored so it does not return on the next sync.

## Testing and Validation

- Functional test: `functional_tests/test_file_sync_capability.py`
- UI test: `ui_tests/test_workspace_file_sync_ui.py`
- Syntax checks were run for changed Python files with `python -m py_compile`.
- JavaScript syntax checks were run with `node --check`.

## Known Limitations

- The first implementation supports SMB only.
- Sync is one-way from SMB to SimpleChat.
- Sync execution happens in the app process scheduler/executor; the helper module is structured so it can move to an external worker later.