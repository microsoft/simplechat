# File Sync Admin Management

Fixed/Implemented in version: **0.241.069**

## Overview

File Sync administration has a dedicated Admin Settings tab for configuring SMB synchronization across personal, group, and public workspaces. The tab separates global sync limits from per-scope app-role gates and gives SimpleChat admins a way to manage sync sources on behalf of users, groups, and public workspaces.

## Purpose

This feature makes File Sync easier to discover and safer to operate at scale. Admins can enable File Sync per workspace scope, require Entra app roles for higher-risk sync capabilities, and decide whether workspace managers can manage their own sources or whether source management is restricted to SimpleChat admins.

## Dependencies

- Redis Cache must be enabled and configured before File Sync is effectively active.
- SMB source connections use the existing File Sync SMB support.
- Group and public workspace source management requires existing workspace records.
- App roles must be created on the SimpleChat app registration before enabling the matching require-role toggles.
- Version was updated in `application/single_app/config.py` to `0.241.069`.

## Technical Specifications

### Architecture

- Admin Settings now includes a top-level File Sync tab instead of embedding File Sync under Workspaces.
- The File Sync settings model now uses app-role requirement toggles:
  - `file_sync_personal_require_app_role`
  - `file_sync_group_require_app_role`
  - `file_sync_public_require_app_role`
- Local allow-list and blocklist settings are no longer enforced or rendered in the File Sync admin UI.
- Required app role values are:
  - `PersonalFileSyncUser`
  - `GroupFileSyncUser`
  - `PublicWorkspaceFileSyncUser`
- New admin-only management flags control whether self-service workspace source management is available:
  - `file_sync_personal_admin_only`
  - `file_sync_group_admin_only`
  - `file_sync_public_admin_only`

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

- `application/single_app/functions_file_sync.py`: File Sync config normalization, app-role checks, and admin-only management gating.
- `application/single_app/route_backend_file_sync.py`: admin target search and admin-managed source APIs.
- `application/single_app/templates/admin_settings.html`: dedicated File Sync tab, per-scope cards, target manager modal.
- `application/single_app/static/js/admin/admin_settings.js`: target search and admin source manager modal wiring.
- `application/single_app/static/js/workspace/workspace-file-sync.js`: reusable source manager initializer.

## Usage Instructions

1. Open Admin Settings and select File Sync.
2. Enable File Sync globally after Redis Cache is configured.
3. Enable the desired scopes: Personal, Group, and/or Public.
4. Create and assign the relevant Entra app roles before enabling require-role toggles.
5. Turn on require-role toggles for scopes that should be governed by Entra assignments.
6. Turn on admins-only source management for any scope that should be centrally managed.
7. Use the Manage Sources controls to search for a target and open the source manager modal.

## Testing and Validation

Coverage was updated in:

- `functional_tests/test_file_sync_capability.py`
- `ui_tests/test_workspace_file_sync_ui.py`
- `ui_tests/test_admin_file_sync_settings_ui.py`

Validation covers the dedicated admin tab, app-role gate UI, removal of local allow-list and blocklist wiring, admin target search endpoints, admin source management endpoints, and reusable source manager initialization.

## Known Limitations

- Personal admin source management targets users by user ID. The target search picker fills this automatically.
- Admin-managed personal sources do not create or validate the user's profile record; they use the selected user ID as the File Sync scope.
- Existing stored allow-list and blocklist values may remain in persisted settings data but no longer affect File Sync authorization.
