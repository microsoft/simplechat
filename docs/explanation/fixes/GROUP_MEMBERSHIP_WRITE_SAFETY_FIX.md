# Group Membership Write Safety Fix (v0.261.151)

## Issue

Every classic group membership change saved the whole group document with no
condition:
- join requests;
- approving and rejecting them;
- adding a member, on the manage page or through the SimpleChat agent tool;
- removing a member, and leaving;
- changing a role;
- transferring ownership.

So:
- **Two changes at once lost one of them.** An admin approving a request while
  another removed a member could quietly bring the removed member back, or drop
  the approval. A classic approval could undo a native join request made a
  moment earlier.
- **A change could recreate a deleted group.** A write that landed after the
  group was deleted saved the old copy again.
- **A group without a `pendingUsers` list couldn't be joined.** The classic join
  failed with a server error.

Fixed in version: **0.261.151**, tracked in `application/single_app/config.py`.

## Root cause

Each writer read the group, changed its copy, and called `upsert_item`, which
writes unconditionally and creates a missing item. The document holds the
group's members, roles, status, settings and model endpoints, so any two writes
that overlapped raced over all of it.

## Technical details

### The change

Each writer now goes through `update_group_document_with_etag_guard`
(`functions_group.py`). The guard replaces the document only if it hasn't
changed since it was read, and otherwise re-reads it and re-applies the change,
up to three attempts. Every check a writer makes runs again on the fresh copy:
the caller's role, the target's membership, and the pending requests. So a
change that landed first is respected rather than overwritten.

Responses, messages and side effects are the classic ones. Activity records,
notifications and chat bootstrap cache bumps run once, after the write commits,
from the committed copy:

| Writer | Cache bump |
|---|---|
| Join request (`POST /api/groups/<g>/requests`) | none, as before |
| Approve or reject (`PATCH /api/groups/<g>/requests/<r>`) | approve only, as before |
| Add (`POST /api/groups/<g>/members`, and the agent tool's add) | `group_member_added` |
| Remove or leave (`DELETE /api/groups/<g>/members/<m>`) | `group_member_removed`, only when a member was removed |
| Role change (`PATCH /api/groups/<g>/members/<m>`) | `group_member_role_updated` |
| Transfer (`PATCH /api/groups/<g>/transferOwnership`) | `group_ownership_transferred` |

### Response changes

Only these:
- a group deleted mid-write gets 404 `{"error": "Group not found"}`, and is not
  recreated;
- a group that keeps changing through three attempts gets 409
  `{"error": "The group changed while this change was being saved. Try again.",
  "error_code": "group_write_conflict"}`;
- a join request on a group with no `pendingUsers` list creates the list and
  succeeds;
- removing or leaving when you're not a member writes nothing and gives the
  same 404 as before. If only a stray `admins` or `documentManagers` entry is
  left behind, it is cleaned up, and the answer is still that 404.

Through the SimpleChat agent tool, a conflicting add is reported as the tool's
usual unexpected error, with the data-free conflict message.

### Files modified

- `route_backend_groups.py`: join, approve and reject, remove and leave, role
  change and transfer.
- `functions_simplechat_operations.py`: `add_group_member_for_current_user`,
  which backs both the add route and the agent tool.
- `functional_tests/test_cosmos_wave2a_chat_bootstrap_cache.py`: its source
  markers now look for the writers' `cache_reason="..."` instead of a direct
  bump.

### Tests

- `functional_tests/test_group_membership_legacy_guard.py` (61 cases). For
  every classic write:
  - one conditional replace, with its cache bump;
  - a concurrent change kept;
  - a deleted group 404, and not recreated;
  - a group that keeps changing 409;
  - its rules re-checked on the fresh copy.

  It also covers the agent tool's add. A source check asserts that no classic
  membership writer upserts. And it shows the race with native join and cancel
  is closed: a classic write no longer undoes them.
- `functional_tests/test_group_membership_legacy_responses.py` (54 cases): the
  classic responses before and after, including the non-member remove.
- `functional_tests/test_group_document_etag_guard.py` (14 cases): each classic
  writer keeps its cache reason.

## Remaining unconditional writers

The group settings writers (rename, download settings, the logo, and
retention, including its admin force push) were converted in version
**0.261.154**; see [Group Settings Write Safety Fix](GROUP_SETTINGS_WRITE_SAFETY_FIX.md).
These are recorded for a follow-up:
- in `route_backend_control_center.py`: the group activity cache, the status
  change, the admin add member, take ownership and transfer ownership;
- the group tag definition writers, in `route_backend_group_documents.py` and
  `functions_documents.get_or_create_tag_definition`;
- `make_group_inactive_for_current_user`;
- the legacy `update_group_model_endpoints`.

One of them landing just after a membership change can still undo it.

## Validation

- Before: overlapping membership changes silently lost one of them, and a late
  write could bring a deleted group back.
- After: each change applies to the group as it currently is, and refuses
  cleanly when the group is gone or keeps changing.

## Related

- [Group Membership APIs](../features/GROUP_MEMBERSHIP_APIS.md)
- [Group Membership Edge Cases Fix](GROUP_MEMBERSHIP_EDGE_CASES_FIX.md)
- [Group Directory APIs](../features/GROUP_DIRECTORY_APIS.md)
