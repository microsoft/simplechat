# Public Connection APIs (v0.261.182)

## Overview

Routes that name the public workspace in the path, for its **identities** (the
reusable credentials a File Sync source binds to) and its **File Sync
sources**. The V2 public workspace uses them to manage both without the classic
page. See [V2 Public Connections](V2_PUBLIC_CONNECTIONS.md).

Implemented in version: **0.261.182**, tracked in
`application/single_app/config.py`.

The routes use the existing public workspace identity and File Sync containers,
the sync engine, and the `public` Key Vault scope. No new setting, container or
index is required.

The two families follow the group ones closely. This page gives the public
rules and the differences; the shared request and response shapes are in
[Group Identity APIs](GROUP_IDENTITY_APIS.md) and
[Group File Source APIs](GROUP_FILE_SOURCE_APIS.md).

## Why new routes

The classic `/api/workspace-identities/public/<id>/identities[...]` and
`/api/file-sync/public/<id>/sources[...]` routes already name the workspace, but:

- their writes aren't conditional, so two managers' saves overwrite each other;
- they check no workspace status;
- the identity routes check no feature flag, in any scope.

Changing their response shapes would break the classic page's shared
`workspace-identities.js` and `workspace-file-sync.js`, which every scope uses.
So the classic and admin routes are unchanged, and V2 uses the new routes.

## Availability and roles

- **Feature gates:** every route requires `enable_public_workspaces`, and File
  Sync enabled for the workspace (`is_file_sync_enabled_for_public_workspace`,
  which also applies `file_sync_public_admin_only` to the caller). A public
  workspace has no actions, so File Sync is the only consumer of a public
  identity, and it gates both families. One predicate per family decides it for
  the routes and the workspace context:
  - `public_identities_available`, refusing with 403 "Identities require File
    Sync.";
  - `public_file_sources_available`, refusing with 403 "File sources require
    File Sync.".
- **Roles:** Owner, Admin and DocumentManager, **for reads and writes**. A
  reader (the `User` role every signed-in user holds) gets 403 "You do not have
  access to the selected public workspace.", and an unknown workspace is 404
  "The selected public workspace was not found.".
- **Status:** managers read in `active`, `locked` and `upload_disabled`
  workspaces. They create, edit, delete, sync, test and browse only in `active`
  ones, as the group routes allow. `inactive` or an unrecognized status is 403,
  through an explicit allowlist, never the classic status helper.
- **Hints:** `identity_management` and `file_source_management`,
  `{"schema_version": 1, "operations": [...]}`, in the public workspace context
  and in each list response. Each identity carries `identity_actions` (`edit`,
  `delete`), and each source `source_actions` (`edit`, `delete`, `sync`,
  `test`), computed fresh on every response.

## Routes

`W` is the public workspace ID.

| Method and path | Purpose |
|---|---|
| `GET` and `POST /api/public-workspaces/W/identities` | List; create (201) |
| `GET`, `PATCH` and `DELETE /api/public-workspaces/W/identities/I` | Read, update, delete one |
| `GET` and `POST /api/public-workspaces/W/file-sources` | List; create (201) |
| `GET`, `PATCH` and `DELETE /api/public-workspaces/W/file-sources/S` | Read, update, delete one |
| `POST /api/public-workspaces/W/file-sources/test-connection` | Test an unsaved configuration |
| `POST /api/public-workspaces/W/file-sources/S/test-connection` | Test a saved source |
| `POST /api/public-workspaces/W/file-sources/browse` | Browse, unsaved |
| `POST /api/public-workspaces/W/file-sources/S/browse` | Browse a saved source |
| `POST /api/public-workspaces/W/file-sources/S/sync` | Sync now |
| `GET /api/public-workspaces/W/file-sources/S/runs` | Run history |
| `POST /api/public-workspaces/W/file-sources/S/ignore-path` | Ignore or restore a remote path |
| `GET /api/public-workspaces/W/file-source-options` | Editor options |

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required` and
`@enabled_required("enable_public_workspaces")`, plus its family's boundary,
which turns every failure into a stable message. No route accepts a query
parameter, and bodies are JSON objects with no duplicate keys.

## Identities

The shape, the allowed fields and the write rules are the group's:
- PATCH carries `expected_etag`, and the DELETE body is exactly
  `{"expected_etag": "..."}`. A stale etag is 409 `etag_conflict`, "This
  workspace identity was modified. Reload and try again.", and nothing is
  written.
- Stored secrets are never returned. A placeholder or blank value keeps the
  stored secret, and a new one is staged in Key Vault under a fresh name before
  the conditional write.
- A delete is refused while a File Sync source in the same workspace still uses
  the identity: 409 `identity_in_use`, with the referencing sources. A public
  workspace has no actions, so a reference is always a `file_source`.

## File sources

The shape, `config_revision`, identity binding, deliberate deletion, sync, runs,
ignored paths, test and browse are the group's:
- Edits carry `expected_config_revision`; a stale one is 409 and nothing is
  written.
- A delete names `delete_associated_files` (`true` or `false`) and is refused
  while a run is active. The associated documents are removed through the
  shared File Sync deletion path, which deletes each one as a public document,
  with the counts and partial outcome in `delete_result`.
- A source binds only to an identity of the same public workspace.

Test and browse need the manager role in an active workspace, so nobody else
can pair a destination with a stored identity's credentials.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_public_identity_apis.py` | 72 | Roles, statuses, the feature and File Sync gates, strict bodies, conditional writes, secrets retained, replaced or cleared, another workspace's identity as 404, the in-use refusal |
| `functional_tests/test_public_file_source_apis.py` | 60 | The group file source coverage under public rules: roles, gates, statuses, secrets in the `public` scope, config conflicts, deletes with and without files, sync, runs, ignore, browse and test |
| `functional_tests/test_public_identity_transport.py`, `test_public_file_source_transport.py` | 5, 14 | The new routes and the classic ones can't match each other |
| `functional_tests/test_public_identity_fixture_parity.py`, `test_public_file_source_fixture_parity.py` | 10, 11 | The V2 browser fixtures answer as the routes do |
| `functional_tests/test_public_context_fixture_parity.py` | | The two hints and sections for every role and status, with File Sync on and off |

## Related

- [V2 Public Connections](V2_PUBLIC_CONNECTIONS.md)
- [Group Identity APIs](GROUP_IDENTITY_APIS.md)
- [Group File Source APIs](GROUP_FILE_SOURCE_APIS.md)
