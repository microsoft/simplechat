# Group Action Test Role Alignment Fix

## Issue

Fixed in version: **0.261.137**

Group connection tests and MCP discovery can load stored credentials:

- Testing a **saved** group action loads its stored configuration, including
  credentials held in Key Vault, and runs the connector against it.
- An **unsaved** test that names a group identity (`identity_id`) resolves that
  identity's secrets as values and applies them to the connection it describes.
  Group members can read the `identity_id` of the group's actions.

On the server, both paths admitted all four group roles: Owner, Admin,
DocumentManager and User. So an ordinary member could use a group's stored
credentials against a destination they chose.

Editing a group action requires Owner or Admin, or Owner alone when
`require_owner_for_group_agent_management` is on.

The classic interface only offers Test, discovery and MCP preconfigurations
inside the action editor, which only editors can open
(`static/js/workspace/group_plugins.js:29-41`, `canManagePlugins()` and
`groupAllowsModifications()`). No supported flow gave a member these
capabilities, but the server did not enforce the editor's roles on them.

## Root cause

The group branches of the shared test path asserted the reader role set rather
than the editor role set (`route_backend_plugins.py` at `02b62d07`):

- `_resolve_action_identity_context`, lines 790-799 and the transient branch
  after them. For a saved group action, and for a group test with no saved
  action, it calls
  `assert_group_role(..., allowed_roles=("Owner", "Admin", "DocumentManager", "User"))`
  on the active group.
- `_load_existing_plugin_for_test`, lines 1184-1192. For `scope == 'group'`, it
  calls the same four-role assertion, then
  `get_group_action(active_group, id, return_type=SecretReturnType.NAME)`.

Four callers of `_resolve_action_identity_context` hydrate identity credentials
with `SecretReturnType.VALUE`:

- `_hydrate_sql_test_identity`
- `_prepare_editor_yamcs_test_data`
- `discover_mcp_tools`
- `_prepare_action_test_manifest`

The fifth caller is `get_mcp_server_preconfigurations`.

Every entry point that loads a saved action for a test reaches these branches:

- `POST /api/plugins/mcp/discover`
- `POST /api/plugins/test-sql-connection`
- `POST /api/plugins/test-cosmos-connection`
- `POST /api/plugins/test-yamcs-connection`
- `POST /api/plugins/test-rocksdb-connection`
- Through `_run_action_connection_test` → `_prepare_action_test_manifest`:
  - `POST /api/plugins/test-openapi-connection`
  - `POST /api/plugins/test-azure-maps-connection`
  - `POST /api/plugins/test-blob-storage-connection`
  - `POST /api/plugins/test-databricks-connection`
  - `POST /api/plugins/test-log-analytics-connection`
  - `POST /api/plugins/test-mcp-connection`
  - `POST /api/plugins/test-snowflake-connection`
  - `POST /api/plugins/test-tableau-connection`

The list comes from an AST walk of `route_backend_plugins.py`, following
the `_load_existing_plugin_for_test`, `_load_existing_plugin_for_sql_test`,
`_prepare_action_test_manifest` and `_run_action_connection_test` call chains.

## Fix

Every group test and discovery request now requires the roles that editing
needs: Owner or Admin, or Owner alone under the setting. That covers saved and
unsaved tests, and the preconfiguration list shares the same check. The group
the request applies to depends on its shape:

- **Without `group_id`**, which is everything the classic interface sends: the
  active group, as before, now with the edit roles, whether or not the request
  references a saved action.
- **With a top-level `group_id`**, which is what the V2 editor sends: the new
  `_resolve_group_for_test` decides the group for the whole request, including
  the saved-action load, identity, origin and Key Vault context. It never falls
  back to the active group, and requires `test` in
  `group_action_management_operations(user_id, group, role, settings)`: the write
  roles, an `active` group, and group actions available to the caller. A saved
  action from another group, or a `group_id` sent with a non-group action, is
  403.

Personal and global tests are unchanged.

### Files modified

- `application/single_app/route_backend_plugins.py`: the saved and transient
  group branches; `_resolve_group_for_test`; `requested_group_id` threaded
  through all seven call sites that load a saved action for a test.
- `application/single_app/functions_group_action_policy.py`: the `test`
  operation in `group_action_management_operations`, used by both the test path
  and the native group action routes.

## Compatibility

No supported flow changes. The classic interface never sends `group_id`
(`plugin_modal_stepper.js` sets only `action_scope`). It offers Test, MCP
discovery and preconfigurations only inside the action editor, which only Owner
and Admin can open.

A script or integration that tests group actions, runs group MCP discovery, or
lists group MCP preconfigurations using an ordinary member's account now
receives 403. Use an Owner or Admin account instead.

## Validation

| Suite | Coverage |
|---|---|
| `functional_tests/test_group_action_saved_test_role_policy.py` | Both saved branches and the transient branch require the edit roles and follow the owner-only setting; none keeps the four-role reader set |
| `functional_tests/test_group_action_named_group_test_resolution.py` | Runs the real resolvers. A named group is used without touching the active group. Readers, locked and unknown groups are refused. A saved action from another group is refused. Without `group_id`, User and DocumentManager are refused, Admin is allowed except under the owner-only setting, and Owner is allowed |

Before the fix, the structural test pinned the transient branch to the four-role
reader set; it now pins the opposite. On the integrated tree the two suites pass
**3** and **19** cases. Route policy passes **8/8, 4/4, 2/2**, and the
broken-access-control scanner passes on every changed backend module.

Related: [Group Action APIs](../features/GROUP_ACTION_APIS.md).
