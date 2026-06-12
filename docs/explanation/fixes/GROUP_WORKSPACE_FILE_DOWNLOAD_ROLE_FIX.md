# Group Workspace File Download Role Fix (v0.241.195)

Fixed/Implemented in version: **0.241.195**

## Issue Description

Group workspace file downloads could be available to regular group users whenever the global and group-level download settings allowed downloads. The intended policy is that enabled group workspace file downloads are limited to group owners, admins, and document managers.

## Root Cause Analysis

The group document download authorization helper validated active group membership with the regular `User` role included. The group workspace page also gated download controls only on the download feature settings and active group assignment, so regular users could see and attempt file downloads when the workspace policy was enabled.

## Technical Details

### Files Modified

- `application/single_app/route_backend_group_documents.py`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/config.py`
- `functional_tests/test_group_workspace_file_download_permissions.py`
- `ui_tests/test_group_workspace_file_download_permissions.py`

### Code Changes Summary

- Added a dedicated group document download manager-role policy for owners, admins, and document managers.
- Applied that policy to single-document and bulk group document download authorization.
- Returned group document list download flags only for groups where the current user has a download-eligible role.
- Updated group workspace UI helpers so regular users do not see download menu items or bulk download controls.
- Bumped `config.py` version to `0.241.195`.

### Testing Approach

- Added source-level regression coverage for the backend role guard and frontend download control gating.
- Added a Playwright UI regression that mocks downloads as enabled for a regular group user and verifies download controls remain hidden and guarded.

## Impact Analysis

Regular group users can still view and chat with group documents according to existing group access rules, but they cannot download source files even when downloads are enabled for the group workspace. Owners, admins, and document managers keep the enabled download workflow.

## Validation

- `python functional_tests/test_group_workspace_file_download_permissions.py`
- `python -m pytest ui_tests/test_group_workspace_file_download_permissions.py`
- `python -m py_compile application/single_app/route_backend_group_documents.py functional_tests/test_group_workspace_file_download_permissions.py ui_tests/test_group_workspace_file_download_permissions.py application/single_app/config.py`