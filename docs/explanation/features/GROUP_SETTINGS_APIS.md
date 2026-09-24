# Group Settings APIs (v0.261.154)

## Overview

These routes read and change a named group's settings, and read its activity,
statistics and document count, without touching the account's active group.
They are the server side of the native V2 Settings, Activity and Statistics
views, which arrive in a later release. Until then, group settings are managed
on the classic manage page, which this release also makes safe to use alongside
other changes.

A client can use them to:
- read the group's name, description, color, logo, download setting and
  retention policy, with what the caller may change;
- rename the group, and change its description and color;
- replace or remove the logo;
- turn file downloads off or on for the group;
- set the group's retention periods;
- read the activity feed, the statistics for a window, and the number of the
  group's documents.

Implemented in version: **0.261.154**, tracked in
`application/single_app/config.py`.

The settings stay where they always were, on the group document: `name`,
`description`, `heroColor`, `logoBase64` and `logoVersion`,
`disable_file_downloads` and `retention_policy`. No new setting, container or
index is required.

## Why new routes

The classic routes (`/api/groups/<group_id>`, `/download-settings`, `/logo`,
`/api/retention-policy/group/<group_id>`) work on the group they name, but a
native page can't build on them:
- every writer saved the whole group document with no condition, so a settings
  save could undo a membership change made at the same moment, or recreate a
  deleted group;
- the retention route refused `"default"`, replaced the whole policy with the
  values sent, and checked no feature switch;
- errors carried raw Pillow and Cosmos exception text;
- the activity feed returned raw activity records, with other members' document
  titles, file names, error text and system fields;
- the file count always answered 0.

The classic routes are now fixed too; see the related fixes below. The native
routes add per-section revisions, one policy for every operation, reviewed
messages, and projected activity.

## Availability and roles

Every route needs `enable_group_workspaces` (400 "Enable Group Workspaces is
disabled." otherwise) and a signed-in user with the `User` or `Admin` app role.
The caller must be a member of the group: a missing group is 404
`group_not_found`, "Group not found.", and a non-member gets 403
`group_access_denied`, "You do not have access to the selected group."

One pure policy module, `functions_group_settings_policy.py`, decides what each
caller may do. It follows the classic routes, and a seam test holds it to their
real outcomes in every cell.

| Operation | Owner | Admin | DocumentManager, User |
|---|---|---|---|
| Read the settings | yes | yes | no |
| Name, description, color (`edit_name`, `edit_description`, `edit_color`) | yes, with the `CreateGroups` app role when **Require membership to create groups** is on | no | no |
| Logo (`edit_logo`) | yes | no | no |
| Downloads (`edit_downloads`) | yes, when an administrator allows downloads for the group | the same | no |
| Retention (`edit_retention`) | yes, when group retention policies are on | the same | no |
| Activity and statistics (`view_activity`, `view_stats`) | yes | yes | no |
| Document count (`view_file_count`) | yes | no | no |

- **Group status.** The name, description, color and logo can change only
  while the group is `active` or `upload_disabled`. Otherwise they're refused
  with 403 `group_status_unavailable`:
  - in a `locked` or `inactive` group: "This group is locked or inactive, so
    its name, description, color and logo can't be changed." That matches the
    classic manage page, which makes those fields read-only there;
  - from version **0.261.157**, in a group whose status isn't recognized: "This
    group's status isn't recognized, so its name, description, color and logo
    can't be changed." An unrecognized status fails closed, as the workspace
    context and adding a member do.

  Downloads, retention and every read are allowed in every status, as classic
  allows.
- **Reasons.** A refused operation is 403 with its reason as the `error_code`:
  `group_owner_required`, `group_manager_required`,
  `create_groups_role_required`, `group_status_unavailable`,
  `group_downloads_not_enabled` or `group_retention_disabled`. When several
  apply, the group role is reported first, then the app role, then the status,
  so nobody is told to obtain a role that wouldn't help.
- A write is refused before its body is read.

### Hints

The settings read and the selected-group context
(`GET /api/v2/workspaces/group/<group_id>`) both carry
`settings_management: {schema_version: 1, operations, reasons}`. `operations`
lists what the caller may do; `reasons` gives each other operation's reason
code. Both are built by the same decision the routes enforce, so a V2 page can
decide whether to offer Settings without another read. A client offers only
what `operations` lists.

## Routes

| Method | Path | Body | Success |
|---|---|---|---|
| `GET` | `/api/groups/<g>/settings` | none | 200 `{settings}` |
| `PATCH` | `/api/groups/<g>/settings/profile` | `{revision, name?, description?, hero_color?}` | 200 `{settings}` |
| `PUT` | `/api/groups/<g>/settings/logo` | multipart `logo_file` and `revision` | 200 `{settings}` |
| `DELETE` | `/api/groups/<g>/settings/logo` | `{revision}` | 200 `{settings}` |
| `PATCH` | `/api/groups/<g>/settings/downloads` | `{revision, disable_file_downloads}` | 200 `{settings}` |
| `PATCH` | `/api/groups/<g>/settings/retention` | `{revision, conversation_retention_days?, document_retention_days?}` | 200 `{settings}` |
| `GET` | `/api/groups/<g>/insights/activity?limit=` | none | 200 `{activity, limit}` |
| `GET` | `/api/groups/<g>/insights/stats?days=` or `?start_date=&end_date=` | none | 200 `{stats}` |
| `GET` | `/api/groups/<g>/insights/file-count` | none | 200 `{file_count}` |

Every route has the Swagger security decorator, `login_required`,
`user_required` and `enabled_required("enable_group_workspaces")`. Every
response is sent with `Cache-Control: no-store`. Requests are strict: only the
documented query parameters, a body only where the table shows one, and a JSON
object with no duplicate keys. Anything else is a 400 with
`error_code: "invalid_request"`. No native path matches a classic route;
transport tests pin that.

## Reading the settings

```json
{
  "settings": {
    "schema_version": 1,
    "group_id": "…",
    "viewer_role": "Owner",
    "status": "active",
    "profile": {"name": "…", "description": "…", "hero_color": "#0078d4", "revision": "…"},
    "logo": {"has_logo": true, "logo_version": 3, "logo_url": "/api/groups/…/logo?v=3", "revision": "…"},
    "settings_management": {"schema_version": 1, "operations": ["edit_name", "…"], "reasons": {}},
    "downloads": {"disable_file_downloads": false, "file_downloads_enabled": true, "revision": "…"},
    "retention": {
      "conversation_retention_days": "default",
      "document_retention_days": 90,
      "bounds": {"conversation": {"min_days": 1, "max_days": 3650}, "document": {"min_days": 1, "max_days": 3650}},
      "organization_defaults": {"conversation_retention_days": "none", "document_retention_days": 365},
      "revision": "…"
    }
  }
}
```

- The read is built from the stored fields only. It carries no owner email, no
  member lists, no logo bytes and no Cosmos field.
- `status` is `active`, `locked`, `upload_disabled`, `inactive`, or `unknown`
  for any other stored value.
- `downloads` is present only when an administrator allows downloads for the
  group. `file_downloads_enabled` says whether members can download now, given
  the administrator's switch and the group's own.
- `retention` is present only when group retention policies are on. Stored
  values are shown as the retention job resolves them: missing, empty or
  `"default"` is `"default"`, `"none"` is `"none"`, a number is whole days, and
  anything else is `"none"`. The bounds come from the retention settings
  (default 1 to 3650 days), and the organization defaults from
  `default_retention_conversation_group` and `default_retention_document_group`.

## Writes

Every write returns the settings read as they were committed.

- **Revisions.** Each section (`profile`, `logo`, `downloads`, `retention`)
  carries a `revision`, a digest of that section's stored fields only. A write
  names the revision it was opened at. If the section changed since, it is 409
  `group_settings_changed`, "These settings changed since you opened them.
  Reload them before saving." A change to another section, or to the members,
  doesn't count. A missing revision is a 400.
- **The guard.** Every write goes through
  `update_group_document_with_etag_guard`, which replaces the group document
  only if it hasn't changed since it was read. Each attempt re-checks the
  caller's membership, role, the operation, the group status and the section
  revision on the fresh copy. A group deleted mid-write is 404 and never
  recreated. A group that keeps changing is 409 `group_write_conflict`, "The
  group changed while your request was being saved. Try again."
- **Cache and audit.** The profile and download writes bump the chat bootstrap
  cache with `group_updated`, as the classic writers do. The logo and retention
  writes bump nothing, as they never did. No write records an activity event or
  sends a notification, as in classic.

### Profile

- `name` and `description` use the group creation rules: a name is required,
  at most 80 characters, with no control characters; a description is text of
  at most 500 characters. Both are trimmed. A value equal to the stored one is
  kept as it is, so an older name longer than today's limit can be left alone.
- `hero_color` must be text. As on the classic page, a value that isn't a hex
  color keeps the stored color.
- At least one field is required.

### Logo

- `PUT` takes multipart form data with exactly one `logo_file` and one
  `revision`. The file must be a PNG or JPEG. As in the classic upload, a
  taller image is resized to the stored logo height, and every logo is saved
  as PNG.
- An image that can't be read, including a decompression bomb, is 400 "The logo
  image could not be read. Upload a PNG or JPEG image." with none of the
  decoder's text.
- A stored logo over 1 MiB of base64 is 400 "This logo is too large to store.
  Use a smaller image." The logo lives on the group document, which also holds
  the members and every other setting, so it is kept well under the 2 MB item
  limit.
- `DELETE` clears the logo. With no logo to remove, it is 409 `no_group_logo`,
  "This group has no logo to remove."
- Both increment `logoVersion`, so a cached image is never reused.

### Downloads

`disable_file_downloads` must be `true` or `false`. It is the group's own
switch; the administrator's switch still applies on top of it.

### Retention

Each value is a whole number of days within the bounds, `"none"`, or
`"default"`, the organization default. The values sent are merged into the
stored policy, so sending one keeps the other. Anything else is a 400, for
example "Conversation retention must be between 1 and 3650 days."

## Insights

### Activity

`limit` is 10, 20 or 50, and defaults to 50. The feed reads the records the
classic feed reads, newest first, but selects only the fields it needs, so no
other part of a record leaves Cosmos. Each record becomes:

```json
{"id": "…", "occurred_at": "2026-09-24T12:00:00Z", "type": "document_creation",
 "summary": "Uploaded a document", "actor": {"kind": "member", "display_name": "…"}}
```

- `type` is a known activity type, or `other`.
- `summary` is a reviewed sentence for the type. The only values it takes from
  a record are a token count and the group's old and new status. No name,
  title, file name, email, content, error text, model or conversation ID
  appears.
- `actor` is `member`, with the display name the group has for them;
  `former_member`, for anyone else; or `system`, for work with no person behind
  it, such as a scheduled File Sync run or a status change made by an
  administrator outside the group.

A storage failure is 503 `group_activity_unavailable`.

### Statistics

The window is `days` (7, 30 or 90, and 30 when neither form is given), or a
custom `start_date` and `end_date` of at most 366 days, between 2000-01-01 and
9998-12-31 ("Choose dates between 2000-01-01 and 9998-12-31." otherwise). The
bounds apply after a date's UTC offset. A window that can't be used is a 400
before the group is read, so a 503 only ever means that storage failed. The
figures are the classic `/stats` figures, from the same queries over the same
window: `totalDocuments`, `storageUsed`, `totalTokens`, `totalMembers`,
`storage`, `documentActivity`, `tokenUsage`, `dateRange` and `window`. Two
things differ:
- the invented `storageLimit` is gone;
- a query that fails makes the whole response 503 `group_stats_unavailable`,
  rather than a figure of zero.

A stored timestamp that can't be read is left out of the day-by-day series.

### Document count

`file_count` is the group's own current documents, counted exactly as the group
document list shows them. Superseded revisions and documents shared into the
group aren't counted. It is for the owner, who is asked to remove the group's
documents before deleting it.

## Errors and logging

Every failure is a stable, data-free `error` with an `error_code`. An
unexpected failure is a 500 `group_settings_unavailable`, "The group settings
request could not be completed. Try again.", logged with the error type only.

## Known limitations

- **The V2 Settings, Activity and Statistics views are a later release.** Use
  the classic manage page until then.
- **Classic saves carry no revision,** so a classic save made after a native
  read still wins. The native save that follows it gets a 409 and reloads.
- **Deleting a group stays classic.** The classic page asks the owner to remove
  the group's documents first, but the server doesn't enforce it, and deleting
  doesn't remove the group's other records. This is recorded as a lifecycle
  follow-up.
- **Membership changes don't appear in the activity feed,** as before. Their
  activity records name the group where the feed doesn't look.
- **Classic status rules are unchanged.** The classic routes still accept
  profile and logo changes in locked and inactive groups; only their page hides
  the form.
- **Remaining classic gaps,** recorded for a follow-up:
  - the classic download route turns downloads back on when its body omits the
    field or isn't JSON;
  - the classic retention route answers a body that isn't a JSON object with a
    500;
  - the classic `/api/groups/<group_id>/stats` answers an owner or admin with a
    500 for a custom date at the edge of the calendar. The public workspace
    statistics and the personal activity trends share the same date helpers
    and the same gap.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_group_settings_apis.py` | 203 | The read and every write through the real Flask app: validation and messages, revisions, refusals, guard races, cache effects and the boundary |
| `functional_tests/test_group_insights_apis.py` | 167 | The activity projection, the statistics and their window rules, the document count, and access in every status |
| `functional_tests/test_group_settings_policy.py` | 392 | The policy against the classic routes' real outcomes, for every role, app role, switch and status |
| `functional_tests/test_group_settings_context_seam.py` | 370 | `settings_management` in the selected-group context is the decision the routes enforce |
| `functional_tests/test_group_settings_transport.py` | 50 | The nine declared routes, and that no native path matches a classic route |
| `functional_tests/test_group_settings_legacy_writers.py` | 44 | The classic writers on the guard |
| `functional_tests/test_group_settings_legacy_fixes.py` | 57 | The classic file count, error text and retention fixes |
| `functional_tests/test_group_document_count_predicate.py` | 9 | The count equals the group document list's own rows |

Route policy coverage is updated for the nine routes and the gated classic
retention route.

## Related

- [Group Settings Write Safety Fix](../fixes/GROUP_SETTINGS_WRITE_SAFETY_FIX.md)
- [Group Document Count Fix](../fixes/GROUP_DOCUMENT_COUNT_FIX.md)
- [Group Retention Settings Fix](../fixes/GROUP_RETENTION_SETTINGS_FIX.md)
- [Group Settings Error Text Fix](../fixes/GROUP_SETTINGS_ERROR_TEXT_FIX.md)
- [Group Membership APIs](GROUP_MEMBERSHIP_APIS.md)
- [Group Directory APIs](GROUP_DIRECTORY_APIS.md)
