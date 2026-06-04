# Workspace Select-All Initial State Fix

Fixed in version: **0.241.125**

## Issue Description

After entering multi-select mode in personal or group workspace document lists, the header select-all checkbox appeared but could not be clicked until a row checkbox was selected first.

## Root Cause Analysis

- The selection-mode sync calculated visible document checkboxes before applying the selection-mode class and before removing the `d-none` class from row checkboxes.
- Because the row checkboxes were still hidden during that first calculation, the header select-all checkbox was treated as having no visible document scope and was disabled.
- Selecting a row triggered a later sync after the row checkboxes were visible, which made the header checkbox start working.

## Technical Details

### Files Modified

- `application/single_app/static/js/workspace/workspace-documents.js`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/config.py`
- `functional_tests/test_workspace_select_all_initial_state.py`
- `ui_tests/test_workspace_document_selection_controls.py`

### Code Changes Summary

- Reordered personal workspace selection sync so table/card selection-mode classes and row checkbox visibility are applied before select-all state is calculated.
- Reordered group workspace selection sync the same way, including folder table and folder-card containers.
- Added regression coverage for the source ordering and browser-visible enabled state.
- Updated `config.py` to version `0.241.125` for this fix.

## Validation

### Test Results

- `functional_tests/test_workspace_select_all_initial_state.py` validates the sync ordering and version update.
- `ui_tests/test_workspace_document_selection_controls.py` now asserts the personal and group header select-all checkbox is visible and enabled immediately after clicking Multi-select.

### User Experience Improvements

- Users can click the header select-all checkbox immediately after enabling multi-select.
- Personal and group workspace selection behavior now matches the public workspace ordering pattern.