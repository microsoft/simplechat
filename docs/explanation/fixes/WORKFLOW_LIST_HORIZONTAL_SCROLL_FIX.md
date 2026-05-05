# Workflow List Horizontal Scroll Fix

Fixed in version: **0.241.045**

## Issue Description

The personal workspace workflow list showed a horizontal scrollbar on desktop even when only a single workflow row was visible. The scroll came from rigid column sizing in the list table, especially the oversized actions column.

## Root Cause Analysis

- The workflow list table used percentage-based columns plus a large hard minimum width on the actions column.
- The new labeled workflow buttons made that large minimum width easier to hit, so the `.table-responsive` wrapper started exposing horizontal overflow on normal desktop widths.
- The list layout did not use a fixed-width table contract, which made the browser keep honoring the minimum widths instead of distributing the available space predictably.

## Technical Details

### Files Modified

- `application/single_app/templates/workspace.html`
- `application/single_app/static/js/workspace/workspace_workflows.js`
- `application/single_app/config.py`
- `functional_tests/test_workflow_list_horizontal_scroll_fix.py`
- `ui_tests/test_workspace_workflow_list_no_horizontal_scroll.py`

### Code Changes Summary

- Added a fixed-width layout contract for the workflows list table on desktop.
- Removed the oversized actions-column minimum width that was forcing the table wider than its card.
- Allowed the workflow action buttons to wrap within their cell instead of forcing a single unbroken button row.
- Kept mobile behavior flexible by switching the workflows table back to `table-layout: auto` on smaller viewports.

## Testing Approach

- Added `functional_tests/test_workflow_list_horizontal_scroll_fix.py` to assert the workflow table layout contract and version update.
- Added `ui_tests/test_workspace_workflow_list_no_horizontal_scroll.py` to validate that the desktop workflow list no longer overflows horizontally while keeping the workflow actions visible.

## Validation

### Test Results

- `functional_tests/test_workflow_list_horizontal_scroll_fix.py` passes locally.
- The browser UI regression was added but requires `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE` to run in an authenticated environment.

### User Experience Improvements

- The workflow list fits within the workspace card on desktop without showing a horizontal scrollbar.
- Workflow actions remain available in the list row because the buttons now wrap within the available cell width.
- Mobile behavior stays flexible instead of hard-locking the table to a desktop layout.