# Group Workspace Identities Permission UI Fix

Fixed/Implemented in version: **0.241.114**

Related version update: `application/single_app/config.py` was incremented to `0.241.114` for this fix.

## Issue Description

Regular group users could see the Group Workspaces Identities tab even though the group identity APIs are limited to group managers. Because those users cannot list or manage workspace identities, the tab could render as an empty or unclear surface.

## Root Cause Analysis

The backend already enforced group identity permissions with the manager roles `Owner`, `Admin`, and `DocumentManager`, but the group workspace navigation did not reflect that role boundary. The shared identity UI also assumed callers were allowed to load identities, so it did not have a dedicated no-permission render state for group users.

## Technical Details

Files modified:

- `application/single_app/config.py`
- `application/single_app/static/js/workspace/workspace-identities.js`
- `application/single_app/templates/group_workspaces.html`
- `application/single_app/templates/_sidebar_nav.html`
- `functional_tests/test_group_workspace_identities_permissions.py`
- `ui_tests/test_group_workspace_identities_permissions.py`

Code changes summary:

- Added permission-aware rendering to the shared workspace identities component with a clear alert when identity management is not allowed.
- Added refresh hooks so the group page can update the identity component after active group or role changes.
- Hid the group Identities tab, section selector option, and sidebar entry by default, then revealed them only for `Owner`, `Admin`, and `DocumentManager` roles.
- Kept the backend manager-only access model intact and documented `DocumentManager` as an allowed role.
- Added functional and UI regression coverage for manager-only group identity navigation.

## Validation

Test coverage:

- `functional_tests/test_group_workspace_identities_permissions.py`
- `ui_tests/test_group_workspace_identities_permissions.py`

Before:

- Regular group users could see an Identities navigation target despite not having API permission.
- The shared identity component had no explicit no-permission UI state.

After:

- Regular group users do not see the Identities navigation in the group tab list, mobile section selector, or sidebar.
- If the identity panel is reached indirectly, it shows `You do not have permission to manage or view identities for this group.`
- Group managers continue to use the existing identity list and management controls.
