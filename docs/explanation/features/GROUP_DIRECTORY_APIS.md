# Group Directory APIs (v0.261.146)

## Overview

These routes let a client find groups, create one, and ask to join one, without
touching the account's active group. They are the server side of the native V2
group directory, which is available from version **0.261.150**; see
[V2 Group Directory](V2_GROUP_DIRECTORY.md). The classic **Find Group** and
**Create Group** flows are unchanged.

A client can use them to:
- list every group the caller may discover, paged and searchable, with the
  caller's membership in each;
- create a group owned by the caller;
- ask to join a group, and cancel that request.

Implemented in version: **0.261.146**, tracked in
`application/single_app/config.py`.

Groups stay where they always were, in the groups container. No new setting,
container or index is required.

## Why new routes

The classic routes work, but they can't back a native page safely:

- **Discover** (`GET /api/groups/discover`) loads every group document in full,
  has no paging and no order, and returns the owner's whole object, including
  the owner's email and user ID.
- **Create** (`POST /api/groups`) sets no length limits and returns the exception
  text on failure.
- **Join** (`POST /api/groups/<group_id>/requests`) upserts the whole group
  document with no condition. A request that raced a membership change could
  undo it, and one that raced a delete could recreate the group. It fails with
  a server error when the group has no `pendingUsers` list. It has no cancel.

The classic routes are unchanged. The new routes:
- page and sort on the server, and return a narrow projection with no owner
  email or ID;
- check creation with one policy that also drives the page's Create control;
- write join requests conditionally, and never recreate a deleted group;
- return stable, data-free messages.

## Availability and roles

- **Availability:** every route needs `enable_group_workspaces`. When it is
  off, every route refuses.
- **Discovery is open.** Any signed-in user with the `User` or `Admin` app role
  can see every group's name, description, owner display name and member count. This
  is what the classic **Find Group** flow already allows. The directory never
  returns the owner's email or ID, or any member's entry, to anyone, members
  included.
- **Creating** needs `enable_group_creation`. When
  `require_member_of_create_group` is on, it also needs the `CreateGroups` app
  role. The `Admin` app role does not stand in for it.
- **Asking to join** needs nothing more than group workspaces. Any signed-in
  user may ask to join any group they aren't in, in **every group status**,
  including `inactive`, as the classic flow allows.

### The `group_directory` hint

The directory response carries a hint the page uses to decide what to offer:

```json
{"schema_version": 1, "can_create": true, "can_request_to_join": true}
```

It comes from one pure function, `build_group_directory_hints(settings, roles)`
in `functions_group_directory_policy.py`. The create route refuses with the same
decision, `group_creation_refusal`, so the page can't offer Create to someone the
route refuses, or hide it from someone the route accepts. A seam test holds both
to the classic create gates.

The hint is published only in the directory response, not in the V2 bootstrap.
A client should gate Create on `can_create`, never on `enable_group_creation`
alone, which ignores the role rule.

## Routes

| Method | Path | Body | Success |
|---|---|---|---|
| `GET` | `/api/groups/directory?search=&view=&page=&page_size=` | none | 200, one page |
| `POST` | `/api/groups/directory` | `{name, description?}` | 201 `{group}` |
| `POST` | `/api/groups/<group_id>/join-request` | none | 201 `{group}` |
| `DELETE` | `/api/groups/<group_id>/join-request` | none | 200 `{group}` |

Every route has the Swagger security decorator, `login_required`,
`user_required` and `enabled_required("enable_group_workspaces")`. Every
response the routes themselves produce, including their refusals, is sent with
`Cache-Control: no-store`.

Requests are strict:
- only the documented query parameters, each given at most once;
- no query parameters on the write routes;
- a body only where the table shows one;
- a JSON object body with no duplicate keys.

Anything else is a 400 with `error_code: "invalid_request"` and a message that
names the rule, not the input.

### How `/api/groups/directory` resolves

`/api/groups/directory` has the same shape as the classic
`/api/groups/<group_id>` routes. On this server, `GET` and `POST` reach the new
routes, because a static path segment outranks a converter. `PATCH`, `PUT` and
`DELETE` still reach the classic group routes, which refuse: 404, because no
group can have the ID `directory` (creation mints UUIDs), or first their
`CreateGroups` 403.

A server older than this release answers `GET /api/groups/directory` with 404
and `POST` with 405. Tests pin both route maps.

## The directory listing

`GET /api/groups/directory` returns:

```json
{
  "groups": [ ... ],
  "page": 1,
  "page_size": 20,
  "total_count": 42,
  "group_directory": {"schema_version": 1, "can_create": true, "can_request_to_join": true}
}
```

### Query parameters

| Parameter | Values | Default |
|---|---|---|
| `view` | `all`, `mine` (the caller is a member), `discover` (pending or not a member) | `all` |
| `search` | up to 200 characters after stripping | none |
| `page` | 1 to 10000 | 1 |
| `page_size` | 1 to 100 | 20 |

`search` is casefolded. It matches a substring of the name or the description,
or the exact group ID. A blank search lists everything.

Rows are sorted by casefolded name, then ID. The page is cut after filtering
and sorting, so `total_count` counts the rows of the requested view.

### A row

```json
{
  "id": "…",
  "name": "Research",
  "description": "…",
  "owner": {"displayName": "Ada Lovelace"},
  "member_count": 12,
  "heroColor": "#2563eb",
  "hasLogo": true,
  "logoVersion": 3,
  "membership": "member",
  "userRole": "Admin"
}
```

- `membership` is `member`, `pending` or `none`. A member row also carries
  `userRole`: `Owner`, `Admin`, `DocumentManager` or `User`. Membership uses the
  classic role predicate, so a caller who holds a role is a `member` even if a
  stale pending entry remains.
- `hasLogo` means the caller can load the logo: a logo is stored **and** the
  caller is a member, because `GET /api/groups/<group_id>/logo` serves members
  only.
- `heroColor`, `logoVersion` and `member_count` are normalized, so a malformed
  stored value falls back to the default rather than reaching the client.

### How the listing reads groups

One cross-partition query reads a narrow projection of every group. It includes
untyped legacy groups, as the admin directory does. The membership arrays are
reduced to the caller's own entries **in the database**, so no other member's
entry leaves Cosmos DB, and a row costs the same however many members the group
has. The classic predicates then run on that reduced copy.

## Creating a group

`POST /api/groups/directory` with `{"name": "…", "description": "…"}`:

1. The creation policy is checked **before the body is read**:
   - creation switched off: 403 `group_creation_disabled`, "Group creation is
     turned off.";
   - the `CreateGroups` role missing: 403 `create_groups_role_required`, "You
     need the CreateGroups role to create groups."

   Switched-off creation is reported first, so a user isn't told to get a role
   that wouldn't help.
2. The body must be exactly `{name, description?}`:
   - `name` is required, 1 to 80 characters after stripping, with no control
     characters. A blank name gets "Enter a group name.";
   - `description` is at most 500 characters after stripping.
3. The group is created by the same helper the classic route uses,
   `create_group_for_current_user`. The creator is the Owner, gets the classic
   "Group created" notification, and the chat bootstrap cache is bumped.
4. The response is 201 `{"group": row}`, with the row exactly as the listing
   would show it.

The new group is **not** made the caller's active group. A client navigates to
it by ID.

A storage failure is a 500 `group_create_failed`, "The group could not be
created. Try again.", with a diagnostic log that carries only the error type.

## Join requests

### Ask to join

`POST /api/groups/<group_id>/join-request` adds the caller's request and returns
201 `{"group": row}`, with `membership: "pending"`.

- The request uses the classic entry shape, `{userId, email, displayName}`, so
  the classic manage page lists it and its approve and reject routes work
  unchanged.
- A group with no `pendingUsers` list gets one.
- 409 `already_member`: "You're already a member of this group."
- 409 `request_pending`: "You've already asked to join this group."

### Cancel a request

`DELETE /api/groups/<group_id>/join-request` removes the caller's own request and
returns 200 `{"group": row}`.

- Every entry carrying the caller's ID is removed. That includes a stale entry
  left behind for someone who has since become a member.
- 409 `no_pending_request`: "You don't have a pending request to join this
  group."

### How the writes are made

Both writes go through `update_group_document_with_etag_guard`
(`functions_group.py`), which replaces the group document only if it hasn't
changed since it was read.

- A change that lands between the read and the write is re-read and kept, and
  the membership rules are checked again on each attempt. An approval that lands
  mid-request turns the request into `already_member`.
- A group deleted mid-request is 404 `group_not_found`, "Group not found.", and
  is never recreated.
- A group that keeps changing is 409 `group_write_conflict`, "The group changed
  while your request was being saved. Try again."

As with the classic request route, neither write notifies anyone, records an
activity event, or bumps the chat bootstrap cache. No bootstrap payload reads
pending requests. The guard takes `cache_reason=None` for that. The keyword is
still required, so every other caller names a reason, and the model endpoint
writes still bump the cache once per commit.

## Errors and logging

Every failure is a stable, data-free `error` with an `error_code`. An unexpected
failure is a 500 `group_directory_unavailable`, "The group directory request
could not be completed. Try again.", logged under `[WORKSPACE_ROUTE]` with the
error type only. Another client error, such as an oversized body, keeps its
status with "The request could not be processed."

## Known limitations

- **The classic membership writers are unconditional.** Approve, reject, add,
  remove, role change and ownership transfer still upsert the whole group
  document. One of them landing just after a native join or cancel can undo it.
  Converting them is the next milestone, M7B.
- **The listing reads every group on each request.** The projection is narrow,
  but the query still visits every group in the container, and paging happens
  after filtering. The classic discover route had the same cost, with full
  documents.
- **Inactive groups accept join requests,** as they always have. This is
  recorded as a product decision; the directory doesn't change it.

## Testing and validation

- `functional_tests/test_group_directory_apis.py` (148 cases, through the real
  Flask routes on `functional_tests/test_support/group_directory_harness.py`):
  - the projection for every caller;
  - the envelope, membership and role, views, search, ordering and paging;
  - the parameter rules;
  - `hasLogo` and the normalized fields;
  - untyped groups;
  - the pinned query;
  - create gates, messages, limits and audit trail;
  - join and cancel, including the etag guard cases: a change landing
    mid-request is kept, an approval or duplicate landing mid-request is refused
    on the retry, and a deleted group is not recreated;
  - every status accepting both;
  - no notification, log or bump;
  - the classic manage page approving a native request;
  - the sign-in, app role and feature gates.
- `functional_tests/test_group_directory_policy.py` (195 cases): the policy
  matches the classic create gates across the settings and role matrix, and the
  hint agrees with the create route.
- `functional_tests/test_group_directory_transport.py` (25 cases): the route
  maps on this server and on an older one.
- `functional_tests/test_group_document_etag_guard.py` (12 cases): a `None`
  cache reason commits without a bump, including after a lost response, and the
  keyword stays required.

Route policy coverage is updated for the four routes.

## Related

- [Workspace Notification Links Fix](../fixes/WORKSPACE_NOTIFICATION_LINKS_FIX.md)
- [Group Details Payload Disclosure Fix](../fixes/GROUP_DETAILS_PAYLOAD_DISCLOSURE_FIX.md)
- [Group Model Endpoint APIs](GROUP_MODEL_ENDPOINT_APIS.md)
