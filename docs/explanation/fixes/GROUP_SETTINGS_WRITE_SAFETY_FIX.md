# Group Settings Write Safety Fix (v0.261.154)

## Issue

The classic group settings writers saved the whole group document with no
condition:
- renaming the group, and changing its description or color
  (`PATCH` and `PUT /api/groups/<group_id>`);
- the group's download setting (`PATCH /api/groups/<group_id>/download-settings`);
- the logo (`POST /api/groups/<group_id>/logo`);
- the retention policy (`POST /api/retention-policy/group/<group_id>`);
- the administrator's retention force push to every group
  (`POST /api/admin/retention-policy/force-push`).

So:
- **A settings save could undo a membership change.** Each writer saved the
  member list it had read. A rename landing just after a member was removed
  brought the member back; one landing just after an approval dropped the new
  member.
- **A settings save could recreate a deleted group.** A write that landed after
  the group was deleted saved the old copy again.

Fixed in version: **0.261.154**, tracked in `application/single_app/config.py`.
The classic membership writers were made safe in 0.261.151
([Group Membership Write Safety Fix](GROUP_MEMBERSHIP_WRITE_SAFETY_FIX.md)).

## Root cause

Each writer read the group, changed its copy, and called `upsert_item`, which
writes unconditionally and creates a missing item. The group document holds the
members, roles, status, settings and model endpoints, so any two writes that
overlapped raced over all of it.

## Technical details

### The change

Each writer now goes through `update_group_document_with_etag_guard`
(`functions_group.py`). The guard replaces the document only if it hasn't
changed since it was read, and otherwise re-reads it and re-applies the change,
up to three attempts. On each fresh copy:
- the caller's owner or admin check runs again, so a demotion that lands
  mid-write is respected;
- the fields the request leaves out come from that copy;
- the logo version follows that copy's, so a cached image is never reused;
- retention values are merged into that copy's policy.

The force push applies `"default"` to each group's current copy. A group deleted
since the listing is skipped rather than recreated, and only committed writes
are counted.

Responses, messages and cache bumps are otherwise the classic ones:

| Writer | Cache bump |
|---|---|
| Rename, description, color | `group_updated`, as before, now after the commit |
| Download setting | `group_updated`, as before |
| Logo | none, as before |
| Retention, and the force push | none, as before |

### Response changes

Only these:
- a group deleted mid-write gets 404 `{"error": "Group not found"}`, and is not
  recreated;
- a group that keeps changing through three attempts gets 409
  `{"error": "The group changed while your request was being saved. Try again.",
  "error_code": "group_write_conflict"}`;
- a caller who lost their role mid-write gets the route's existing 403.

### Files modified

- `route_backend_groups.py`: `api_update_group`,
  `api_update_group_download_settings` and `api_upload_group_logo`.
- `route_backend_retention_policy.py`: `update_group_retention_settings` and
  `force_push_retention_defaults`.
- `functional_tests/test_cosmos_wave2a_chat_bootstrap_cache.py`: its source
  markers now look for the rename's `cache_reason="group_updated"`.

### Tests

- `functional_tests/test_group_settings_legacy_writers.py` (44 cases). For every
  writer:
  - the classic responses, messages and cache effects;
  - a membership change landing between the read and the write is kept;
  - a deleted group 404, and not recreated;
  - a group that keeps changing 409, with nothing stored;
  - the owner or admin check made again on the fresh copy.

  A source check asserts that none of them upserts.
- `functional_tests/test_group_document_etag_guard.py`: each writer keeps its
  classic cache reason.

## Remaining unconditional writers

These are recorded for a follow-up:
- in `route_backend_control_center.py`: the group activity cache, the status
  change, the admin add member, take ownership and transfer ownership;
- the group tag definition writers, in `route_backend_group_documents.py` and
  `functions_documents.get_or_create_tag_definition`;
- `make_group_inactive_for_current_user`;
- the legacy `update_group_model_endpoints`.

All of them are on the conditional write from version 0.261.160; see the
[Group Residual Writers Write Safety Fix](GROUP_RESIDUAL_WRITERS_WRITE_SAFETY_FIX.md).

## Validation

- Before: a settings save could silently undo a membership change, and a late
  save could bring a deleted group back.
- After: each save applies to the group as it currently is, and refuses cleanly
  when the group is gone or keeps changing.

## Related

- [Group Settings APIs](../features/GROUP_SETTINGS_APIS.md)
- [Group Membership Write Safety Fix](GROUP_MEMBERSHIP_WRITE_SAFETY_FIX.md)
- [Group Retention Settings Fix](GROUP_RETENTION_SETTINGS_FIX.md)
