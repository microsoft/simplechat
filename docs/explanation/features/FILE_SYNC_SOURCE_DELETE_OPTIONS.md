# File Sync Source Delete Options

Implemented in version: **0.241.061**

Fixed/Implemented in version: **0.241.061**

## Overview

File Sync source deletion now presents a modal choice instead of an inline confirmation. Workspace managers can delete only the sync source while keeping synced documents, or delete the synced documents before the source is removed.

## Dependencies

- File Sync must be enabled for the workspace scope.
- Users must have the existing File Sync manager role for the workspace.
- The version was updated in `application/single_app/config.py` for traceability.

## Technical Specifications

- The shared File Sync source table opens a Bootstrap modal with three choices: cancel, delete the source only, or delete all synced files with the source.
- The source delete API accepts `delete_associated_files` in the JSON body.
- Associated file deletion uses the existing synced document deletion helper so personal, group, and public workspace deletion behavior stays scoped correctly.
- If associated document deletion fails, the source is not deleted and the API reports the failure.

## File Structure

- `application/single_app/static/js/workspace/workspace-file-sync.js` - source delete modal and delete choice payload.
- `application/single_app/route_backend_file_sync.py` - delete request payload handling.
- `application/single_app/functions_file_sync.py` - associated synced document deletion before source removal.
- `functional_tests/test_file_sync_capability.py` - regression coverage for backend and UI wiring.
- `ui_tests/test_workspace_file_sync_ui.py` - modal option smoke coverage.

## Testing and Validation

- `functional_tests/test_file_sync_capability.py` validates backend cascade wiring and modal text/options.
- `ui_tests/test_workspace_file_sync_ui.py` validates the delete modal appears with both destructive choices.

## Known Limitations

- Associated file deletion relies on File Sync tracking items. Documents manually detached from File Sync metadata may not be included.
- Delete all files removes SimpleChat documents only; it does not delete files from the remote SMB share.