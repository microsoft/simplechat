# Group And Public Workspace Download Settings Visibility Fix (v0.242.057)

Fixed/Implemented in version: **0.242.057**

Related config.py version update: `application/single_app/config.py` now sets `VERSION = "0.242.057"`.

## Issue Description

The Manage Group and Manage Public Workspace Settings tabs showed the local File Download Settings section even when administrators had not enabled file downloads for that group or public workspace. Owners and admins could see a local disable switch for a feature that was not actually available.

## Root Cause Analysis

The management templates rendered the local `disable_file_downloads` controls unconditionally for workspace owners and admins. The frontend loaded only the workspace-local disable value, while the backend PATCH routes accepted local disable updates without checking whether the admin-level download policy enabled downloads for that target workspace.

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_groups.py`
- `application/single_app/route_backend_public_workspaces.py`
- `application/single_app/templates/manage_group.html`
- `application/single_app/templates/manage_public_workspace.html`
- `application/single_app/static/js/group/manage_group.js`
- `application/single_app/static/js/public/manage_public_workspace.js`
- `application/single_app/config.py`
- `functional_tests/test_group_manage_settings_tab_visibility.py`
- `ui_tests/test_manage_group_page_branding.py`
- `ui_tests/test_manage_public_workspace_page_load.py`

### Code Changes Summary

- Added admin-policy helpers that determine whether file downloads are enabled for a specific group or public workspace before applying local owner/admin disable settings.
- Added `file_downloads_admin_enabled` to the manage page API payloads.
- Hid the local File Download Settings sections by default and only revealed them when the API reports that admin downloads apply to the current workspace.
- Blocked download settings PATCH calls when administrators have not enabled downloads for the current group or public workspace.
- Bumped `config.py` to `0.242.057`.

## Validation

### Testing Approach

- Extended the source-level functional regression for group/public management settings to verify backend admin gates, hidden default template sections, frontend visibility toggles, and documentation/version traceability.
- Extended manage group and manage public workspace UI tests to assert the local download settings section remains hidden when the API reports downloads are not admin-enabled.

### Before/After Comparison

- Before: owners/admins saw a file download disable switch even when file downloads were globally off or not assigned to their workspace.
- After: owners/admins only see the local file download disable section after administrators enable downloads for that specific group or public workspace.

### Test Results

- `python functional_tests/test_group_manage_settings_tab_visibility.py`
- `python -m py_compile application/single_app/functions_settings.py application/single_app/route_backend_groups.py application/single_app/route_backend_public_workspaces.py application/single_app/config.py functional_tests/test_group_manage_settings_tab_visibility.py functional_tests/test_plugin_tool_agent_security_audit.py`
- `node --check application/single_app/static/js/group/manage_group.js`
- `node --check application/single_app/static/js/public/manage_public_workspace.js`