# WORKSPACE DOCUMENT CARDS AND HEALTHCHECK SETTINGS FIX

Fixed in version: **0.241.014**

## Overview

This update restores the default rounded workspace tabs on desktop, closes the remaining personal workspace switcher spacing issue, introduces a true document card view for personal and group workspaces, and adds admin wiring for the unauthenticated external healthcheck route.
Version `0.241.014` in `application/single_app/config.py` is the version associated with these updates.

## Issue Description

- Desktop workspace tabs had drifted into an intentionally square treatment instead of the app's normal rounded tab shape.
- Personal workspace still left a visible gap between the migration banner and the section switcher.
- Documents only had a list view and a folder browser, but no action-oriented card view.
- The unauthenticated `/external/healthcheckz` route existed without matching admin defaults, persistence, or UI controls.

## Root Cause Analysis

- Shared workspace CSS still carried a custom tab radius override from the previous refinement pass.
- The personal section switcher remained attached to the header area rather than the document area it controlled.
- Document rendering logic only supported table rows, so the new cards toggle needed cache-aware render paths and shared selection logic.
- Admin settings only persisted the authenticated healthcheck setting and never exposed a separate setting for the no-auth route.

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/templates/workspace.html`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/static/js/workspace/workspace-tags.js`
- `application/single_app/static/js/workspace/workspace-documents.js`
- `application/single_app/static/css/workspace-responsive.css`
- `application/single_app/config.py`
- `functional_tests/test_no_auth_external_healthcheck_admin_setting.py`
- `ui_tests/test_workspace_document_cards_layout.py`
- `ui_tests/test_workspace_sidebar_endpoint_links.py`

### Code Changes Summary

- Removed the custom square tab override so desktop workspace tabs inherit the normal rounded Bootstrap shape again.
- Moved the personal workspace section switcher below the migration banner and aligned it with the active pane controls.
- Added a new Cards view alongside List and Folders for personal and group workspaces.
- Rendered document cards with status badges, metadata pills, tag badges, quick actions, and selection-mode support.
- Added default settings, admin persistence, and admin UI controls for `enable_no_auth_external_healthcheck` and `/external/healthcheckz`.

## Validation

- Added functional regression coverage in `functional_tests/test_no_auth_external_healthcheck_admin_setting.py`.
- Added UI regression coverage in `ui_tests/test_workspace_document_cards_layout.py`.
- Updated `ui_tests/test_workspace_sidebar_endpoint_links.py` to verify rounded desktop tabs instead of square tabs.
- Verified the changed HTML, CSS, JavaScript, and Python files with editor diagnostics.

## Impact Analysis

- Workspace document browsing now has a denser, more actionable card presentation without removing the folder browser.
- Personal workspace layout feels more coherent because the switcher now sits closer to the content it controls.
- Administrators can independently enable authenticated and unauthenticated external health probes.
- Desktop workspace tabs match the expected visual language again.