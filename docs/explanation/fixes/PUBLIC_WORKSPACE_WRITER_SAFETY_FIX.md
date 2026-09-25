# Public Workspace Writer Safety Fix

Fixed/Implemented in version: **0.261.173**

## Issue

Each public workspace is one Cosmos item that holds:
- its owner, admins, document managers and pending requests;
- its status, download and retention settings, and branding;
- its tag definitions and cached Control Center metrics.

Every classic writer of that item, 27 in all, saved a copy it had read earlier
with an unconditional `upsert_item`. They were:
- the public workspace routes for requests, members, roles, ownership,
  settings, logo and download settings;
- the public tag routes and `get_or_create_tag_definition`;
- retention settings and the retention defaults push;
- seven Control Center writers.

Any of them could undo a change made in between, such as a member added, a
role changed, a status change or a new tag. A writer that saved a copy read
before the workspace was deleted brought the workspace back. Control Center's
metrics refresh saved every listed workspace.

The conversion also fixed these defects in the classic routes:

- **Admins stored as objects were refused.** Five routes checked Admin with a
  test that matched only bare ids. An Admin promoted by the role-change route,
  which stores an object, got 403 on the request list, deciding requests and
  adding members, and couldn't receive ownership. A legacy bare-id document
  manager entry made several routes answer 500.
- **Names and emails were blanked.** A role change to DocumentManager, and the
  previous owner after a transfer, were saved with an empty name and email.
- **Unvalidated bodies.** A download setting that wasn't a boolean, or a
  retention body that wasn't an object, was accepted.
- **Statistics dates.** The public statistics route used the unbounded date
  window. A date at the calendar's edge with an offset failed with a 500, and
  dates outside 2000-01-01 to 9998-12-31 weren't refused.
- **Error text.** The update, download settings and logo routes answered raw
  exception text. An oversized image (a decompression bomb) failed with a 500.
- **Unknown statuses.** The classic status check gave an unrecognized status
  the `active` permissions.
- **Tag vocabulary.** A tag definition write that lost to a concurrent change
  answered a generic sentence with no code.

## Root cause

The public workspace routes predate conditional writes. The group side was
moved onto a conditional write between versions 0.261.140 and 0.261.160; the
public side kept the original pattern.

## Fix

### One guard, one conflict answer

`update_public_workspace_document_with_etag_guard` in
`functions_public_workspaces.py` mirrors the group guard:
- it reads the workspace, applies the change to a private copy, and replaces
  the item only if it hasn't changed since the read;
- a lost race is re-read and re-applied, up to three writes, before a conflict
  is reported;
- a missing workspace is never recreated;
- a lost response whose write had committed is recognized as committed;
- the chat bootstrap cache is bumped once, when the change needs it.

A route that can't commit answers 409 `{"error": "The public workspace changed
while your request was being saved. Try again.", "error_code":
"public_workspace_write_conflict"}`. Each classic route's own refusals (for
example "Already requested" or "Forbidden") are checked again against the fresh
copy on every attempt, so a decision is never made from a stale one.

### Membership, requests and roles

- Every role check uses the one role helper, which reads both entry formats,
  and every document manager read tolerates a bare id.
- A member moving between admins, document managers and owner keeps their
  stored name and email. A directory (Graph) lookup is used only for an old
  bare-id entry, and only before the conditional write.
- The previous owner stays a document manager, with their name and email.

### Settings, logo, downloads and retention

- The download setting must be a boolean, and the retention body an object;
  anything else is a 400 that writes nothing.
- The routes answer reviewed text, and log a storage failure with its error type
  and status only, under `[PUBLIC_SETTINGS]`.
- An unreadable logo, including a decompression bomb, gets "The logo image
  could not be read. Upload a PNG or JPEG image."

### Tags

- The tag routes and `get_or_create_tag_definition` write through the guard.
- A tag definition write that loses to a concurrent change answers the same
  409 as the up-front check, with `error_code: "vocabulary_conflict"`.
- Metadata edits and bulk tagging write the tag definitions before any
  document, as the group side does from version 0.261.168.

### Control Center

- **The metrics cache** is computed first. Only `metrics` is written onto the
  fresh copy, with no cache bump, and a deleted workspace is skipped.
- **Ownership approvals** apply only if the fresh copy still has the owner the
  request recorded. A repeat is a no-op, and anything else asks for a new
  request.
- **Bulk actions** write each workspace separately and report each failure;
  one conflict doesn't stop the others.

### Statistics and status

- The public statistics route uses the bounded date window, so an out-of-range
  or overflowing date is a 400 with the reviewed message.
- An unrecognized status gets the `inactive` permissions. That's the V2 public
  context's rule, with its reason "This workspace's status is not recognized.
  Contact an administrator."

### Also in this release

- Four unused document manager helpers in `functions_public_workspaces.py` were
  removed.
- The group tag definition warning added in version 0.261.160 used a
  nonstandard `[Tags]` logging tag. It now uses `[CREATE_TAG]`.

## Files modified

| File | Change |
| --- | --- |
| `functions_public_workspaces.py` | The guard and its conflict constants; the unknown-status rule; the unused helpers removed |
| `route_backend_public_workspaces.py` | Requests, members, roles, ownership, settings, logo, download settings and statistics through the guard, with the fixes above |
| `route_backend_public_documents.py` | The public tag routes through the guard |
| `functions_documents.py` | The public branch of `get_or_create_tag_definition` through the guard; the group warning's tag |
| `functions_public_document_management.py` | The coded vocabulary conflict, and definitions before documents |
| `route_backend_retention_policy.py` | Public retention settings and the defaults push through the guard |
| `route_backend_control_center.py` | The seven public workspace writers |
| `docs/reference/logging-tags.md` | `[PUBLIC_SETTINGS]` |

## Testing

- `test_public_workspace_document_write_guard.py`: the guard's behaviour,
  beside the group guard's.
- `test_public_workspace_document_write_inventory.py`: fails on any new raw
  writer of the public workspace item. The allowed writes are its creation,
  two deletions, the guard's own replace and the conditional tag patch.
- `test_public_workspace_membership_writer_safety.py`,
  `test_public_workspace_settings_writer_safety.py`,
  `test_public_workspace_tag_writer_safety.py` and
  `test_control_center_public_writers.py`: each converted route over its real
  handler.
  - They cover both admin formats and bare-id document managers, kept names
    and emails, and the reviewed texts.
  - They cover a concurrent change kept, a deleted workspace not recreated,
    and the conflict answer.
- `test_public_classic_request_gaps.py`: the statistics window, the unknown
  status, and the download and retention body checks.
- `test_public_document_management.py`: the coded vocabulary conflict and the
  definition order. Its line endings were also normalized to LF.
- Every new pin was mutation-checked.

## Known limitations

- The public tag routes still answer a generic 500 for failures other than a
  conflict, as the group's do; this is a cross-scope follow-up.
- Deleting a public workspace still leaves its documents, prompts, identities
  and file sources behind; see decision 10.
- Classic saves send no revision, so two saves of the same field still resolve
  as last-writer-wins. The conditional write keeps unrelated changes, such as a
  membership change made at the same moment.

## Related

- [Group Residual Writers Write Safety Fix](GROUP_RESIDUAL_WRITERS_WRITE_SAFETY_FIX.md)
- [Group Tag Vocabulary Conflict Code Fix](GROUP_TAG_VOCABULARY_CONFLICT_CODE_FIX.md)
- [Group Tag Definitions First Fix](GROUP_TAG_DEFINITIONS_FIRST_FIX.md)
- [Public Document Management APIs](../features/PUBLIC_DOCUMENT_MANAGEMENT_APIS.md)
