# Workspace Identities

Implemented in version: **0.241.095**
Initial foundation: **0.241.091**
Action binding implemented in: **0.241.095**

## Overview

Workspace identities are reusable authentication profiles for personal, group, public, and global capabilities. They are intentionally not File Sync-specific: File Sync sources and actions can reference the same identity catalog instead of each feature creating its own credential silo.

Fixed/Implemented in version: **0.241.095**

Version reference: `application/single_app/config.py` was updated to `0.241.095` when action identity binding was implemented.

## Dependencies

- Workspace identity APIs require an authenticated user.
- Group identities require an active group role of Owner, Admin, or DocumentManager.
- Public workspace identities require Owner, Admin, or DocumentManager access to the target public workspace and are limited to File Sync usage.
- Global identities are admin-managed and are limited to global actions. Global identities do not participate in File Sync.
- Secrets use the existing Key Vault dynamic secret system when Key Vault storage is enabled.

## Technical Specifications

Identity records are stored in scope-specific Cosmos DB containers:

- `personal_workspace_identities`, partitioned by `/user_id`
- `group_workspace_identities`, partitioned by `/group_id`
- `public_workspace_identities`, partitioned by `/public_workspace_id`
- `global_workspace_identities`, partitioned by `/global_id`

The route layer exposes generic identity APIs:

- `/api/workspace-identities/personal/identities`
- `/api/workspace-identities/group/identities`
- `/api/workspace-identities/public/<public_workspace_id>/identities`
- `/api/admin/workspace-identities/global/identities`
- `/api/admin/workspace-identities/<scope_type>/<scope_id>/identities`

Each identity carries usage metadata behind the scenes, but the UI presents it as simple **Used For** checkboxes. Personal and group identities can be used for File Sync and Actions. Public workspace identities are constrained to File Sync. Global identities are constrained to Actions so global credentials cannot accidentally become sync credentials.

Supported identity auth types in the catalog include username/password, anonymous, API key, bearer token, client secret, connection string, and managed identity. File Sync currently only consumes SMB-compatible username/password and anonymous identities. Actions consume API key, bearer token, client secret, connection string, managed identity, and username/password identities. Username/password identities show the domain as optional with helper text because not every account requires a domain. Managed identity selection does not collect a client ID; client IDs are collected only for client-secret service identity scenarios.

## Usage Instructions

Users manage identities from the **Identities** tab in personal, group, and public workspace pages. SimpleChat admins manage global identities from the **Global Identities** tab in Admin Settings. Add, view, and edit flows open in a Bootstrap modal with grouped cards for identity details, used-for checkbox selection, and authentication. File Sync source setup uses the **Identity and Authentication** card to choose a reusable workspace identity or source-local credentials.

Action setup now uses the same identity catalog. Personal actions can use personal identities, group actions can use identities from the active group, and global actions can use global identities. Public workspace identities are not exposed to actions. Action manifests store only `identity_id` and `auth.type = "identity"`; runtime code resolves secrets through `functions_workspace_identities.py` so credentials are not copied into action records.

## Testing and Validation

- `functional_tests/test_file_sync_capability.py` validates workspace identity containers, global identity routes, File Sync identity consumption, credential redaction, and UI wiring.
- `functional_tests/test_action_workspace_identity_scoping.py` validates action identity scope enforcement, runtime hydration helpers, schema support, and delete-reference guards.
- `ui_tests/test_workspace_file_sync_ui.py` covers the File Sync tab and personal workspace identity tab when UI test environment variables are configured.
- `ui_tests/test_workspace_action_identity_modal.py` covers the personal action modal identity selector and verifies saved SQL actions contain only an `identity_id` reference.

## Version Tracking

Related version update: `application/single_app/config.py` was incremented to `0.241.095`.