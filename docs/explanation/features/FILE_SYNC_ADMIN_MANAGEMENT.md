# File Sync Admin Management

Fixed/Implemented in version: **0.241.069**
Workspace assignment gates implemented in version: **0.241.180**

## Overview

File Sync administration has a dedicated Admin Settings tab for configuring synchronization across personal, group, and public workspaces. The tab separates global sync limits from per-scope access gates and gives SimpleChat admins a way to manage sync sources on behalf of users, groups, and public workspaces.

## Purpose

This feature makes File Sync easier to discover and safer to operate at scale. Admins can enable File Sync per workspace scope, require the PersonalFileSyncUser app role for personal sync, assign specific groups or public workspaces for shared-workspace sync, and decide whether workspace managers can manage their own sources or whether source management is restricted to SimpleChat admins.

## Dependencies

- Redis Cache must be enabled and configured before File Sync is effectively active.
- SMB source connections use the existing File Sync SMB support.
- Group and public workspace source management requires existing workspace records.
- The `PersonalFileSyncUser` app role must be created on the SimpleChat app registration before enabling the personal require-role toggle.
- Group and public workspace File Sync access is controlled by Admin Settings assignment lists, not group/public app roles.
- Version was updated in `application/single_app/config.py` to `0.241.180` for workspace assignment gates.

## Technical Specifications

### Architecture

- Admin Settings now includes a top-level File Sync tab instead of embedding File Sync under Workspaces.
- The File Sync settings model uses a personal app-role requirement and group/public workspace assignment gates:
  - `file_sync_personal_require_app_role`
  - `require_group_assignment_for_file_sync`
  - `file_sync_allowed_group_ids`
  - `require_public_workspace_assignment_for_file_sync`
  - `file_sync_allowed_public_workspace_ids`
- Local allow-list and blocklist settings are no longer enforced or rendered in the File Sync admin UI.
- The only active File Sync app role value is `PersonalFileSyncUser`.
- New admin-only management flags control whether self-service workspace source management is available:
  - `file_sync_personal_admin_only`
  - `file_sync_group_admin_only`
  - `file_sync_public_admin_only`
- Scheduled File Sync runs for group and public workspace sources are skipped when the corresponding assignment requirement is enabled and the source workspace is no longer assigned.

### API Endpoints

Admin target search endpoints:

- `GET /api/admin/file-sync/users/search`
- `GET /api/admin/file-sync/groups/search`
- `GET /api/admin/file-sync/public-workspaces/search`

Admin-managed source endpoints:

- `/api/admin/file-sync/personal/<target_user_id>/sources`
- `/api/admin/file-sync/group/<group_id>/sources`
- `/api/admin/file-sync/public/<public_workspace_id>/sources`

Each admin source API supports the same source list, create, update, delete, test connection, sync now, and run history workflows used by the workspace File Sync UI.

### File Structure

- `application/single_app/functions_file_sync.py`: File Sync config normalization, personal app-role checks, workspace assignment checks, scheduled-run assignment filtering, and admin-only management gating.
- `application/single_app/route_backend_file_sync.py`: admin target search and admin-managed source APIs.
- `application/single_app/templates/admin_settings.html`: dedicated File Sync tab, per-scope cards, assignment modals, target manager modal.
- `application/single_app/static/js/admin/admin_settings.js`: assignment list modals, target search, and admin source manager modal wiring.
- `application/single_app/static/js/workspace/workspace-file-sync.js`: reusable source manager initializer.

## Usage Instructions

1. Open Admin Settings and select File Sync.
2. Enable File Sync globally after Redis Cache is configured.
3. Enable the desired scopes: Personal, Group, and/or Public.
4. Create and assign `PersonalFileSyncUser` before enabling the personal require-role toggle.
5. For group File Sync, enable Require Group Assignment to Use File Sync and choose groups with Manage Groups.
6. For public workspace File Sync, enable Require Public Workspace Assignment to Use File Sync and choose public workspaces with Manage Public Workspaces.
7. Turn on admins-only source management for any scope that should be centrally managed.
8. Use the Manage Sources controls to search for a target and open the source manager modal.

## Testing and Validation

Coverage was updated in:

- `functional_tests/test_file_sync_capability.py`
- `ui_tests/test_workspace_file_sync_ui.py`
- `ui_tests/test_admin_file_sync_settings_ui.py`

Validation covers the dedicated admin tab, personal app-role UI, group/public assignment UI, removal of local allow-list and blocklist wiring, admin target search endpoints, admin source management endpoints, scheduled-run assignment filtering, and reusable source manager initialization.

## Known Limitations

- Personal admin source management targets users by user ID. The target search picker fills this automatically.
- Admin-managed personal sources do not create or validate the user's profile record; they use the selected user ID as the File Sync scope.
- Existing stored allow-list and blocklist values may remain in persisted settings data but no longer affect File Sync authorization.
