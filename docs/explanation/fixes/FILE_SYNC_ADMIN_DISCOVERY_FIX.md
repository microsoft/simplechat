# File Sync Admin Discovery Fix

Fixed/Implemented in version: **0.241.052**

## Issue Description

The File Sync backend and workspace Sync tabs existed, but admins could not discover or manage the capability from Admin Settings, and the sidebar did not expose File Sync navigation entries.

## Root Cause Analysis

The File Sync implementation added service, API, scheduler, and workspace tab wiring, but the admin settings template, admin settings save path, and sidebar partial were missing the corresponding controls and links.

## Technical Details

### Files Modified

- `application/single_app/config.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/_sidebar_nav.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `functional_tests/test_file_sync_capability.py`
- `ui_tests/test_admin_file_sync_settings.py`

### Code Changes Summary

- Added File Sync to the Admin Settings Workspaces sidebar section.
- Added personal and group workspace sidebar links that open the Sync tab when File Sync is enabled for the active workspace.
- Added an Admin Settings File Sync card with global enablement, per-scope enablement, allow/block lists, run limits, default remote delete policy, and debug logging.
- Added Redis readiness warnings so admins can save requested settings while File Sync remains inactive until Redis is configured.
- Added admin save handling for every File Sync settings field.

## Validation

- Added functional regression checks for admin settings, route save handling, sidebar discovery, and File Sync UI visibility wiring.
- Added an Azure Playwright UI smoke test for the Admin Settings File Sync controls.
- Updated `config.py` to version `0.241.052` for traceability.