# File Sync Cloud Connector Visibility Fix

Fixed/Implemented in version: **0.241.178**

## Issue Description

OneDrive, SharePoint, and Google Workspace File Sync connector options were visible as configurable Admin Settings source-type toggles before the connectors had completed validation. This could let admins expose cloud connector choices before the team was ready to support them broadly.

## Root Cause Analysis

The admin-visible source type list used the same setting path as fully available File Sync providers. OneDrive was also present in the default visible source type list, so new or legacy settings could expose it even when admins should only be able to enable the current File Sync and Azure Files paths.

## Version Implemented

- Fixed in version: **0.241.178**
- Related config version update: `application/single_app/config.py` uses `VERSION = "0.241.178"`.

## Technical Details

- Files modified:
  - `application/single_app/functions_file_sync.py`
  - `application/single_app/functions_settings.py`
  - `application/single_app/templates/admin_settings.html`
  - `application/single_app/static/js/admin/admin_settings.js`
  - `application/single_app/static/js/workspace/workspace-file-sync.js`
  - `application/single_app/templates/workspace.html`
  - `application/single_app/templates/group_workspaces.html`
  - `application/single_app/templates/manage_public_workspace.html`
- Code changes summary:
  - Added a server-side admin-visible source type allowlist for SMB Share and Azure Files.
  - Removed OneDrive from File Sync visible source type defaults while keeping provider code in place.
  - Rendered OneDrive, SharePoint, and Google Workspace controls as disabled coming-soon options in Admin Settings.
  - Updated frontend fallback visible source types to avoid exposing OneDrive when a root omits `data-visible-source-types`.
- Testing approach:
  - Updated File Sync functional tests for defaults, server-side allowlisting, and disabled admin controls.
  - Updated the Admin File Sync UI test to assert cloud connectors are visible but disabled.

## Impact Analysis

Admins can still enable File Sync and choose SMB Share or Azure Files as visible source types. OneDrive, SharePoint, and Google Workspace remain visible as coming soon, but they cannot be enabled from Admin Settings or submitted through the standard admin form.

## Validation

- Before: OneDrive could be included in `file_sync_visible_source_types` by default or through Admin Settings.
- After: Admin Settings only submits SMB Share and Azure Files source type values, and backend normalization filters cloud connector values out of saved visibility settings.
- User experience improvement: Admins see cloud connector status clearly without being able to turn those connectors on prematurely.