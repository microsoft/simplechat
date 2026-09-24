# Group Residual Writers Write Safety Fix

Fixed/Implemented in version: **0.261.160**

## Issue

Each group is one Cosmos item that holds its membership, roles, status,
settings, tag definitions, model endpoints and cached Control Center metrics.
Releases 0.261.140 to 0.261.154 moved most writers of that item onto a
conditional write, but twelve still saved a copy they had read earlier with an
unconditional `upsert_item`:

- in Control Center: the activity metrics cache, the group status change, the
  admin's add member, and the take ownership and transfer ownership approvals;
- the classic group tag definition routes (add, rename, delete) and
  `get_or_create_tag_definition`, which uploads, File Sync and metadata edits
  call;
- the SimpleChat agent's operation that marks a group inactive;
- the legacy bulk save of a group's model endpoints.

Any of them could undo a change made in between, such as a member added or
removed, a status change or a new tag. A writer that saved a copy read before
the group was deleted brought the group back with its old members.

The metrics cache made this likely. Control Center's refresh, and its
scheduled run at 02:00 (on by default), list every group and then save each
listed copy. The groups list and its CSV export also save when called with
`?force_refresh=true`. No shipped page sends that for groups, but any Control
Center admin can.

## Root cause

These writers predate the conditional write,
`functions_group.update_group_document_with_etag_guard`. It re-reads the
group, applies the change to that fresh copy, and saves only if the group
hasn't changed since the read. If it has, it tries again, up to three attempts.
It never recreates a deleted group.

## Fix

Every writer now goes through the guard and decides on the fresh copy.

### One conflict text

A group that keeps changing through every attempt gets 409 with one text
everywhere:

```json
{"error": "The group changed while your request was being saved. Try again.",
 "error_code": "group_write_conflict"}
```

`GROUP_WRITE_CONFLICT_CODE` and `GROUP_WRITE_CONFLICT_MESSAGE` live in
`functions_group.py`, and the membership, directory, settings, endpoint and
retention routes use them. Before this, membership said "while this change
was being saved" and endpoints "while this model endpoint was being saved".
The V2 endpoint editor's fallback text uses the same sentence.

### Control Center

- **Metrics.** The figures are computed first, and only `metrics` is set on
  the fresh copy. It is the only writer of `metrics`. A deleted group is
  skipped, and a conflict leaves the group uncached.
- **Status change and add member.** "Unchanged" and "already a member" are
  decided on the fresh copy; the second answers 200 and writes nothing.
  Membership history and roles apply to that copy. A deleted group is 404
  "Group not found" and isn't recreated. The status log, activity record and
  log entry are written once, after the save.
- **Take and transfer ownership.** The approval is re-checked on the fresh
  copy:
  - if the owner is still the recorded one, it applies (a transfer also needs
    the new owner to be a member, with the existing "New owner not found in
    group members");
  - if the requested owner already owns the group, it succeeds with no write
    and no second activity record, so approving the same request twice ends
    `executed` rather than `failed`;
  - if anyone else owns it, it's refused with "The group's owner changed after
    this request was made, so it wasn't applied. Submit a new request.";
  - a deleted group gives "The group no longer exists.", and a conflict the
    shared text. The approval ends `failed` in those three cases.

### Tags

- **The classic tag routes** share one helper. The caller's tag role is
  re-checked on the fresh copy (403 "You do not have permission to manage
  tags"), and "Tag already exists" is decided there too. Nothing is written
  when nothing changes. A deleted group is 404 "Active group not found".
- **Rename and delete** change the definition first, then the documents. A
  failure partway through can be finished by repeating the request, because
  both routes skip a definition that's already gone.
- **`get_or_create_tag_definition`** adds a definition only when the fresh
  copy lacks it, and never recreates a deleted group. If the group keeps
  changing, it answers the default colour and logs a warning with no tag or
  group data: "[Tags] A group tag definition was not saved because the group
  kept changing." Every group caller passes no colour, so nothing is lost.

### The inactive marker

The SimpleChat operation that marks a group inactive decides on the fresh copy.
A group that's already inactive, including one made inactive meanwhile, gets
the classic answer and nothing is written. A missing or deleted group raises
`LookupError`, and a conflict raises `GroupDocumentWriteConflict`.

### The bulk model endpoint save

- `update_group_model_endpoints` re-checks that the caller is an Owner or Admin
  on the fresh copy. The route answers a conflict with 409 and the shared text,
  a missing group with 404 "The selected group could not be found.", and a
  demoted caller with 403.
- **Key Vault.** Secrets the save supersedes or removes are deleted only
  after the save commits. The set is taken from the version the save
  replaced, minus anything the committed endpoints still reference. If the
  save fails for certain (a conflict, a deleted group or a demoted caller),
  only the secret this save staged is deleted. If the outcome is uncertain,
  the staged secret is kept and a warning is logged.
- **Behavior change:** a failed Key Vault delete used to fail the save before
  anything was written (500). It's now logged, and the committed save stands,
  as on the per-endpoint routes.

## Files modified

| File | Change |
| --- | --- |
| `functions_group.py` | The shared conflict text and code; `update_group_model_endpoints` on the guard. |
| `functions_group_directory.py`, `functions_group_membership.py`, `functions_group_settings.py`, `route_backend_groups.py`, `route_backend_retention_policy.py` | Use the shared conflict text. |
| `functions_group_endpoint_access.py` | The shared text; four public helpers for staged and committed endpoint secrets. |
| `route_backend_control_center.py` | Metrics, status change, add member and the ownership approvals on the guard. |
| `route_backend_group_documents.py`, `functions_documents.py` | The tag writers on the guard. |
| `functions_simplechat_operations.py` | The inactive marker on the guard. |
| `route_backend_models.py` | The bulk save's responses and post-commit Key Vault cleanup. |
| `application/v2_ui/src/lib/modelConnections.ts` | The endpoint editor's fallback conflict text. |

Application paths are relative to `application/single_app/` unless shown.

## Testing

- `functional_tests/test_group_document_write_inventory.py` (25) fails if any
  code writes a group item outside the guard. It allows only `create_group`,
  the guard itself, `delete_group`, the conditional tag-definition patch and
  the data management tools.
- `test_group_write_conflict_text.py` (14) pins the one text and code.
- `test_control_center_group_writers.py` (40), for example: a stale listed
  copy keeps a concurrent membership change, a deleted group isn't
  recreated, a plain read writes nothing, and all four ownership outcomes.
- `test_group_tag_definition_writers.py` (38), including a failure on the
  second document followed by a repeat that finishes.
- `test_simplechat_group_inactive_writer.py` (10).
- `test_group_bulk_endpoint_save_writer.py` (16), including that a secret the
  committed endpoints still reference is never deleted.
- Updated text pins: the membership and endpoint API suites, the membership
  legacy guard, and the membership and endpoint fixture parity pins.

## Known limitations

- The bulk list still replaces the whole endpoint list, so it wins over a
  per-endpoint change saved between its read and its write. A key rotated by
  the per-endpoint route in that window can leave the bulk list referencing
  a deleted secret.
- The approvals record itself can still race for other action types, an
  approval's `execution_result` can include exception text (visible to
  administrators only), and the public workspace metrics writer is unchanged.
  These are recorded for later work.

## Related

- [Group Settings Write Safety Fix](GROUP_SETTINGS_WRITE_SAFETY_FIX.md)
- [Group Membership Write Safety Fix](GROUP_MEMBERSHIP_WRITE_SAFETY_FIX.md)
- [SimpleChat Agent Group Output Fix](SIMPLECHAT_AGENT_GROUP_OUTPUT_FIX.md)
- [Group Classic Request Gaps Fix](GROUP_CLASSIC_REQUEST_GAPS_FIX.md)
