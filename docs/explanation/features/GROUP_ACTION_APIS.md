# Group Action APIs (v0.261.137)

## Overview

Immutable-target routes for group actions, and a fix to who may test a saved
group action.

Implemented in version: **0.261.137**, tracked in
`application/single_app/config.py`.

Dependencies are the existing group actions Cosmos container (partitioned by
`/group_id`), current group membership, and the group action settings described
below. No new setting, container, or index is required.

## Why new routes

The legacy `/api/group/plugins` routes find their target from an optional
`?group_id`, and fall back to the user's stored active group when it is absent.
Writes through them upsert unconditionally, so a second editor silently
overwrites the first.

The new routes name the group in the path, so they can only act on the group the
request names. An older server that lacks them returns 404 instead of acting on
the wrong group. Every write is conditional.

The legacy routes keep their paths and behaviour, because the classic group
workspace still uses them.

## Availability

The whole native surface is available only when all of these hold:

- `enable_group_workspaces`, `enable_semantic_kernel` and
  `per_user_semantic_kernel` are on;
- `allow_group_agents` and `allow_group_plugins` are on;
- the caller passes `governance_group_actions` for group scope.

One predicate, `group_actions_available` in `functions_group_action_policy.py`,
decides this. The workspace context uses it for `sections.actions`, the
`action_management` hint uses it, and every route below uses it.

When it fails, every route refuses with 403 and the section's own reason:
"Group actions are not enabled." or "Your administrator has restricted access to
this capability." No data is returned.

## Who may do what

| | Read | Create, edit, delete, test |
|---|---|---|
| Owner, Admin | yes | yes, in an `active` group |
| DocumentManager, User | yes | no |

When `require_owner_for_group_agent_management` is on, only the Owner may
create, edit, delete, or test. This mirrors the classic interface's
`canManagePlugins()` and `groupAllowsModifications()`.

| Status | Read | Write |
|---|---|---|
| `active` | yes | Owner, Admin |
| `upload_disabled`, `locked` | yes | no |
| `inactive`, or unrecognized | no | no |

An unrecognized status is treated as unavailable, never as active.

## Immutable API family

All paths start `/api/groups/G/actions`. `G` is the sole target.

| Method and path | Purpose | Success |
|---|---|---|
| `GET /api/groups/G/actions` | List the group's actions | 200, `{"actions": [...]}` |
| `GET /api/groups/G/actions/A` | Read one action | 200, editor resource |
| `POST /api/groups/G/actions` | Create an action | **201**, editor resource |
| `PATCH /api/groups/G/actions/A` | Update an action | 200, editor resource |
| `DELETE /api/groups/G/actions/A` | Delete an action | 200, `{"success": true}` only |
| `GET /api/groups/G/actions/types` | Action type catalogue | 200, `{"types": [...]}` |
| `GET /api/groups/G/action-options` | Editor defaults for secret reminders | 200, `{"secret_reminders": {...}}` |

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required`, and
`@enabled_required("enable_group_workspaces")`.

Requests are strict. **No route accepts a query parameter.** GET and DELETE
reject a request body. POST and PATCH require a JSON object and reject duplicate
keys. Each of these is a 400.

| Failure | Status |
|---|---|
| Unknown group | 404 |
| Caller is not a member | 403 |
| Status does not allow reading | 403 |
| Surface unavailable (see above) | 403, with the section's reason |
| Caller lacks a write role, or the status does not allow the write | 403 |
| Unknown action | 404 |

## Editor resources and writes

The routes use the same editor contract as personal actions, extended to group
scope in `functions_workspace_authoring.py`.

A read, create, or update returns:

```json
{"record": {...}, "revision": "<etag>", "secret_paths": ["/auth/key"], "read_only": false}
```

`read_only` is true for anyone who cannot write. Stored secrets appear as
`***REDACTED***`, and `secret_paths` lists them as JSON pointers.

POST and PATCH send:

```json
{"updates": {...}, "expected_revision": "<etag>", "clear_secret_paths": [], "removed_paths": []}
```

- `updates` names only changed leaves. Ownership, scope, IDs and audit fields
  cannot be changed, and the server allocates the ID of a new action.
- A masked secret sent back unchanged keeps its stored value. A secret is removed
  only through `clear_secret_paths`. A client can never supply a Key Vault
  reference.
- Group action secrets are stored in the **group's** Key Vault namespace, never
  the saving member's. Replaced secrets are cleaned up only after the write
  succeeds.
- Names must be unique within the group, and must not match a global action's
  name. The comparison with global names ignores case.

## Conflicting edits

| Case | Result |
|---|---|
| PATCH without `expected_revision` | 400 |
| PATCH with a revision that is no longer current | **409**, nothing written |
| DELETE | No body and no revision. The server deletes against the revision it has just read, so a change between that read and the delete is a **409** |
| Create or rename to a name already in use | 409 |

Every 409 carries the editor engine's single message, "This resource changed.
Reload it before saving.", including the duplicate-name case. On a 409, reload
and reapply the change. The V2 editor keeps the draft open.

## Activity log

Since **0.261.138**, every committed create, update and delete records the same
activity event as the classic group routes:

- `log_action_creation`, `log_action_update` or `log_action_deletion`;
- with `scope='group'` and the group named in the path;
- with the action's ID, name and, except on delete, its type.

A refused write (400, 403 or 409) records nothing. A failure to record activity
is logged as a warning and never undoes the committed change. In 0.261.137 these
routes recorded no activity.

## Per-action operations

Each listed action carries `action_actions`, computed fresh on every request and
never stored. It is `edit`, `delete` and `test` for a writer in an available,
`active` group, and empty otherwise. A seam test pins that the projector calls
the policy function rather than using a constant.

## Provided (global) actions

When `merge_global_semantic_kernel_with_workspace` is on, the list also includes
global actions, marked `is_global: true` with empty `action_actions`.

`GET /api/groups/G/actions/<global id>` opens one read-only: `read_only: true`,
`is_global: true`, `action_actions: []`.

| Case | Result |
|---|---|
| Merge off, unknown ID, or a disabled global action | 404 |
| Governance denies the global action | 403, as the personal `scope=global` read does |
| PATCH or DELETE on a global ID | 404; it is not a group action, and nothing is written |

## Type catalogue

`GET /api/groups/G/actions/types` returns the same enriched editor catalogue as
the personal editor: each type has `type`, `display`, `description`,
`allowed_auth_types`, `additional_fields_schema` and `metadata_schema`, filtered
by `governance_group_actions`. It is sent with `Cache-Control: no-store`.

It is a **read** capability, available to every member role, because the
collection and details page render type labels for readers too. The legacy
`/api/group/plugins/types` keeps its Owner/Admin gate.

## Editor defaults

`GET /api/groups/G/action-options` returns the tenant's Key Vault reminder
defaults the group action editor needs:

```json
{"secret_reminders": {"storage_enabled": true, "reminders_enabled": true,
  "require_expiration": false, "lead_days": 30, "contact_email": ""}}
```

It is a read capability with the same gate as the list, and is sent with
`Cache-Control: no-store`. It sits on its own path segment, so it can never
collide with an action ID.

The values come from `build_secret_reminder_defaults`, the one helper the
personal editor options also use: `lead_days` is clamped to 1 to 3650 (default
30) and `contact_email` is capped at 254 characters. Before this route existed,
the group editor read these values from the personal agent settings response,
which also carries personal data.

## Connection tests

Connection tests keep their existing routes (`/api/plugins/test-*-connection`
and `/api/plugins/mcp/discover`). A group test from the V2 editor sends
`action_scope: "group"` and a top-level `group_id`.

When `group_id` is present, it is authoritative for the whole request: loading a
saved action, the identity it uses, and its Key Vault context. The active group
is never used as a fallback. The caller must hold `test` in that group, which
means the write roles, an `active` status and an available surface.

- A saved action from a different group is 403.
- A `group_id` sent with a non-group action is 403.

Requests without `group_id`, which is everything the classic interface sends,
still target the active group, but now require the same roles.

> **Fixed in this release.** Group connection tests and MCP discovery admitted
> every group member, although they can load stored credentials:
>
> - testing a **saved** action loads its stored configuration;
> - an unsaved test that names a group identity resolves that identity's
>   secrets.
>
> They now require the roles that editing needs: Owner or Admin, or Owner alone
> under the owner-only setting. The group MCP preconfiguration list shares the
> same check, so it requires the same roles. The classic interface offers all of
> these only inside the action editor, which only those roles can open, so no
> supported flow changes. See the
> [fix write-up](../fixes/GROUP_ACTION_TEST_ROLE_ALIGNMENT_FIX.md).

## Workspace context

The group workspace context gains `action_management`,
`{schema_version: 1, operations: [...]}`. Its operations are `create`, `edit`,
`delete` and `test` for a writer in an available, `active` group, and empty
otherwise.

It is an interface hint, never an authorization grant. Every route checks
availability, role and status on each request.

## Testing and validation

| Suite | Coverage |
|---|---|
| `functional_tests/test_group_action_apis.py` | Roles, the owner-only setting, status, 404 vs 403, the availability flags and governance, conditional writes, the DELETE shape, strict requests, secrets, the type catalogue for every member, provided actions |
| `functional_tests/test_group_action_named_group_test_resolution.py` | Connection tests use the named group, never the active group; readers, locked and unknown groups are refused; the legacy path is unchanged without `group_id` |
| `functional_tests/test_group_action_saved_test_role_policy.py` | Saved-action tests require the edit roles |
| `functional_tests/test_group_action_hint_seam.py` | `action_actions` is computed from policy |
| `functional_tests/test_group_action_transport.py` | No new route can match a legacy route |
| `functional_tests/test_personal_action_save_helper_regression.py` | Personal action create and update still save |
| `functional_tests/test_v2_group_workspace_context.py` | The context's advertised operations and `sections.actions`, from the same predicate the routes use |

On the integrated tree, which includes the React V2 base-branch merge:

- the group action suites pass **94** cases;
- the workspace context suite passes **48**, and the delegation permission suite **113**;
- the personal authoring guards pass **165**, including the regression test that
  personal action create and update still save.

Route policy passes **8/8, 4/4, 2/2**. The broken-access-control scanner passes
on all seven changed backend modules, and no changed module adds an undefined
name.

## Related

- [V2 Group Actions](V2_GROUP_ACTIONS.md) — the browser surface
- [Group Action Test Role Alignment Fix](../fixes/GROUP_ACTION_TEST_ROLE_ALIGNMENT_FIX.md)
- [Group Prompt APIs](GROUP_PROMPT_APIS.md)
