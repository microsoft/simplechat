# Group Membership APIs (v0.261.151)

## Overview

These routes manage a group's members, its pending join requests and its owner
for a named group, without touching the account's active group. They are the
server side of the V2 Members section, native from version **0.261.155**
([V2 Group Members](V2_GROUP_MEMBERS.md)). This release also makes the classic
manage page safe to use alongside other changes.

A client can use them to:
- list the members, paged and searchable, with what the caller may do to each;
- add a member, change a member's role, remove a member, or leave;
- list, approve and reject join requests;
- transfer ownership.

Implemented in version: **0.261.151**, tracked in
`application/single_app/config.py`.

Membership stays where it always was, on the group document: `owner`, `users`,
`admins`, `documentManagers` and `pendingUsers`. No new setting, container or
index is required.

## Why new routes

The classic routes under `/api/groups/<group_id>/members` and `/requests` act on
the group they name, but they had three problems a native page can't build on:
- every one of them upserted the whole group document with no condition, so
  two changes at once lost one of them, and a change could recreate a deleted
  group;
- several accepted invalid data: a duplicate member on approve, the owner
  moved into `admins`, and an old owner appended with no email or name;
- their responses weren't consistent enough for a client to act on.

The classic routes are now safe too (see
[Group Membership Write Safety Fix](../fixes/GROUP_MEMBERSHIP_WRITE_SAFETY_FIX.md)
and [Group Membership Edge Cases Fix](../fixes/GROUP_MEMBERSHIP_EDGE_CASES_FIX.md)).
The native routes add a paged list, server-computed hints, one role vocabulary,
and stable, data-free errors.

## Availability and roles

Every route needs `enable_group_workspaces` and a signed-in user with the
`User` or `Admin` app role, and the caller must be a member of the group. A
non-member gets 403 `not_a_member`. One pure policy module,
`functions_group_membership_policy.py`, decides what each caller may do. Seam
tests hold it to the classic routes and to the native routes.

| Operation | Owner | Admin | DocumentManager, User |
|---|---|---|---|
| List members | yes | yes | yes |
| List, approve or reject join requests | yes | yes | no |
| Add a member | yes, in an `active` or `upload_disabled` group | the same | no |
| Change a role | yes | yes, including other Admins and themselves | no |
| Remove a member | yes | yes, including other Admins | no |
| Leave | no: transfer ownership first | yes | yes |
| Transfer ownership | yes, to another member | no | no |

- The owner's role can't be changed: 409 `owner_target`, "Transfer ownership
  to change the owner's role."
- The owner can't be removed (409 `owner_target`, "Transfer ownership before
  removing the owner.") or leave (409 `owner_cannot_leave`).
- **Group status.** Adding a member is refused in `locked` and `inactive`
  groups, and in any unrecognized status, with 403 `group_status_unavailable`:
  "Members can't be added to this group in its current status." That matches
  the classic page, which hides Add and Bulk add for those groups. Every other
  membership operation is allowed in every status, as classic allows.

### Hints

The member list carries what the caller may do:
- `membership_management: {schema_version: 1, operations}`, where operations
  are drawn from `add_member`, `review_requests`, `change_role`,
  `remove_member`, `transfer_ownership` and `leave`;
- `member_actions` on each row, drawn from `change_role`, `remove`,
  `transfer_ownership` and `leave`.

A client offers only what these list. The hints are published only by the
member list. The workspace context's `sections.members` (version 0.261.155)
says only whether the Members section can open, not what it may do.

## Routes

| Method | Path | Body | Success |
|---|---|---|---|
| `GET` | `/api/groups/<g>/membership/members?search=&role=&page=&page_size=` | none | 200, one page |
| `POST` | `/api/groups/<g>/membership/members` | `{userId, displayName?, email?, role}` | 201 `{member}` |
| `PATCH` | `/api/groups/<g>/membership/members/<user_id>` | `{role}` | 200 `{member, changed}` |
| `DELETE` | `/api/groups/<g>/membership/members/<user_id>` | none | 200 `{userId, left}` |
| `GET` | `/api/groups/<g>/membership/requests` | none | 200 `{requests, total_count}` |
| `POST` | `/api/groups/<g>/membership/requests/<user_id>/approve` | none | 200 `{member, already_member}` |
| `POST` | `/api/groups/<g>/membership/requests/<user_id>/reject` | none | 200 `{userId}` |
| `PUT` | `/api/groups/<g>/membership/owner` | `{userId}` | 200 `{owner, changed}` |

Every route has the Swagger security decorator, `login_required`,
`user_required` and `enabled_required("enable_group_workspaces")`. Every response
is sent with `Cache-Control: no-store`. Requests are strict: only the documented
query parameters, a body only where the table shows one, and a JSON object with
no duplicate keys. Anything else is a 400 with `error_code: "invalid_request"`.
No native path matches a classic route; transport tests pin that.

Roles use one vocabulary everywhere: `Owner`, `Admin`, `DocumentManager` and
`User`. `DELETE` on your own user ID is leaving.

## Reading members

```json
{
  "members": [{"userId": "…", "displayName": "…", "email": "…", "role": "Admin",
               "member_actions": ["change_role", "remove"]}],
  "page": 1, "page_size": 20, "total_count": 12,
  "membership_management": {"schema_version": 1, "operations": ["add_member", "…"]}
}
```

- Each `users[]` entry is listed once, by its first appearance. The owner is
  listed even when missing from `users[]`, and malformed entries are skipped.
- `search`, of up to 200 characters, matches a substring of the display name or
  email, casefolded, or the exact user ID. `role` filters to one of the four
  roles; anything else is a 400.
- Rows are sorted by role (Owner, Admin, DocumentManager, User), then by
  casefolded name, then by ID. `page_size` defaults to 20, up to 100.
- Every member can list the members, with their emails, as the classic
  members route allows.

The request list is for the Owner and Admins. It gives each requester once, as
`{userId, displayName, email}`, sorted by name.

## Writes

Every write goes through `update_group_document_with_etag_guard`, which
replaces the group document only if it hasn't changed since it was read. Each
attempt re-checks the caller's role and the target's state on the fresh copy,
so a demotion or a membership change that lands mid-write is respected.

- A group deleted mid-write is 404 `group_not_found`, and is never recreated.
- A group that keeps changing is 409 `group_write_conflict`: "The group changed
  while your request was being saved. Try again." From version **0.261.160**
  every group-document write shares this text; before it, these routes said
  "while this change was being saved".
- Audit records, notifications and chat bootstrap cache bumps run once, after
  the write commits, and never on a refusal.

### Add

1. The caller must be the Owner or an Admin, and the group's status must allow
   adding.
2. The user is looked up by ID in the directory, through the caller's
   delegated token, before the write:
   - a definitive not-found is 400 `user_not_found`, "That user wasn't found in
     the directory.";
   - if the directory can't answer (no token, no permission, or a transport
     failure), the submitted `displayName` and `email` are used, as the classic
     add does. This is logged as a warning, with the error type only.
3. Someone who is already a member is 409 `already_member`.
4. The member is added with the role, and any pending requests from them are
   cleared.

The audit is the classic one: an `add_member_directly` activity record, and the
two "added" notifications, to the member and to the person who added them.

### Change a role

`{role}` is `Admin`, `DocumentManager` or `User`.
- The target must be a member (404 `member_not_found` otherwise), and can't be
  the owner.
- Changing a role to the one it already has is 200 with `changed: false`, and
  writes and notifies nothing.
- A real change writes the classic `group_member_role_changed` activity record,
  and sends the member the classic "Role Changed" notification.

### Remove and leave

- Removing needs the Owner or an Admin; leaving needs only membership.
- The removal is recorded with the classic `log_group_member_deleted`, as
  `admin_removed_member` or `member_left_group`.
- The chat bootstrap cache is bumped only when a `users[]` entry was actually
  removed.

### Join requests

Approve and reject settle **every** pending entry for the user.
- Approving someone who is already a member clears their entries, adds no
  duplicate, and returns `already_member: true`.
- Deciding when there's no pending request is 409 `no_pending_request`. So
  retrying an approve whose response was lost gets this 409. A client should
  reload the members and requests rather than report a failure.

Approve bumps the chat bootstrap cache; reject doesn't, as in classic. Neither
records an activity event or sends a notification, as in classic.

### Transfer ownership

- Only the Owner can transfer, to someone with a `users[]` entry
  (404 `member_not_found` otherwise).
- The new owner leaves `admins` and `documentManagers`. The old owner becomes a
  User, and is appended to `users[]` with the stored owner's email and name if
  they were missing.
- Transferring to the current owner is 200 with `changed: false` for any
  member, so a retry after a lost response is safe.

## Errors and logging

Every failure is a stable, data-free `error` with an `error_code`. An
unexpected failure is a 500 `group_membership_unavailable`, "The membership request
could not be completed. Try again.", logged with the error type only.

## Known limitations

- **The V2 Members section isn't available in inactive groups,** or groups
  with an unrecognized status, although these routes still allow management
  there. Use the classic manage page for those groups.
- **Directory fallback.** When the directory can't be reached, an add stores
  the name and email the client sent.
- **Membership changes don't appear in the group activity feed,** as before.
  Their activity records keep the group ID where the feed doesn't look.
- **Other whole-document writers.** The membership writers are now
  conditional, and the group settings writers followed in version
  **0.261.154** ([Group Settings APIs](GROUP_SETTINGS_APIS.md)). A few writers
  remain for a follow-up, and one of them landing just after a membership
  change can still undo it:
  - the Control Center's group actions;
  - group tag definitions;
  - the inactive marker;
  - the legacy group endpoint save.
- **Product questions** are recorded for later:
  - should role changes and removals be allowed in inactive groups?
  - should approvals be allowed in locked or inactive groups?

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_group_membership_apis.py` | 179 | Every route through the real Flask app: roles, statuses, the owner rules, pending-request handling, transfer, directory lookup, guard races, strict requests and errors |
| `functional_tests/test_group_membership_policy.py` | 88 | The policy against the classic routes and the native routes, for every role, status and target |
| `functional_tests/test_group_membership_transport.py` | 32 | The declared routes, and that no native path matches a classic route |
| `functional_tests/test_group_membership_legacy_responses.py` | 54 | The classic routes' responses, before and after the conversion and fixes |
| `functional_tests/test_group_membership_legacy_guard.py` | 61 | The classic writers on the guard, and the closed race with native join and cancel |
| `functional_tests/test_group_membership_audit_parity.py` | 15 | Native and classic writes leave the same group, audit, notifications and cache bumps |

Route policy coverage is updated for the eight routes.

## Related

- [Group Membership Write Safety Fix](../fixes/GROUP_MEMBERSHIP_WRITE_SAFETY_FIX.md)
- [Group Membership Edge Cases Fix](../fixes/GROUP_MEMBERSHIP_EDGE_CASES_FIX.md)
- [User Search Error Hardening Fix](../fixes/USER_SEARCH_ERROR_HARDENING_FIX.md)
- [Group Directory APIs](GROUP_DIRECTORY_APIS.md)
