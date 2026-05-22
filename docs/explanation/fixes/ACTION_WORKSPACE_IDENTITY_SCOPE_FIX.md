# Action Workspace Identity Scope Fix

Fixed/Implemented in version: **0.241.095**

Related version update: `application/single_app/config.py` was incremented to `0.241.095` for this fix.

## Issue Description

Reusable workspace identities existed for File Sync, but the action creation workflow did not load or bind the scoped identity catalog. SQL actions still required action-local credentials, so an action-capable identity selected in the identity manager did not appear in the action modal.

## Root Cause Analysis

The identity framework already stored personal, group, public, and global identities with usage metadata, and File Sync resolved them through `functions_workspace_identities.py`. The action workflow did not have equivalent integration:

- The shared action modal did not call the workspace identity APIs.
- Personal, group, and global action save paths did not validate identity references against their owning scope.
- SQL connection testing and runtime plugin loading could not resolve identity-backed credentials.
- Identity deletion only checked File Sync references and skipped global identities entirely.

## Technical Details

Files modified:

- `application/single_app/functions_workspace_identities.py`
- `application/single_app/functions_personal_actions.py`
- `application/single_app/functions_group_actions.py`
- `application/single_app/functions_global_actions.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/route_backend_workspace_identities.py`
- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/templates/_plugin_modal.html`
- `application/single_app/static/json/schemas/plugin.schema.json`
- `application/single_app/semantic_kernel_plugins/sql_query_plugin.py`
- `application/single_app/semantic_kernel_plugins/sql_schema_plugin.py`
- `application/single_app/semantic_kernel_plugins/plugin_health_checker.py`

Code changes summary:

- Added `identity_id` as the explicit action manifest reference for reusable identities.
- Added scope-aware action identity validation and runtime hydration helpers.
- Added personal, group, and global action save validation so identities cannot cross scope boundaries.
- Added SQL action modal identity selectors for personal, group, and global action contexts.
- Added SQL connection test identity resolution without trusting caller-supplied group or global scope ids.
- Updated SQL plugin runtime connection building to preserve managed identity auth mode.
- Updated SQL plugin health validation so connection-string identities do not require copying the connection string into the action manifest.
- Updated identity deletion safeguards to block deletes when identities are referenced by actions or File Sync.
- Limited public identities to public File Sync and global identities to global actions.

## Validation

Test coverage:

- `functional_tests/test_action_workspace_identity_scoping.py`
- `ui_tests/test_workspace_action_identity_modal.py`
- `functional_tests/test_file_sync_capability.py` version assertion updated for `0.241.095`

Before:

- A SQL action could not select an existing action-capable identity.
- Action saves could not validate identity scope ownership.
- Runtime action loading had no server-side identity hydration path.
- Global identities could be deleted without checking action references.

After:

- Personal actions use only personal identities.
- Group actions use only identities from the active group.
- Public workspace identities remain File Sync-only.
- Global identities use global actions only.
- Action manifests store identity references instead of copied secrets.
