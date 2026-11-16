# Public Settings APIs (v0.261.185)

## Overview

Routes that name the public workspace in the path, for its **settings** (the
profile, logo, file downloads and retention), its **activity** feed, its
**statistics**, and the **document count** the delete warning quotes. The V2
public workspace's Settings, Activity and Statistics sections use them; see
[V2 Public Settings](V2_PUBLIC_SETTINGS.md).

Implemented in version: **0.261.185**, tracked in
`application/single_app/config.py`.

They follow the group settings routes closely. This page gives the public rules
and the differences; the shared shapes are in
[Group Settings APIs](GROUP_SETTINGS_APIS.md). No new setting, container or
index is required.

## Why new routes

The classic routes (`PATCH`/`PUT /api/public_workspaces/<id>`, its
`/download-settings`, `/logo`, `/activity`, `/stats` and `/fileCount`, and
`POST /api/retention-policy/public/<id>`) write without a revision, check no
workspace status, and some answer failures with an empty list. They're
unchanged, because the classic manage page still uses them. Since version
0.261.173 their writes are conditional; see the
[Public Workspace Writer Safety Fix](../fixes/PUBLIC_WORKSPACE_WRITER_SAFETY_FIX.md).

## Who may do what

One decision, `public_settings_decisions` in `functions_public_settings_policy.py`,
decides every route and the `settings_management` block that the settings read
and the public workspace context publish:

| Operation | Who | Also needs |
|---|---|---|
| Edit the name, description, color and logo | the Owner | an `active` or `upload_disabled` workspace |
| Edit file downloads | the Owner or an Admin | the administrator's download capability for the workspace |
| Edit retention | the Owner or an Admin | public workspaces and `enable_retention_policy_public` on |
| Read the activity | the Owner or an Admin | |
| Read the statistics | the Owner, an Admin or a DocumentManager | |
| Read the document count | the Owner | |

- The status rule for the profile and logo, the retention switches and the
  owner-only document count are native only: the classic routes check none of
  them, and the classic `/fileCount` answers any signed-in user. An
  unrecognized status is read-only.
- When several reasons apply, the role is reported before the status.
- A refusal is 403 with the reason code as `error_code`:
  `public_workspace_owner_required`, `public_workspace_manager_required`,
  `public_workspace_member_required`, `public_workspace_status_unavailable`,
  `public_workspace_downloads_not_enabled` or
  `public_workspace_retention_disabled`, each with its reviewed sentence.

## Routes

`W` is the public workspace ID.

| Method and path | Purpose |
|---|---|
| `GET /api/public-workspaces/W/settings` | The settings, with each section's revision and `settings_management` (the Owner or an Admin) |
| `PATCH /api/public-workspaces/W/settings/profile` | Name, description and color |
| `PUT` and `DELETE /api/public-workspaces/W/settings/logo` | Upload or remove the logo |
| `PATCH /api/public-workspaces/W/settings/downloads` | `disable_file_downloads`, a boolean |
| `PATCH /api/public-workspaces/W/settings/retention` | The conversation and document retention days |
| `GET /api/public-workspaces/W/insights/activity` | The activity feed |
| `GET /api/public-workspaces/W/insights/stats` | The statistics, for a window |
| `GET /api/public-workspaces/W/insights/file-count` | The number of current documents |

Every route carries `@swagger_route(security=get_auth_security())`,
`@login_required`, `@user_required` and
`@enabled_required("enable_public_workspaces")`, and answers
`Cache-Control: no-store`.

## Reading the settings

The read is built from the stored workspace fields, never from the classic
details payload, so it carries no owner email and no member list:
- `profile`: the name, description and hero color;
- `logo`: whether one is stored, its version and its URL;
- `downloads`: only when the administrator allows downloads for the workspace;
- `retention`: only when public retention policies are on, with each value as
  the retention job resolves it (days, `"none"` or `"default"`), and the
  configured bounds.

## Writes

- **Revisions:** each section carries a `revision` over its own stored fields.
  A write names the revision it was opened at, and a stale one is 409
  `public_workspace_settings_changed`, "These settings changed since you opened
  them. Reload them before saving.". Membership and every other workspace field
  are outside every section. Classic saves carry no revision, so a classic save
  landing after a native one still wins.
- **The public guard:** the write re-reads the workspace and re-checks the
  role, the operation, the status and the revision on the copy it writes. A
  workspace deleted mid-write is 404 and never recreated; one that keeps
  changing is 409 `public_workspace_write_conflict`.
- **Profile:** a changed name is at most 80 characters with no control
  characters, and a changed description at most 500, the limits the group
  native settings use; an unchanged stored value is accepted as it is. A color
  that isn't `#RRGGBB` keeps the stored one.
- **Logo:** a PNG or JPEG through the shared branding helper. An unreadable
  image, a decompression bomb included, is 400 "The logo image could not be
  read. Upload a PNG or JPEG image.", and a stored logo is capped at 1 MiB.
  Removing the logo, like an upload, increments `logoVersion`.
- **Retention:** each value is whole days within the configured bounds,
  `"none"` or `"default"`, merged into the stored policy.
- **Effects,** as the classic writers have: the profile and downloads writes
  bump the chat bootstrap cache (`public_workspace_updated`), the logo and
  retention writes bump nothing, and none records activity or a notification.

## Insights

- **Activity:** the workspace's activity records, projected to `id`,
  `occurred_at`, `type`, `summary` and `actor`, with display names only.
  Only records whose `workspace_context` names the workspace are included, so
  the membership audit records aren't, as for groups (decision 11). An actor
  with no stored role in the workspace is `{"kind": "non_member"}`; most are
  readers, since chat usage is logged against the workspace a reader chats in.
  A failed read is 503 `public_workspace_activity_unavailable`, never an empty
  list.
- **Statistics:** the classic statistics queries, run as they are, for a window
  bounded by the shared 366-day limit (a 400 before the workspace is read).
  `storageLimit` is not returned, and `totalMembers` is the Owner plus the
  Admins and DocumentManagers, as classic counts it. A failed query is 503
  `public_workspace_stats_unavailable`.
- **Document count:** the workspace's current documents, counted by the same
  predicate as the V2 document list (`current_public_document_records`), so a
  document with several versions counts once. Classic's `/fileCount` counts
  every stored version.

## Errors and logging

A malformed request is 400 "The request could not be processed.", an unknown
workspace 404 "The selected public workspace was not found.", and an
unexpected failure 500 `public_workspace_settings_unavailable`, "The workspace
settings request could not be completed. Try again.". Unexpected failures are
logged under `[PUBLIC_SETTINGS]` with the error type only.

## Testing and validation

| Suite | Cases | Coverage |
|---|---|---|
| `functional_tests/test_public_settings_policy.py` | 360 | Every role, member format and status against the real classic routes, and each native rule as the only difference |
| `functional_tests/test_public_settings_apis.py` | 210 | Every write, revision, guard race, logo and retention case |
| `functional_tests/test_public_insights_apis.py` | 182 | The activity projection and the statistics, including their failures and the window limits |
| `functional_tests/test_public_settings_transport.py` | 50 | The new routes and the classic ones can't match each other |
| `functional_tests/test_public_document_count_predicate.py` | 10 | The count and the document list share one predicate |
| `functional_tests/test_public_settings_fixture_parity.py`, `test_public_settings_refusal_text_parity.py` | 50, 3 | The V2 fixture and the client's refusal texts against the real routes |

## Related

- [V2 Public Settings](V2_PUBLIC_SETTINGS.md)
- [Group Settings APIs](GROUP_SETTINGS_APIS.md)
