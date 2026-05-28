# Token Export Workspace Names Fix

## Issue Description

Control Center Activity Trends token exports showed `Workspace Type`, `Group ID`, and `Public Workspace ID`, but did not include friendly group or public workspace names. Admins had to manually map IDs back to workspace records to understand token usage by workspace.

## Root Cause Analysis

Token export records were built directly from `activity_logs` token usage entries. Those logs store scoped IDs in `workspace_context`, but the export path did not resolve those IDs against the group and public workspace containers before writing CSV rows.

## Fixed in version: **0.241.115**

The application version is tracked in `application/single_app/config.py` and is currently `0.241.115` for this fix.

## Technical Details

### Files Modified

*   `application/single_app/route_backend_control_center.py`
*   `functional_tests/test_control_center_token_export_workspace_names.py`

### Code Changes Summary

*   Added group and public workspace name resolver helpers for Control Center reporting.
*   Added `group_name` and `public_workspace_name` fields to raw token export records.
*   Added `Group Name` and `Public Workspace Name` columns to token CSV exports.
*   Added regression coverage that verifies the backend export path includes the new fields and CSV headers.

### Testing Approach

*   Python syntax validation with `py_compile`.
*   Functional source regression test for token export workspace name fields.
*   Targeted diagnostics on modified backend and test files.

## Validation

### Test Results

*   `python -m py_compile application/single_app/route_backend_control_center.py functional_tests/test_control_center_token_export_workspace_names.py`
*   `python functional_tests/test_control_center_token_export_workspace_names.py`

### Before/After Comparison

Before, token exports included workspace IDs without friendly names. After the fix, group-scoped token rows include `Group Name`, and public workspace token rows include `Public Workspace Name`, while preserving the existing ID columns for precise filtering and lookup.

### User Experience Improvements

Admins can now read token exports without manually cross-referencing group or public workspace IDs, making group and public workspace token reporting easier to audit and share.