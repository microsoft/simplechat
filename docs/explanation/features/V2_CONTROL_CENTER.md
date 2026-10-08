# V2 Control Center

The V2 Control Center is a permission-aware administration pane for managing SimpleChat. It provides a usage dashboard, user/group/public-workspace management, and activity investigations.

**Dashboard implemented in version:** 0.261.279
**Foundation implemented in version:** 0.261.278
**Users implemented in version:** 0.261.280
**Groups implemented in version:** 0.261.282
**Activity Logs implemented in version:** 0.261.284
**Public Workspaces implemented in version:** 0.261.283
**Current version:** 0.261.300 (Dashboard reorganized with named rankings and plain-language definitions; Chat with this dashboard through the Control Center action)

**Dependencies:** React 18, TypeScript, Vite, Flask session authentication, and the existing Control Center APIs.

## Architecture

The Control Center is a distinct React route (`/control-center` and `/control-center/<section>`), reached from the account menu when the signed-in user has at least one Control Center capability. It is not a primary workspace-navigation item. The internal section rail has a separate per-user collapsed-state preference.

`get_control_center_capabilities()` in `functions_authentication.py` is the shared permission decision for both `control_center_required()` and the `/api/v2/bootstrap` response. When the ControlCenterAdmin role requirement is enabled, that role grants all capabilities; otherwise the regular Admin role grants them. The optional ControlCenterDashboardReader role grants dashboard viewing only when its setting is enabled. The bootstrap payload exposes `can_view_dashboard`, `can_manage_users`, `can_manage_groups`, `can_manage_workspaces`, `can_view_activity_logs`, and `can_run_maintenance`. Since Data health was removed in 0.261.292, no V2 section uses `can_run_maintenance`; it remains part of the shared capability contract.

## Dashboard

Users, Groups and Public Workspaces management are available with `can_manage_users`, `can_manage_groups` and `can_manage_workspaces`, respectively.

The Dashboard is available to users with `can_view_dashboard`, including users assigned the configured ControlCenterDashboardReader role. `GET /api/v2/control-center/dashboard/summary` returns counts and period comparisons; `GET /api/v2/control-center/dashboard/insights` returns the daily sign-in, conversation, upload and token-type series, token use by model, named rankings and the sign-in heatmap. Since 0.261.300 both are thin wrappers around `functions_control_center_dashboard.py`, which the Control Center action shares, so chat answers match the dashboard. Each response is built from two halves cached for 90 seconds in process: one keyed by the date range, and token figures keyed by the date range and token filters, so changing a token filter recalculates only token figures. Pass `force_refresh=1` to bypass both.

Rankings carry each entity's `name`, a `detail` (a user's email) and `found`. Names are read by ID from the users, groups and public-workspaces containers and cached with the same 90-second lifetime; an entity that can no longer be read is reported as **Unknown user**, **Deleted group** or **Deleted public workspace** rather than failing the dashboard.

Neither endpoint runs cross-partition `GROUP BY` or `COUNT` over `DISTINCT` values: the azure-cosmos Python SDK cannot run either, and Cosmos rejects such a query with HTTP 400. Active-user, DAU, WAU and MAU counts count the results of `SELECT DISTINCT VALUE c.user_id`. Uploads by workspace type subtract the `group` and `public` counts from the period total; any other or missing type is personal. Group and public-workspace status counts tally a `SELECT VALUE c.status` projection. Insights stream two narrow projections, the filtered token records and the activity window, and aggregate them in the application. Each login heatmap cell totals one UTC weekday and hour across the whole period, and rankings with equal totals are ordered by ID. See [V2 Control Center Cosmos Query Compatibility Fix](../fixes/V2_CONTROL_CENTER_COSMOS_QUERY_COMPATIBILITY_FIX.md).

The date presets are 7, 30, and 90 UTC calendar days. Custom ranges use `start_date` and `end_date` in `YYYY-MM-DD` format and are limited to 366 days. Since 0.261.300 the dashboard no longer calls the classic `/api/admin/control-center/activity-trends` API; it still uses the token-filter options API and the classic CSV export. Chart data is grouped from the fields written by `functions_activity_logging.py`: `user_login.timestamp`, creation activity types and `workspace_type`, and `token_usage.usage.model`, `usage.total_tokens`, `token_type`, `user_id`, and `workspace_context` IDs. The login heatmap uses UTC and Monday=0.

Invalid dashboard date ranges return a generic validation error rather than exposing exception details.

Group and public-workspace status counts use the stored `status` values (`active`, `locked`, `upload_disabled`, `inactive`); missing values count as active. Unknown group statuses count as active, matching the group permission default, while unknown public-workspace statuses count as inactive, matching its fail-closed permission behavior. Current user, blocked-user, group/workspace status, and pending-approval counts are snapshots. The application does not retain historical snapshots for those dimensions, so their period deltas are intentionally unavailable. Period deltas are shown for login activity, conversations, document creations, document processing failures, and tokens. Processing failures are counted only when a document's stored status text contains “failed” or “error”; when that query is unavailable, the dashboard shows the metric as unavailable rather than zero. Pending approvals are omitted when the aggregate query cannot be completed.

### Control Center query-parameter contract

Dashboard drill-through links set these parameters. A link or chart drill-through is shown only when the viewer's capabilities include the target section, and token drill-throughs carry the active token filters:

| Section | Parameters |
|---|---|
| Users | `user_id`, `last_login`, `status` (legacy `filter=active` is still accepted) |
| Groups | `id`, `status` |
| Public Workspaces | `id`, `status` |
| Activity Logs | `activity_type`, `range`, `date`, `start_date`, `end_date`, `workspace_type`, `workspace_id`, `group_id`, `public_workspace_id`, `user_id`, `search`, `token_type`, `model`, `status` |

Section paths are `/control-center/users`, `/control-center/groups`, `/control-center/public-workspaces`, and `/control-center/activity-logs`. IDs and parameter values are URL-encoded. `date` is a UTC calendar date; `start_date` and `end_date` are inclusive UTC dates. Activity Logs' `range` is a relative window (`today`, `7`, `30` or `90` days ending today, UTC) that saved views and bookmarks keep relative.

## Users

The Users section supports server-side search by email or display name, access and file-upload status filters, last-login windows, document-ownership filtering, sortable usage columns, and paging. It accepts the Dashboard drill-through contract: `user_id` opens that user's detail drawer, `filter=active` selects users active within 30 days, and `status=blocked` selects denied accounts. Direct filters are `access_status`, `upload_status`, `last_login`, and `has_documents`; `search`, `page`, `per_page`, `sort`, and `direction` control search and result ordering. The API validates filter and sort values and binds query values as parameters.

`GET /api/v2/control-center/users` returns cached login, conversation, document, and token metrics with their calculation timestamps. Its response includes the oldest and newest metric timestamps and the count of users on the current page without a cached metric snapshot so administrators can judge freshness. `GET /api/v2/control-center/users/<user_id>` returns the profile and current access/upload restrictions, usage summary, the most recent activity records, and group/public-workspace memberships and ownership.

Each Users query orders a single property, because a two-property `ORDER BY` needs a composite index that `user_settings` does not have. Users with a recorded value for the sort column come first, in the chosen direction. Users without one follow in ID order, so missing values are listed last in either direction, and a page can continue from one population into the other. Equal recorded values have no guaranteed secondary order. The automatic index serves both queries, so existing deployments need no index change.

Administrators can change access or upload restrictions for one user, or select explicit users and users matching the current filters across pages. Filter-based bulk selection supports exclusions and is capped at 500 accounts. Bulk changes use the existing user settings update path so established activity and audit behavior remains in effect. Deleting a user's documents creates an approval request; it does not directly delete the documents.

`GET /api/v2/control-center/users/export.csv` exports all users matching the current filters, in the list's order. It runs its first query before streaming, so a storage failure returns an error rather than a header-only file. CSV cells beginning with `=`, `+`, `-`, or `@` are prefixed to prevent spreadsheet formula execution. The Activity tab's link carries `user_id` into the Activity Logs section.

## Groups

Implemented in version: **0.261.282**, tracked in `application/single_app/config.py`.

The Groups section helps administrators find shared workspaces that need attention, inspect their membership and usage, and perform audited status changes without losing the classic approval boundaries. Dashboard links with `id` open the drawer; `status` filters the list. Every new endpoint uses the existing Control Center Blueprint login policy, Swagger security decorator, and `control_center_required('admin')`.

### List and selection contract

`GET /api/v2/control-center/groups` accepts:

| Parameter | Meaning |
|---|---|
| `search` | Case-insensitive substring of group name or description, up to 200 characters |
| `status` | `active`, `locked`, `upload_disabled`, `inactive`, or `all`; missing/null/unknown stored status is displayed as active |
| `owner` | Case-insensitive substring of owner ID, name, or email, up to 200 characters |
| `members_min`, `members_max` | Inclusive whole-number bounds, including the owner |
| `has_documents` | `yes`, `no`, or `all`, based on document metadata records, not chunks |
| `created_from`, `created_to` | Inclusive creation dates in `YYYY-MM-DD` |
| `activity_from`, `activity_to` | Inclusive last-recorded-activity dates in `YYYY-MM-DD`; missing activity does not match a date window |
| `sort`, `direction` | Name, owner, members, documents, tokens, or last activity; `asc`/`desc`, default name ascending |
| `page`, `per_page` | Server paging, default 25 and maximum 250 rows |
| `force_refresh=1` | Rebuild the server inventory instead of using its 90-second cache |

`functions_control_center_groups.py` builds an inventory with four batched Cosmos queries. One projects the groups. The other three stream narrow projections that the application aggregates into document counts, all-time token totals and latest activity timestamps: document metadata group IDs, group token records, and a coalesced group ID with timestamp. The Python Cosmos SDK cannot run cross-partition `GROUP BY`. Activity includes the top-level `group_id`, nested `group.group_id`, and `workspace_context.group_id` writer shapes. `GROUP` is a reserved word in Cosmos SQL, so the nested shape is read as `c['group']['group_id']`; the dotted `c.group.group_id` is a syntax error that rejected the whole inventory query until 0.261.296. Filtering, sorting and paging occur on the server after aggregation; neither the browser nor per-row enrichment performs filtering or counting. This deliberately avoids N+1 queries and Cosmos ordering on undefined/computed fields. Tied sort values use stable ID ordering and missing activity sorts last in either direction. Failed aggregates fail the request rather than silently reporting zero. A legacy group document with a non-object owner, non-object member entries or a non-text name is listed with those values treated as missing instead of failing the whole list. List and detail failures log the Cosmos status code with the error type.

The response includes `groups`, `pagination`, and `metrics_freshness` with the snapshot's `calculated_at`, source and TTL. List/CSV totals can lag external writes by up to 90 seconds; **Refresh groups** bypasses the cache. Rebuild cost scales with the number of group documents and all-time group token and activity records, while memory holds only per-group totals. This is not continuation-token pagination. Legacy storage-size estimates retain their own older refresh timestamp and are not represented as current counts.

`POST /api/v2/control-center/groups/bulk-status` accepts either `group_ids` or a `filter` object, plus `status` and `reason`. Filter selection accepts the same filter fields, supports `exclude_ids`, and resolves against a fresh server inventory. The full population is capped at 500 before any writes occur. Locked/inactive status requires a nonblank reason (maximum 2,000 characters). `PUT /api/v2/control-center/groups/<id>/status` has the same reason rule. Both call the classic single-status writer, preserving etag conflict handling, status history, activity logging and App Insights audit events. Partial results report `success_count`, `failed_count`, and individual `failed_groups`; unchanged groups succeed without duplicate audit records. The classic status route keeps its existing optional-reason behavior.

`GET /api/v2/control-center/groups/export.csv` exports the entire filtered/sorted inventory, not just the visible page, with spreadsheet-formula-safe cells.

### Drawer and existing actions

`GET /api/v2/control-center/groups/<id>` reads current ownership, members, roles and status history, then returns the overview, retention policy, document summary, token total and the 20 most recent projected activity records. It does not expose model endpoints, credentials, logos, or the raw group document. The activity view shows the returned record as JSON and exports that recent subset as CSV. **View in Activity Logs** carries `workspace_type=group`, `workspace_id`, and `group_id` to the scoped Activity Logs investigation.

The drawer has Overview, Members, Ownership, Status, Retention, Activity and Documents tabs. Owner and member links open the Users drawer. `EntityDetailSections.tsx` provides reusable keyboard-operable detail tabs, timeline/JSON presentation and date formatting for later workspace management. `DetailDrawer` reuses the application's modal focus trap, focus restoration and innermost-dialog Escape handling.

Member addition reuses `/api/userSearch` and the existing admin `/groups/<id>/add-member` endpoint. The shared directory-search and CSV-import dialogs retain validation, a 1,000-row import limit, per-row outcomes and retry support. CSV columns are `userId,displayName,email,role`; the admin add flow trusts the supplied member identity fields, so verify CSV data before importing. Supported roles are Admin, DocumentManager and User, mapped to the existing endpoint's `admin`, `document_manager`, and `user` tokens.

Removing members and changing roles reuse the existing `/api/groups/<id>/members/<member_id>` DELETE/PATCH routes. Those operations still require current group Owner/Admin membership; a Control Center role alone does not confer it. The owner cannot be removed or assigned a member role. Retention uses the existing `/api/retention-policy/group/<id>` POST route, requires group Owner/Admin membership and enabled group retention, and accepts `default`, `none`, or organization-bounded whole-number days. Nonmember administrators can inspect these settings and request ownership rather than bypassing the existing membership rules.

Delete group, delete all documents, take ownership and transfer ownership reuse the existing admin approval APIs. Each requires a reason and returns an approval ID, not a performed deletion or ownership change. Transfer recipients must already be members; the UI excludes the current owner. The shared submitted notice links to `/v2/approvals/all/<approval_id>?group_id=<group_id>` using a basename-aware router link, matching the V2 Approvals contract (PR #1687), instead of adding an approvals queue to Control Center. User requests use the same detail destination without a group filter.

### Validation

`functional_tests/test_v2_control_center_groups.py` exercises filters/sorts/paging, cache reuse/expiry, detail projection, roles, bulk cap/exclusions/reasons, real status-writer audit parity, denied access, formula-safe export, and approval creation without direct mutation. `ui_tests/test_v2_control_center_groups.py` covers desktop/mobile drawers, URL filters, cross-page bulk selection, partial failures, status history, escaped text/raw JSON, member search/CSV/roles/removal, retention, ownership approvals and permission-limited controls. Route policy tests include all five new routes; prior Control Center layers and `test_v2_api_security.py` are included in regression validation.

## Activity Logs

Implemented in version: **0.261.284**, tracked by `VERSION` in `application/single_app/config.py`. Redesigned in **0.261.296**.

Activity Logs is an investigation surface for administrators with `can_view_activity_logs`. It links dashboard trends, a user's recent activity, and workspace timelines to the same filtered evidence, and answers who did what, where and when in human terms: people and workspaces appear by name, and any person, activity type or workspace in a row filters the log to it. All five APIs use the existing login-protected Control Center Blueprint, `@swagger_route(security=get_auth_security())`, and `control_center_required('activity_logs')`; dashboard-only readers cannot query, look up names or export activity.

### Query and paging contract

`GET /api/v2/control-center/activity-logs` accepts inclusive UTC `start_date`/`end_date`, or the dashboard's single-day `date`. The default is the latest 30 UTC dates; ranges are limited to 366 days. Filters include repeated or comma-separated `activity_type` values (OR within types, AND with other filters), `user_id`, `workspace_type`, `workspace_id`, `group_id`, `public_workspace_id`, `search`, `token_type`, `model`, and recorded `status`. Search is a case-insensitive substring across stored IDs, actor emails, names, descriptions, file names, conversation titles and model names, not a full-text index. It is parameterized, limited to 200 characters, and does not trigger Graph enrichment.

Since 0.261.296 search also finds what a person did when the term matches their name or email. When the term has at least two characters, the route looks up to 25 SimpleChat users whose `user_settings` display name or email contains it and adds them to the search as actors. The page, summary and export reuse a term's matches from the same five-minute cache as the names. More than 25 matches sets `search_people.truncated`, and the page suggests the Person filter. The matched IDs widen the search only; they are not part of the cursor's filter scope, so paging continues if a new user matches between pages. A failed people lookup is logged and the search falls back to the stored fields.

The query recognizes top-level and nested group/public-workspace identifiers and the historical `public_workspace` workspace-type spelling. `GROUP` is a reserved word in Cosmos SQL, so the nested `group` object is read as `c['group']`; before 0.261.296 the dotted form made every search and every group filter fail with HTTP 400. `workspace_id` requires a workspace type; for personal workspaces it matches the user's ID. A specific group or public workspace matches every record that references it, whatever workspace type the writer stored, so membership removals and role changes, which record a group but no workspace type, are included. Group references are read from `workspace_context.group_id`, `group_id`, `group.group_id` and `workspace_context.group_workspace_id` (user agreement acceptances). Public workspace references are read from `workspace_context.public_workspace_id`, `public_workspace_id`, `public_workspace.public_workspace_id` (membership removals and access requests), `public_workspace.workspace_id` (status changes) and the bare `workspace_id` that public workspace ownership approvals record. A workspace type on its own (`group` or `public`) matches records of that type or that reference such a workspace. The person filter matches every field where writers record who acted: `user_id`, `admin_user_id`, `requester_id`, `added_by_user_id`, `changed_by_user_id`, `changed_by.user_id`, `removed_by.user_id`, `admin.user_id` and `actor.user_id`. `status=failed` matches recorded failure/error text; it does not infer failures from unrecorded events.

Responses contain `items`, `presentation`, `filter_labels`, `search_people`, `next_cursor`, `page_size`, and `snapshot`. Page size defaults to 50 and is bounded at 200. Paging uses a descending keyset of the **stored timestamp string, ID, and user partition**, not Cosmos continuation tokens, `OFFSET`, or a total-count scan. The partition tie-breaker is required because Cosmos IDs are unique only within a partition. Cursors retain the original timestamp spelling, distinguish missing/null partition values, carry a time cutoff, and reject reuse with different filters. Refresh starts a new sequence. The cutoff excludes newer timestamped events, but is not a Cosmos transactional snapshot: deletion, edits, or late/backdated writes can change an ongoing investigation. Records without string timestamps or IDs, or with malformed non-string/non-null user partitions, cannot participate in this ordered feed; legacy browsing remains available for those records.

### Readable presentation and names

`functions_control_center_activity_display.py` turns each record into the presentation the table, detail drawer and CSV export share, so an activity reads the same everywhere. It has no Flask or Azure dependency; the route passes the containers in. `presentation[i]` describes `items[i]` and contains:

| Field | Meaning |
|---|---|
| `label`, `category` | A readable activity type ("Token usage") and its group (Sign-in and consent, Chat and conversations, Documents, Token usage, Groups, Public workspaces, Approvals and administration, Agents/actions/workflows, Data and sync, Other). Unknown types are humanized. |
| `summary`, `detail` | What happened, ported from the classic Control Center's per-type formatting: token totals and model, file names, conversation titles, status transitions, members and roles, approval requesters and approvers, file sync counts, data management jobs, agent and workflow runs. |
| `facts` | Label/value pairs for the drawer's Details section. |
| `status` | `failed` when the record's status, document status, run status or error mentions a failure. |
| `actor` | `id`, `name`, `email`, `kind` (`user` or `system`) and `resolved`. The first recorded actor field wins (see the person filter above); `system`/`unknown` IDs and records without an actor read as System. |
| `workspace` | `type`, `id`, current `name` and `resolved`. Falls back to the name recorded on the activity when the workspace no longer exists. |

Names come from SimpleChat's own `user_settings`, `groups` and `public_workspaces` documents, the same source the classic Control Center used, never from Microsoft Graph. Each page resolves its IDs with at most one parameterized `ARRAY_CONTAINS(@ids, c.id)` query per kind (100 IDs per batch) and keeps results, including misses, in a 5-minute in-process cache of up to 5,000 entries. A lookup failure is logged and the page is returned with IDs instead of names. `filter_labels` carries the names for the current person and workspace filters, so the toolbar never shows a bare ID after a Dashboard, Users or Groups drill-through.

Two lookups back the filter pickers:

- `GET /api/v2/control-center/activity-logs/people?q=` returns up to 10 SimpleChat users whose display name or email contains the term, or whose ID equals it, as `{"people": [{"id", "display_name", "email"}]}`.
- `GET /api/v2/control-center/activity-logs/workspaces?q=` returns up to 10 groups and 10 public workspaces whose name contains the term, or whose ID equals it, as `{"workspaces": [{"type", "id", "name"}]}`.

Terms shorter than two characters return an empty list without a query; terms over 200 characters return 400. Exact ID and exact name matches rank first. These endpoints reveal names and emails only to Control Center administrators, the same population that can already list users and groups.

### Index rollout

New `activity_logs` containers receive the composite index on `/timestamp`, `/id`, `/user_id`, all descending, in `config.py`. **Existing deployments must apply the expected indexing policies using the existing Admin Settings App Maintenance tooling and wait for Cosmos index transformation before using the new feed.** `functions_cosmos_indexing.py` registers the index, preserves existing indexing paths and composites, and retains the maintenance setting/explicit-apply controls; opening Activity Logs never changes a cloud policy. An unavailable index produces a visible, generic API error with an App Maintenance recovery instruction. The partition key remains `/user_id`; browsing and export are cross-partition queries.

### Bounded distribution and export

`GET /api/v2/control-center/activity-logs/summary` applies the same filters, including the people search, and projects the newest **at most 5,000** matching records, using one extra projected row to detect truncation. It returns activity-type facets with their `label` and `category`, a UTC histogram with no more than 31 buckets, bucket width, sample size/limit, `truncated`, and `type_catalog`, the list of labelled activity types the Activity filter offers. Facets describe the current filtered result, including selected activity types; they are not disjunctive counts of unselected categories. When truncated, the UI says the trend and counts use the newest 5,000 records rather than presenting full-range totals.

`GET /api/v2/control-center/activity-logs/export.csv` streams the same filtered order in page-sized reads, with an upper limit of **10,000 activity rows** and a final `export_limit_reached` status row when the cap is reached. Narrow the filters for a complete larger investigation. The columns are `timestamp`, `id`, `user_id`, `activity_type`, `workspace_type`, `user_name`, `user_email`, `activity`, `summary`, `workspace_id`, `workspace_name` and `raw_json`. The first five and the trailing raw JSON keep their 0.261.284 positions; the readable columns between them come from the same presentation as the table, with names resolved per batch. Cells beginning with `=`, `+`, `-`, `@`, tab or carriage return are apostrophe-prefixed, including whitespace-prefixed formulas. It is an uncached attachment with `X-Export-Row-Limit`. The first storage query runs before response headers; later storage failures log and interrupt the stream rather than producing a success-shaped fallback.

### Browser behavior

`ActivityLogsSection.tsx` orchestrates the components in `components/controlCenter/activityLogs/`; `lib/activityLogs.ts` owns the URL contract, date presets and time formatting. From top to bottom the page shows:

1. **Header actions:** **Views**, **Refresh** and **Export CSV**.
2. **Filter pills** (`ActivityFilterBar.tsx`, `FilterPill.tsx`): a search field followed by Date, Activity, Person and Workspace pills and **Add filter** (Model, Token type, Recorded status). Each pill shows its current value in human terms, opens its editor in a portalled popover, and applies as soon as it changes; there is no Apply step. Search applies 400 ms after typing stops, or on Enter; the field keeps what is being typed while the URL updates. The Person and Workspace pickers (`EntityCombobox.tsx`) follow the ARIA combobox pattern and search the lookups above, so administrators pick people and workspaces by name or exact ID. When the text looks like an ID (no spaces or `@`, and a digit or hyphen) and nothing in SimpleChat has that ID, the picker offers **Filter by user ID** or **Filter by group ID** / **Filter by public workspace ID**, so activity of someone or something since removed can still be investigated. **Reset filters** appears whenever the filters differ from the default.
3. **Trend strip** (`ActivityTrendStrip.tsx`): the record count and bucket width, one bar per UTC bucket, and the top four activity types with counts. The bars are buttons in a single-tab-stop toolbar: arrow keys, Home and End move between them, and Enter narrows the date range to that bucket. Selecting a top type toggles it as a filter. The strip collapses to its count line.
4. **Log table** (`ActivityTable.tsx`): Time, Person, Activity, Details and Workspace. Selecting a person, activity type or workspace filters by it; selecting the details or the row opens the record. Below the `md` breakpoint the rows stack instead. Loading shows skeleton rows; an empty result offers to widen the range to 90 days or reset the filters.
5. **Detail drawer** (`ActivityDetailDrawer.tsx`): the summary, then Who (with **Show only this person's activity** and **Open in Users**), Where (with **Show only this workspace** and **Open group** or **Open workspace**), Details, Record (raw type, UTC and local time, record ID, approval link) and collapsed raw JSON with **Copy JSON**. **Previous** and **Next** step through the page.

The URL is the investigation's state. A relative range is written as `range` (`today`, `7`, `90`; the default 30 days is implied), and a custom window as `start_date`/`end_date`. Existing links keep working: `date`, `group_id`, `public_workspace_id` and `workspace_type=public_workspace` are read and normalized to `workspace_type` and `workspace_id`. The API always receives explicit dates. A relative range re-reads the UTC date whenever a filter changes, on **Refresh**, before **Export CSV**, and when the administrator returns to the tab, so a page left open past UTC midnight does not keep querying the previous day.

Selecting a person, activity type, workspace or trend bar in the log, or a **Show only** button in the drawer, replaces the rows it was chosen from, so keyboard focus moves to the matching filter pill, which now shows the new value. Clearing a pill keeps focus on it; clearing or cancelling an added filter moves focus to **Add filter**.

Times show in the browser's local time by default with the UTC time on hover; the **Local time | UTC** choice, row density and the trend strip's visibility are stored in the `v2ActivityLogPrefs` user setting. Saved views are stored on the account in the `v2ActivityLogSavedViews` user setting (up to 30, names up to 60 characters), so they follow the administrator across browsers. A view stores the canonical filter query, so "last 7 days" stays relative. Views saved by earlier versions in this browser's `localStorage` are merged into the account once, by name with the account's copy winning, and the local copy is removed after the save succeeds. While the account's settings are loading, or if they failed to load, the menu cannot save, rename or delete views and the browser copy is left in place, because a change built on views that never loaded would replace the account's real ones. The **Views** menu also offers quick views for recent sign-ins, recent token usage and document processing failures.

Untrusted text renders as React text; raw JSON is escaped. Router links are built from literal paths with encoded IDs and omit `/v2` because the application basename supplies it. All browser assets remain local.

### Validation

`functional_tests/test_v2_control_center_activity_logs_queries.py` covers ties across partitions, timestamp spelling, cursor/filter validation, parameter binding, the person filter's actor fields, workspace matching, people-widened search outside the cursor scope, bounded sampling, histogram buckets, streamed export with readable columns and formula injection. Every generated query passes the Cosmos query guard. `functional_tests/test_v2_control_center_activity_display.py` covers labels, per-writer summaries, malformed records, actor and workspace resolution, batched and cached lookups, ranked people and workspace searches, and CSV columns. `functional_tests/test_v2_control_center_activity_logs_routes.py` executes the actual handlers and permission decorators, including denial before storage access, generic errors, degraded name lookups and the two lookup routes. The indexing-maintenance regression verifies safe index merging. `ui_tests/test_v2_control_center_activity_logs.py` covers, against built local assets at desktop and mobile sizes: rows visible in the first viewport, names instead of IDs, cross-filters from rows and the drawer with focus moving to the matching pill, each pill including keyboard pickers and the filter-by-ID option for removed users and workspaces, search text kept while the URL updates, deep links rendered as named pills, keyboard trend drill-through, relative ranges moving to the new UTC day on Refresh and export (using Playwright's clock), the drawer's sections and escaped JSON, the remembered time zone and density, account-backed saved views with the one-time import, saved views locked when settings cannot load, paging, export, empty/error recovery and capability gating. These isolated checks do not replace a live Cosmos query smoke test.

## Public Workspaces

Implemented in version: **0.261.283**, tracked in `application/single_app/config.py`.

The Public Workspaces section helps administrators review public knowledge collections, their responsible managers, restrictions and usage. It reuses the Groups detail drawer, membership dialogs, keyboard-operated tabs, reason confirmation, activity presentation and shared approval notice. Dashboard `id` and `status` deep links retain their meaning.

### Query-backed list and selection

`GET /api/v2/control-center/public-workspaces` accepts `search` (name/description substring), `owner` (stored owner name/email/ID substring), `status`, `page`, `per_page`, `sort` and `direction`. Search/owner text is limited to 200 characters, pages to 100,000, and page size to 250 (default 25). Invalid inputs fail before storage access. Status values are active, locked, upload_disabled and inactive; missing, null and empty status is active, and unrecognized stored strings are inactive.

`functions_control_center_public_workspaces.py` applies parameterized search, owner and status predicates to Cosmos counts and paginated queries, **not an in-memory workspace inventory**. Sort choices are name, stored owner display name, created date, recorded documents, recorded tokens and recorded last activity. A separate missing-value population places unavailable sort fields last without dropping those workspaces. Each query orders one property and uses the existing automatic indexes, not a new composite index. Equal recorded values have no guaranteed secondary ordering, and concurrent writes can shift OFFSET pages; this is live offset pagination, not a stable snapshot or continuation-token cursor.

The list reads recorded `metrics.document_metrics`, `metrics.token_metrics` and `metrics.last_activity` fields from the returned page. There are no per-row metric or directory queries. Unrecorded statistics are unavailable rather than zero, and every row shows the stored metric refresh timestamp. **Refresh workspaces** rereads stored records; it does not recalculate metrics. In particular, the legacy public-workspace refresh does not currently record token totals, so those list cells can remain unavailable. Detail views calculate live metadata-document and activity-log token totals separately.

`POST /api/v2/control-center/public-workspaces/bulk-status` accepts either `workspace_ids` or `filter` with optional `exclude_ids`, plus `status` and `reason`. Filter selection queries at most 501 IDs after exclusions and rejects populations above 500 **before writing anything**. Locked/inactive changes require a reason of at most 2,000 characters. `PUT /api/v2/control-center/public-workspaces/<id>/status` applies the same validation. Both reuse the classic guarded status writer with its etag conflict handling, status history and audit logging. Partial failures return `failed_workspaces` alongside success/failure counts.

Bulk controls are status-only. Setting active unlocks and enables uploads, as in classic lock/unlock and upload-enable actions. V2 does not expose the classic bulk `delete_documents` action, which deletes directly and differs from individual document-deletion approval requests.

`GET /api/v2/control-center/public-workspaces/export.csv` honors the same filters and server sorting across pages, exports at most 10,000 workspaces, and protects every cell against spreadsheet formula injection. Narrow filters when the limit is exceeded. Export shares live offset pagination's concurrent-write limitation.

### Details and existing behavior

`GET /api/v2/control-center/public-workspaces/<id>` projects current owner, managers, history and retention, computes document metadata count and all-time recorded token usage, and returns the most recent 20 projected activity records. Activity failures fail the detail request instead of producing an empty success. Raw JSON and local CSV export apply to this returned, allowlisted subset, not the full storage document. Links carry `workspace_type=public`, `workspace_id` and `public_workspace_id` to Activity Logs (Phase 6), and owner/manager links open Users.

Unlike Groups, public readers are implicit; only Owner, Admin and DocumentManager are stored. Legacy string identities are shown by ID without uncached directory lookup. Addition/CSV uses classic `/add-member` with `admin` or `document_manager`; the unsupported `user` role is never offered. CSV identities are trusted by that existing admin path and should be verified before import. Native `/api/public_workspaces/<id>/members/<member_id>` PATCH/DELETE still require workspace Owner/Admin membership and enabled public workspaces. Owner and self-removal controls are excluded. Control Center access does not bypass those membership checks.

Retention uses `/api/retention-policy/public/<id>` with the existing Owner/Admin rules. It accepts `none` or organization-bounded numeric days. The public save API does **not** accept `default`: inherited fields are omitted from writes, and resetting a custom policy to inherited defaults is unavailable in this drawer. Organization retention defaults remain managed through existing admin settings.

Take ownership POST, ownership PUT with `newOwnerId`, documents DELETE and workspace DELETE reuse existing classic admin routes with a required reason. On this branch both deletion routes already create approvals; this release does not introduce a new deletion authorization policy. Submission displays the returned approval ID and links to `/v2/approvals/all/<id>?group_id=<workspace_id>`; it never claims deletion or ownership execution. The approval's `metadata.entity_type=workspace` dispatches to public-workspace executors, using `group_id` as the existing approval partition/scope key, not the Groups container.

An existing executor limitation remains: document deletion catches individual document errors and reports the successful deletion count. The workspace executor can consequently delete the workspace after partial document cleanup. This release does not change those destructive semantics; inspect the approval execution result and logs for cleanup failures.

### Validation

`functional_tests/test_v2_control_center_public_workspaces.py` exercises query-level filters/paging, missing-status normalization, sorts with unavailable metrics, bounded inputs, admin-versus-reader access, bulk cap/exclusions/partial failures, real guarded audit writes, safe filtered CSV, detail projection and actual public-scope approval dispatch. `ui_tests/test_v2_control_center_public_workspaces.py` exercises the built local bundle at desktop/mobile sizes: filters/sorts, cross-page selection, partial errors, details/history/raw JSON, supported member roles/CSV, public retention payloads, ownership and deletion approval requests. Existing Groups, Users, foundation, dashboard, API security, public writers and route-policy checks remain regression coverage.

## Usage

Open **Account → Control Center**, then select a section in its internal rail. A bookmarked section URL opens that section directly; an unknown section, such as a bookmark to the removed Data health page, opens the Dashboard. On the Dashboard, select a date range; the page is organized into Directory, Sign-ins, Conversations and documents, Token usage and Most active sections, and each figure states what it counts. Token filters sit inside the Token usage section and change only its figures. Charts include accessible data tables, and chart selections link to the matching filtered activity view. Export downloads the trend data as CSV. **Chat with this dashboard** opens a new orchestrated chat with a prompt about the dashboard on screen, or lists what must be set up first; see [Control Center Action](CONTROL_CENTER_ACTION.md).

## Testing and limitations

Functional checks cover dashboard status normalization, period deltas, cache expiry and refresh, dashboard-reader access, capability parity, bootstrap exposure, and route wiring. Dashboard named rankings and daily series are covered by `functional_tests/test_v2_control_center_dashboard.py`; the Control Center action and dashboard chat readiness by `functional_tests/test_v2_control_center_action.py`. `ui_tests/test_v2_control_center_dashboard.py` covers the sections, definitions, names, token filter scope, capability-aware links, chart drill-through, the requirements checklist and the prompt hand-off into a new orchestrated chat. Route-level tests run the real Dashboard and Users handlers, and the Groups inventory, against fake containers that reject query shapes the Python Cosmos SDK cannot run. `functional_tests/test_v2_control_center_cosmos_query_compatibility.py` scans every V2 Control Center SQL string for cross-partition `GROUP BY`, `COUNT` over `DISTINCT` values, and multi-property `ORDER BY` without a declared composite index. Since 0.261.296 it also rejects reserved keywords (such as `group`, `value` or `order`) used as dotted property names or aliases in every Control Center query, classic routes included, and checks the generated Activity Logs search and group filters, which a static scan cannot see. Playwright coverage verifies capability-based section visibility and that the removed Data health section stays absent, including for its old URL. Top activity and token rankings are limited to entities present in the recorded `user_id` and workspace-context fields; unlogged historical status snapshots and model/provider details are not inferred.

## Version tracking

The application version is defined by `VERSION` in `application/single_app/config.py`. The foundation was added in **0.261.278**, the dashboard in **0.261.279**, user management in **0.261.280**, group management in **0.261.282**, public workspace management in **0.261.283**, and Activity Logs in **0.261.284**. In **0.261.292**, the Dashboard, Users and Groups queries were made compatible with the Python Cosmos SDK. The same release removed the Data health section and its `GET /api/admin/control-center/migrate/status` and `POST /api/admin/control-center/migrate/all` backfill APIs; the classic Control Center had already stopped using them. In **0.261.296**, the Groups list, group details, the Activity Logs group filter, Activity Logs search and the classic group activity timeline stopped failing on the reserved `group` keyword (see [V2 Control Center Reserved Keyword Query Fix](../fixes/V2_CONTROL_CENTER_RESERVED_KEYWORD_QUERY_FIX.md)), and Activity Logs was redesigned around filter pills, names and account-backed saved views. In **0.261.300**, the Dashboard was reorganized with named rankings and plain-language definitions, gained **Chat with this dashboard** and `GET /api/v2/control-center/dashboard/chat-readiness`, and the broken `POST /api/admin/control-center/activity-trends/chat` endpoint and the classic page's unreachable chat modal were removed. See [V2 Control Center Dashboard Usability Fix](../fixes/V2_CONTROL_CENTER_DASHBOARD_USABILITY_FIX.md).
