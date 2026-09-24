# Workspace Notification Links Fix (v0.261.146)

## Issue

Six notifications linked to management pages at paths no route serves. Opening
one of them from the notification list led to a 404 instead of the workspace's
management page.

Four group notifications linked to `/manage_group/<group_id>`:

| Notification | Sent to | Where it was built |
|---|---|---|
| "Group created" | the creator | `_notify_group_created`, `functions_simplechat_operations.py` |
| "Added to Group" | the member who was added | `_notify_group_member_addition` |
| "Group member added" | the person who added them, when that's someone else | `_notify_group_member_addition` |
| "Role Changed" | the member whose role changed | the role change route, `route_backend_groups.py` |

Two public workspace notifications linked to
`/manage_public_workspace?workspace_id=<workspace_id>`:

| Notification | Sent to | Where it was built |
|---|---|---|
| "Added to Public Workspace" | the member who was added | the add member route, `route_backend_public_workspaces.py` |
| "Workspace Role Changed" | the member whose role changed | the role change route, `route_backend_public_workspaces.py` |

Fixed in version: **0.261.146**, tracked in `application/single_app/config.py`.

## Root cause

The management pages are registered as `/groups/<group_id>`
(`route_frontend_groups.manage_group`) and `/public_workspaces/<workspace_id>`
(`route_frontend_public_workspaces.manage_public_workspace`). The notification
links were written by hand with paths that match no registered route, and
nothing checked them against the route map.

## Technical details

### Files modified

- `application/single_app/functions_simplechat_operations.py`: a new
  `_build_group_manage_url(group_id)` returns `/groups/<group_id>`, with the ID
  URL-encoded. The group-created notification and both member-added
  notifications use it.
- `application/single_app/route_backend_groups.py`: the role-changed
  notification links to `/groups/<group_id>`, URL-encoded the same way.
- `application/single_app/route_backend_public_workspaces.py`: the member-added
  and role-changed notifications link to `/public_workspaces/<workspace_id>`,
  URL-encoded the same way.

The notifications' text, `link_context` and metadata are unchanged.

### Tests

`functional_tests/test_group_notification_links_fix.py` (6 cases):
- no application code, including static JavaScript, templates and the V2
  sources, builds a `/manage_group/` path;
- the management page route is the one the links name;
- the group-created, both member-added, and role-changed notifications, sent by
  the real helpers and the real classic routes, link to the group's page;
- every literal group page link in the application resolves to a registered
  page.

`functional_tests/test_public_workspace_notification_links_fix.py` (4 cases):
- no application code builds a `/manage_public_workspace` path;
- the public management page route is the one the links name;
- every literal public workspace page link resolves to a registered page, and
  both fixed notifications resolve to the management page;
- both links URL-encode the workspace ID.

Three of the four public cases fail before the fix.

`functional_tests/test_simplechat_operation_notifications.py` now expects the
corrected group link. It can't run in an environment without `python-docx`,
which `config.py` imports; the new link tests cover the same behaviour.

## Impact

New notifications open the right management page. **Notifications created
before this fix keep the old link,** because each notification stores its own
link. They still show the right text, but opening one leads to a 404. Open the
workspace from **Group Workspaces** or **Public Workspaces** instead.

## Validation

- Before: the six notifications linked to `/manage_group/<group_id>` or
  `/manage_public_workspace?workspace_id=<id>`, which return 404.
- After: they link to `/groups/<group_id>` and
  `/public_workspaces/<workspace_id>`, the registered management pages. The
  tests fail if any code builds either old path again.

## Related

- [Group Directory APIs](../features/GROUP_DIRECTORY_APIS.md)
