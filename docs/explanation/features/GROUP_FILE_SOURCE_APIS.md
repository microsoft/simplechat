# Group File Source APIs (v0.261.142)

## Overview

These are immutable-target routes for a group's File Sync sources: the
connections that keep documents in a group workspace in step with an SMB share,
Azure Files, Azure Blob Storage, or another supported source.

A client can use them to:
- list, create, edit and delete sources for a named group;
- test a connection and browse remote folders;
- start a sync and read run history;
- ignore a remote path.

None of this depends on the account's active group.

Implemented in version: **0.261.142**, tracked in
`application/single_app/config.py`.

The routes use the existing File Sync containers and sync engine. No new
setting, container or index is required. The V2 editor for these routes is a
later release; until then, group sources are managed in the classic group
workspace.

## Why new routes

The legacy `/api/file-sync/group/sources[...]` routes act on the account's
**active** group (`require_active_group`), and their edits are not conditional.
When two managers edit the same source, the later save silently wins.

The new routes are different:
- they name the group in the path, and never read the active group;
- they make edits and deletes conditional on a configuration revision;
- they return stable messages.

The legacy routes keep their behaviour, with one exception: **Sync now** now
explains a refusal, as described below.

## Availability and roles

- **Availability:** File Sync is enabled for this group. That is
  `is_file_sync_enabled_for_group`, which also applies
  `file_sync_group_admin_only` to the caller. One predicate,
  `group_file_sources_available` in `functions_group_file_source_policy.py`,
  decides this for the routes and for the workspace context. When it is off,
  every route refuses with 403 "File sources require File Sync."
- **Roles:** Owner, Admin and DocumentManager, **for reads and writes**. An
  ordinary member can't list sources, as in the classic workspace.
- **Status:**
  - managers can read in `active`, `locked` and `upload_disabled` groups;
  - they can create, edit, delete, sync, test and browse only in `active`
    groups;
  - `inactive` or an unrecognized status is 403.
- **Hints:** the group's operations are published as `file_source_management`,
  `{"schema_version": 1, "operations": [...]}`, a subset of `create`, `edit`,
  `delete`, `sync` and `test`. It appears in the selected-group workspace context
  and in the list response. Each source carries `source_actions`, a subset of
  `edit`, `delete`, `sync` and `test`.

## Routes

| Method and path | Purpose | Success |
|---|---|---|
| `GET /api/groups/G/file-sources` | List | `{"file_sources": [...], "file_source_management": {...}}` |
| `POST /api/groups/G/file-sources` | Create | 201 `{"file_source": ...}` |
| `GET /api/groups/G/file-sources/S` | Read one | `{"file_source": ...}` |
| `PATCH /api/groups/G/file-sources/S` | Update | `{"file_source": ...}` |
| `DELETE /api/groups/G/file-sources/S` | Delete | `{"success": true, "delete_result": {...}}` |
| `POST /api/groups/G/file-sources/test-connection` | Test an unsaved configuration | `{"connection": {...}}` |
| `POST /api/groups/G/file-sources/S/test-connection` | Test a saved source | `{"connection": {...}}` |
| `POST /api/groups/G/file-sources/browse` | Browse, unsaved | `{"browse": {...}}` |
| `POST /api/groups/G/file-sources/S/browse` | Browse a saved source | `{"browse": {...}}` |
| `POST /api/groups/G/file-sources/S/sync` | Sync now | 202 `{"run": ...}` |
| `GET /api/groups/G/file-sources/S/runs` | Run history | `{"runs": [...]}` |
| `POST /api/groups/G/file-sources/S/ignore-path` | Ignore or restore a remote path | `{"item": ...}` |
| `GET /api/groups/G/file-source-options` | Editor options | See below |

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required` and
`@enabled_required("enable_group_workspaces")`.
- No route accepts a query parameter.
- `GET` and sync take no body.
- The other routes take a JSON object with no duplicate keys. A saved test or
  browse may send no body at all.

## The source shape

Each source is the classic sanitized shape (`sanitize_file_sync_source`), with
the Cosmos system fields removed. Stored secrets are never returned. Instead,
`credentials` carries this, with a placeholder for a stored value:

```json
{"auth_type": "...", "username": "", "domain": "", "identity": "",
 "password_stored": true, "secret_stored": false,
 "password": "Stored_In_KeyVault", "secret": ""}
```

A source bound to a workspace identity also carries `identity_name`. The routes
add two fields:

- `config_revision`, for conditional writes;
- `source_actions`.

### `config_revision`

`config_revision` is SHA-256 over the canonical JSON of the source's
**editable** fields:

- `name`, `source_type`, `enabled`, `recursive`, `connection`, `filters`,
  `remote_delete_policy` and `identity_id`;
- `schedule`, without `next_run_at`;
- every non-secret `auth` field: `auth_type`, `username`, `domain`, `identity`,
  `tenant_id` and `managed_identity_client_id`, plus the Key Vault reference
  names `password_secret_name` and `secret_secret_name`.

It never covers an inline password or secret, which is stored when Key Vault is
off. The sync engine writes only `last_run_*`, `updated_at` and
`schedule.next_run_at`, so a run finishing never changes the revision.

Including the reference names means a credential rotated by someone else also
changes the revision. The rotation stages a fresh name and removes the old one
once it commits. Without the names in the hash, a concurrent edit could have put
the old, deleted reference back.

## Writes

### Create and edit

- **Create:** the source object, as the classic editor sends it.
  - A hidden source type is refused with 403.
  - OneDrive is personal-only and is refused.
  - A new secret is stored in Key Vault under the new source's own names. If
    storing the record then fails, those secrets are removed.
- **Edit:** the changed fields plus a top-level `expected_config_revision`. A
  missing revision is 400. Fields you leave out keep their stored values.
  - The revision is compared with the freshly read source, inside the same
    conditional write that saves it.
  - A mismatch is 409, and nothing is written:

    ```json
    {"error": "This file source changed while it was being saved. Reload it and try again.",
     "error_code": "config_conflict"}
    ```

  - A source deleted meanwhile is 404, and is never recreated.
  - A write that keeps losing to other writes is 409 `write_conflict`.
- **Secrets on edit:** a new value is stored under a **fresh** Key Vault name
  before the conditional write.
  - A refused write never changes the credential the source still points at,
    and the unused new secret is removed.
  - After a successful write, the replaced secret is removed.

### Identity binding

A source can bind to a workspace identity from the same group. The identity must
meet three conditions:
- its normalized `usage_contexts` include `file_sync`;
- its normalized `supported_source_types` include the source type, or `generic`;
- its auth type suits the source type.

An identity from another group isn't found. This holds for create, edit, and
unsaved tests and browses.

### Delete

The body is exactly:

```json
{"expected_config_revision": "...", "delete_associated_files": true}
```

Both fields are required, and `delete_associated_files` must be a boolean.
There's no default, because deleting the documents a source produced is a
choice. Unknown fields are 400.

1. The delete is refused while a sync is queued or running:

   ```json
   {"error": "Wait for the running sync to finish, then delete the source.",
    "error_code": "source_busy"}
   ```

2. A stale revision is 409 `config_conflict`.
3. When requested, the source's documents are deleted, including every version.
4. The server checks again that no run has started, then deletes the source
   against its **current** etag.
   - If only an engine field changed meanwhile, the delete retries and succeeds.
   - A configuration change is `config_conflict`, a run that started is
     `source_busy`, and a source already gone is 404.
5. After the delete commits, the source's Key Vault secrets are removed, best
   effort.

Success returns the counts:

```json
{"success": true,
 "delete_result": {"associated_files_requested": true, "documents_deleted": 12,
                   "documents_skipped": 0, "documents_failed": 0}}
```

If any refusal comes after documents were already deleted, the response says so,
with `"partial": true` and the same `delete_result`, so a client never reports
that nothing changed:

| Refusal after documents were deleted | Status and `error_code` | Message |
|---|---|---|
| Configuration changed | 409 `config_conflict` | The source's documents were deleted, but the source changed before it could be removed. Reload it and try again. |
| Sync started | 409 `source_busy` | The source's documents were deleted, but a sync started before the source could be removed. Wait for it to finish, then delete the source again. |
| Source already removed | 404 | The source was already removed. Its documents were deleted. |

If some documents can't be deleted, the source is kept, and the response is 409
`delete_incomplete` with the counts: "Some of this source's documents could not
be deleted, so the source was kept. Try again." `partial` is true when at least
one document was deleted.

### Sync, runs and ignored paths

- **Sync now** queues a run. It isn't processed inside the request.
  - A source that already has a queued or running sync is refused with "This
    source already has a queued or running sync."
  - When the tenant's concurrent-run limit is reached, it is refused with "The
    File Sync concurrent run limit has been reached. Try again later."
  - The classic routes now return the same messages, instead of the generic
    configuration error.
- **Runs** returns the run history. A provider error message is replaced by the
  public run message.
- **Ignore path** takes `{"remote_path": "...", "ignored": true|false}`, and needs
  the `edit` operation.

### Test and browse

Testing a connection and browsing folders need the `test` operation: a manager,
in an `active` group.
- A saved test or browse uses the stored configuration and stored secrets of a
  source in this group.
- An unsaved one refuses hidden source types, and resolves identities only in
  this group.
- So nobody below a manager can pair a destination with a stored credential.

## Editor options

`GET /api/groups/G/file-source-options` returns what the editor needs, decided by
the server. For example, with the default limits:

```json
{"source_types": [{"value": "smb", "label": "SMB", "visible": true}],
 "eligible_identity_ids": {"smb": ["<identity_id>"]},
 "schedule": {"min_interval_minutes": 15, "max_interval_minutes": 10080},
 "limits": {"max_sources": 10},
 "recursive_allowed": true}
```

- `source_types` lists only the types valid for a group. OneDrive is never
  offered.
- `eligible_identity_ids` uses the same check the save applies. An editor that
  filters its identity picker with it offers exactly the identities the server
  accepts.

## Errors and logging

| Case | Response |
|---|---|
| Reviewed validation text | 400 with that text |
| Any other invalid request | 400 "The File Sync request could not be completed. Verify the source configuration and try again." |
| Not found | 404 "The requested File Sync resource was not found." |
| Not permitted | 403 |
| Anything unexpected | A stable 500 |

Every response is `Cache-Control: no-store`. Create, edit and delete run
through the existing File Sync service functions. They log the same
`source_created`, `source_updated` and `source_deleted` activity events as the
classic routes. A refused write logs nothing.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_group_file_source_apis.py` | 60 | See below |
| `functional_tests/test_group_file_source_transport.py` | 14 | None of the new routes can fall through to a legacy File Sync route |
| `functional_tests/test_v2_group_workspace_context.py` | `file_source_management` cases | The hint for each role and status, built by the shared policy |

`test_group_file_source_apis.py` covers:
- role, status and availability;
- 404 versus 403;
- fresh-name staging on create and edit;
- a refused edit keeps the live credential and leaves no orphan;
- a rotation landing mid-edit is a conflict;
- revision completeness over every auth field;
- engine writes never conflict;
- the delete body and busy refusal, the retry, and each partial outcome;
- documents deleted with their counts;
- Key Vault cleanup after a delete;
- identity binding, including another group's identity refused;
- options matching save-time validation;
- test and browse gating;
- sync, runs and ignored paths;
- the reviewed queue messages;
- audit parity.

The Key Vault tests enable storage and a vault name in the settings the helpers
read, and assert exact names.

Integrated with the branch tip, the related functional test files show no
failure that isn't already on the tip. Route policy passes 8/8, 4/4 and 2/2, and
the broken-access-control scanner passes on every changed backend module.

## Related

- [File Sync Concurrent Write Fix](../fixes/FILE_SYNC_CONCURRENT_WRITE_FIX.md)
- [Group Identity APIs](GROUP_IDENTITY_APIS.md)
- [File Sync Source Workflow](FILE_SYNC_SOURCE_WORKFLOW.md)
