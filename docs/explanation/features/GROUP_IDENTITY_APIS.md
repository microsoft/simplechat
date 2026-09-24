# Group Identity APIs (v0.261.139)

## Overview

Immutable-target routes for group workspace identities: the reusable
credentials that group File Sync sources and group actions bind to. The V2
group workspace can list, create, edit and delete them without the classic
interface.

Implemented in version: **0.261.139**, tracked in
`application/single_app/config.py`.

The routes use the existing group workspace identities Cosmos container,
partitioned by group. No new setting, container or index is required.

## Why new routes

The legacy `/api/workspace-identities/group/identities[/<id>]` routes act on the
account's **active** group (`require_active_group`). Their writes are
unconditional: an update reads, then upserts, so an identity deleted meanwhile
is recreated. Their errors return the raw exception text.

The new routes name the group in the path, never read the active group, make
every write conditional, and return stable messages. The legacy routes are
unchanged, because the classic workspace still uses them.

## Availability and roles

- **Availability:** Semantic Kernel is on for the tenant, **or** File Sync is
  enabled for this group. One predicate, `group_identities_available` in
  `functions_group_identity_policy.py`, decides this for the workspace context's
  Identities section and every route. Otherwise every route refuses with 403 and
  "Identities require File Sync or Semantic Kernel."
- **Roles:** Owner, Admin and DocumentManager, **for reads and writes**. An
  ordinary member cannot list identities, as in the classic workspace.
- **Status:** managers can read in `active`, `locked` and `upload_disabled`
  groups, and write only in `active` ones. `inactive` or unrecognized is 403.

## Routes

| Method and path | Purpose | Success |
|---|---|---|
| `GET /api/groups/G/identities` | List | `{"identities": [...]}` |
| `POST /api/groups/G/identities` | Create | 201 `{"identity": ...}` |
| `GET /api/groups/G/identities/I` | Read one | `{"identity": ...}` |
| `PATCH /api/groups/G/identities/I` | Update | `{"identity": ...}` |
| `DELETE /api/groups/G/identities/I` | Delete | `{"success": true}` |

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required` and
`@enabled_required("enable_group_workspaces")`. No route accepts a query
parameter. GET takes no body, and POST, PATCH and DELETE take a JSON object with
no duplicate keys.

## The identity shape

Each identity is the sanitized stored record. That includes `id`,
`identity_id`, `scope_type`, `group_id`, `name`, `description`, `provider`,
`source_type`, `usage_contexts`, `supported_source_types`, `metadata`, and the
audit fields. It also carries `credentials`:

```json
{"auth_type": "...", "username": "", "domain": "", "identity": "",
 "password_stored": true, "secret_stored": false,
 "password": "Stored_In_KeyVault", "secret": ""}
```

Stored secrets are never returned; a stored value appears as the placeholder.
The routes add three things:

- `etag`, for conditional writes;
- `identity_actions`, the subset of `edit` and `delete` the caller may perform;
- **normalized `usage_contexts` and `supported_source_types`**, exactly as the
  save-time checks read them. An older record without `usage_contexts` reports
  `["action"]`, and the aliases `agent`, `plugin` and `general` read as
  `action`. So a client filtering on them never hides an identity the server
  would accept.

The group's management operations (`create`, `edit`, `delete`) are published as
`identity_management` in the selected-group workspace context.

## Writes

- **Allowed fields:** `name`, `description`, `provider`, `source_type`,
  `usage_contexts`, `supported_source_types`, `metadata` and `credentials`.
  Anything else is 400. That includes `auth`, which the legacy normalizer
  accepts as an alias.
- **Conditional:** PATCH carries `expected_etag`, and the DELETE body is exactly
  `{"expected_etag": "..."}`. A missing etag is 400. A stale one is 409:

  ```json
  {"error": "This workspace identity was modified. Reload and try again.",
   "error_code": "etag_conflict"}
  ```

  Nothing is written. An identity deleted meanwhile is 404 and is never
  recreated.
- **Secrets:** a placeholder or blank value keeps the stored secret. When
  secret storage is on, a new value is stored in Key Vault under a **fresh**
  name before the conditional write. So a refused write (409 or 404) never
  changes the credential the stored identity still points at, and the unused
  new secret is deleted. After a successful write, the replaced secret is
  deleted. A delete removes the identity's secrets, best effort and logged.
- **Validation:** four reviewed messages are returned as they are:
  - "Unsupported workspace identity authentication type"
  - "Selected authentication type is not available for the selected identity uses"
  - "Username/password identities require a password"
  - "This identity type requires a secret value"

  Every other invalid request is "The workspace identity details are not
  valid."

## Delete while in use

If a File Sync source or an action in the same group still uses the identity,
the delete is refused, and nothing is deleted:

```json
{"error": "This workspace identity is still in use.",
 "error_code": "identity_in_use",
 "references": [{"kind": "file_source" | "action", "id": "...", "name": "..."}]}
```

The refusal is logged with `log_workspace_identity_reference_block`, as the
classic route does.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_group_identity_apis.py` | 72 | Role, status and availability for every route; strict requests; `auth` and other unknown fields refused; the exact DELETE body; conditional writes, including races where a write or delete lands mid-request; fresh-name secret staging with exact Key Vault names, as positive controls; a refused write leaves the live secret unchanged; superseded and staged secrets cleaned up; the normalization of `usage_contexts` and `supported_source_types`, including older records; the reviewed validation messages; the in-use 409 for File Sync sources and actions |
| `functional_tests/test_group_identity_transport.py` | 5 | None of the new routes can fall through to a legacy identity route |
| `functional_tests/test_v2_group_workspace_context.py` | 57 | `identity_management` for each role and status, and agreement between the context and the list response |
| `functional_tests/test_action_workspace_identity_scoping.py`, `test_group_workspace_identities_permissions.py`, `test_file_sync_azure_files_identity.py` | 6, 4, 5 | Existing identity behaviour, unchanged |

Integrated with the branch tip, 60 related functional test files show exactly the
failures already present there: zero regressions. Route policy passes 8/8, 4/4
and 2/2, and the broken-access-control scanner passes on every changed backend
module.

## Related

- [V2 Group Identities](V2_GROUP_IDENTITIES.md)
- [Group Action APIs](GROUP_ACTION_APIS.md)
