# File Sync Stale Source Document Delete Fix

Fixed in version: **0.241.054**

## Issue Description

Documents created by File Sync could remain after their sync source was deleted. When users tried to delete those remaining documents, the first delete confirmation was followed by a synced-document confirmation, and the delete flow could stop after the initial `409 CONFLICT` response.

## Root Cause Analysis

The frontend reused the same Bootstrap delete modal for the normal delete confirmation and the synced-document confirmation. The first prompt resolved immediately on button click while the modal was still hiding, so the synced-document prompt could be attached before the previous `hidden.bs.modal` event completed.

The backend also treated any document with `file_sync` metadata as actively synced, even when the original sync source had been deleted. Selecting the ignore-remote action could then try to update a missing source.

## Version Implemented

Implemented in version: **0.241.054**

Related version update: `application/single_app/config.py` was incremented from `0.241.053` to `0.241.054`.

## Technical Details

### Files Modified

- `application/single_app/functions_file_sync.py`
- `application/single_app/static/js/workspace/workspace-documents.js`
- `application/single_app/static/js/public/public_workspace.js`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/config.py`
- `functional_tests/test_file_sync_capability.py`
- `ui_tests/test_workspace_file_sync_ui.py`

### Code Changes Summary

- Delete modal prompts now resolve only after the modal has fully hidden, preventing the synced-document prompt from being canceled by the previous modal transition.
- Synced-document delete guards now verify that the File Sync source still exists before requiring the synced-document action prompt.
- Ignore-remote delete handling now tolerates a deleted sync source and continues with document deletion.

### Testing Approach

- Functional tests validate the modal sequencing pattern and stale-source guard behavior.
- Existing File Sync wiring tests continue to validate delete guard registration across personal, group, and public routes.

## Impact Analysis

Users can delete documents that were formerly synced after the sync source has been removed. Active synced sources still prompt users to choose whether the remote path should be ignored before deleting the local document.

## Validation

### Before

Deleting a stale synced document could stop after a `409 CONFLICT`, leaving the document in place.

### After

Documents whose sync source no longer exists use the normal delete flow, and active synced documents can complete the second synced-delete confirmation without being canceled by modal timing.