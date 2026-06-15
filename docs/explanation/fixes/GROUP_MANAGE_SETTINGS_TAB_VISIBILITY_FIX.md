# Group Manage Settings Tab Visibility Fix (v0.241.204)

Fixed/Implemented in version: **0.241.204**

Related config.py version update: `application/single_app/config.py` now sets `VERSION = "0.241.204"`.

## Issue Description

The group manage page showed the Settings tab for group owners and admins, but clicking the tab displayed an empty pane. Group retention policy controls and the group file download disable control were present in the template, but remained hidden.

## Root Cause Analysis

The group manage template intentionally rendered the Settings pane with Bootstrap's `d-none` class until the current user's group role was loaded. The JavaScript removed `d-none` from the Settings tab button for owners and admins, but did not remove it from the `#settings` pane itself. This produced a silent blank tab with no JavaScript error.

The group and public workspace download settings PATCH APIs also returned a successful HTTP 200 response without the `success` flag that their frontend save handlers already required.

## Technical Details

### Files Modified

- `application/single_app/static/js/group/manage_group.js`
- `application/single_app/route_backend_groups.py`
- `application/single_app/route_backend_public_workspaces.py`
- `application/single_app/config.py`
- `functional_tests/test_group_manage_settings_tab_visibility.py`

### Code Changes Summary

- Unhid the group manage `#settings` pane alongside the Settings tab item for group owners and admins.
- Kept the group Settings pane hidden for non-admin group roles.
- Updated the group download settings route to use `assert_group_role(..., allowed_roles=("Owner", "Admin"))` at the write boundary.
- Added `success: true` to group and public download settings PATCH responses so the existing frontend save handlers show success.
- Bumped `config.py` from `0.241.203` to `0.241.204`.

## Testing Approach

- Added a functional static regression test that verifies group manage settings visibility wiring, download settings API response contracts, and version/documentation traceability.

## Impact Analysis

Group owners and admins can now see and manage retention policy settings and per-group file download disable settings from the group manage page. Public workspace download settings keep the same UI behavior, with a corrected successful save response.

## Validation

- `python functional_tests/test_group_manage_settings_tab_visibility.py`
- `python -m py_compile application/single_app/route_backend_groups.py application/single_app/route_backend_public_workspaces.py functional_tests/test_group_manage_settings_tab_visibility.py application/single_app/config.py`
- `node --check application/single_app/static/js/group/manage_group.js`