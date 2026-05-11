# PUBLIC_WORKSPACE_DELETE_TOAST_FIX

Fixed/Implemented in version: **0.240.056**

## Issue Description

Public workspace document delete failures used blocking browser `alert(...)` dialogs instead of the app's Bootstrap toast pattern.

## Root Cause Analysis

The public workspace page did not have a shared notification helper for document delete failures, so the single-delete and bulk-delete error paths surfaced native alerts directly from `public_workspace.js`.

## Technical Details

Files modified:

- `application/single_app/static/js/public/public_workspace_utility.js`
- `application/single_app/static/js/public/public_workspace.js`
- `application/single_app/config.py`
- `functional_tests/test_public_workspace_delete_toast_fix.py`
- `ui_tests/test_public_workspace_delete_error_toast.py`

Code changes summary:

- Added `showPublicWorkspaceToast()` to the shared public workspace utility script.
- Routed single-document delete failures through the shared toast helper with a danger variant.
- Routed bulk delete partial-failure messaging through the same toast helper with warning or danger variants.
- Added source-level and UI regression coverage for the non-blocking delete failure experience.

Testing approach:

- Added a functional regression test that verifies the shared toast helper exists and the delete flows call it instead of `alert(...)`.
- Added a Playwright UI regression test that intercepts a failing public document delete request and confirms the page shows a toast without raising a browser dialog.

## Validation

Before:

- Failed public document deletes showed blocking browser alerts.
- Bulk delete partial failures also used alerts, interrupting the workflow.

After:

- Public workspace delete failures surface in the shared Bootstrap toast container.
- Delete failure messaging is non-blocking and consistent with the rest of the application's notification patterns.