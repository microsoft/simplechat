# V2 Control Center

The V2 Control Center is a permission-aware administration pane for managing SimpleChat. The foundation release provides the shared navigation and capability contract, placeholders for management areas that will arrive in later phases, and a manual activity-log data-health tool.

**Dashboard implemented in version:** 0.261.279
**Foundation implemented in version:** 0.261.278
**Users implemented in version:** 0.261.280
**Groups implemented in version:** 0.261.282
**Public Workspaces implemented in version:** 0.261.283
**Current version:** 0.261.285 (including public workspace validation-safety fixes)

**Dependencies:** React 18, TypeScript, Vite, Flask session authentication, and the existing Control Center APIs.

## Architecture

The Control Center is a distinct React route (`/control-center` and `/control-center/<section>`), reached from the account menu when the signed-in user has at least one Control Center capability. It is not a primary workspace-navigation item. The internal section rail has a separate per-user collapsed-state preference.

`get_control_center_capabilities()` in `functions_authentication.py` is the shared permission decision for both `control_center_required()` and the `/api/v2/bootstrap` response. When the ControlCenterAdmin role requirement is enabled, that role grants all capabilities; otherwise the regular Admin role grants them. The optional ControlCenterDashboardReader role grants dashboard viewing only when its setting is enabled. The bootstrap payload exposes `can_view_dashboard`, `can_manage_users`, `can_manage_groups`, `can_manage_workspaces`, `can_view_activity_logs`, and `can_run_maintenance`.

## Dashboard

Users, Groups and Public Workspaces management are available with `can_manage_users`, `can_manage_groups` and `can_manage_workspaces`, respectively.

The Dashboard is available to users with `can_view_dashboard`, including users assigned the configured ControlCenterDashboardReader role. `GET /api/v2/control-center/dashboard/summary` returns counts and period comparisons; `GET /api/v2/control-center/dashboard/insights` returns grouped chart data. Both use a 90-second in-process cache keyed by the date range and token filters. Pass `force_refresh=1` to bypass it.

The date presets are 7, 30, and 90 UTC calendar days. Custom ranges use `start_date` and `end_date` in `YYYY-MM-DD` format and are limited to 366 days. The trend charts reuse the existing activity-trends and token-filter APIs, CSV export, and “Chat with these trends” endpoint. Chart data is grouped from the fields written by `functions_activity_logging.py`: `user_login.timestamp`, creation activity types and `workspace_type`, and `token_usage.usage.model`, `usage.total_tokens`, `token_type`, `user_id`, and `workspace_context` IDs. The login heatmap uses UTC and Monday=0.

Invalid dashboard date ranges return a generic validation error rather than exposing exception details.

Group and public-workspace status counts use the stored `status` values (`active`, `locked`, `upload_disabled`, `inactive`); missing values count as active. Unknown group statuses count as active, matching the group permission default, while unknown public-workspace statuses count as inactive, matching its fail-closed permission behavior. Current user, blocked-user, group/workspace status, and pending-approval counts are snapshots. The application does not retain historical snapshots for those dimensions, so their period deltas are intentionally unavailable. Period deltas are shown for login activity, conversations, document creations, document processing failures, and tokens. Processing failures are counted only when a document's stored status text contains “failed” or “error”; when that query is unavailable, the dashboard shows the metric as unavailable rather than zero. Pending approvals are omitted when the aggregate query cannot be completed.

### Control Center query-parameter contract

Dashboard drill-through links set these parameters for the management sections being delivered in later phases:

| Section | Parameters |
|---|---|
| Users | `user_id`, `filter`, `status` |
| Groups | `id`, `status` |
| Public Workspaces | `id`, `status` |
| Activity Logs | `activity_type`, `date`, `start_date`, `end_date`, `workspace_type`, `workspace_id`, `group_id`, `user_id`, `token_type`, `model`, `status` |

Section paths are `/control-center/users`, `/control-center/groups`, `/control-center/public-workspaces`, and `/control-center/activity-logs`. IDs and parameter values are URL-encoded. `date` is a UTC calendar date; `start_date` and `end_date` are inclusive UTC dates.

## Users

The Users section supports server-side search by email or display name, access and file-upload status filters, last-login windows, document-ownership filtering, sortable usage columns, and paging. It accepts the Dashboard drill-through contract: `user_id` opens that user's detail drawer, `filter=active` selects users active within 30 days, and `status=blocked` selects denied accounts. Direct filters are `access_status`, `upload_status`, `last_login`, and `has_documents`; `search`, `page`, `per_page`, `sort`, and `direction` control search and result ordering. The API validates filter and sort values and binds query values as parameters.

`GET /api/v2/control-center/users` returns cached login, conversation, document, and token metrics with their calculation timestamps. Its response includes the oldest and newest metric timestamps and the count of users on the current page without a cached metric snapshot so administrators can judge freshness. `GET /api/v2/control-center/users/<user_id>` returns the profile and current access/upload restrictions, usage summary, the most recent activity records, and group/public-workspace memberships and ownership.

Administrators can change access or upload restrictions for one user, or select explicit users and users matching the current filters across pages. Filter-based bulk selection supports exclusions and is capped at 500 accounts. Bulk changes use the existing user settings update path so established activity and audit behavior remains in effect. Deleting a user's documents creates an approval request; it does not directly delete the documents.

`GET /api/v2/control-center/users/export.csv` exports all users matching the current filters. CSV cells beginning with `=`, `+`, `-`, or `@` are prefixed to prevent spreadsheet formula execution. The Activity tab's link carries `user_id` into the Activity Logs section.

## Data health

Data health is available to users with `can_run_maintenance`. Its Check button calls `GET /api/admin/control-center/migrate/status` only when requested. Run backfill requires confirmation and calls `POST /api/admin/control-center/migrate/all`. The legacy-flag counts do not prove that activity logs are missing: normal application writers already record activity, so the backfill is normally unnecessary. The backfill checks for a matching resource creation record in the user's activity-log partition and uses stable per-resource IDs to avoid duplicate writes on repeated or concurrent runs.

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

`functions_control_center_groups.py` builds an inventory with four batched Cosmos queries: projected groups, document metadata counts, all-time token totals, and latest activity timestamps. Activity includes the top-level `group_id`, nested `group.group_id`, and `workspace_context.group_id` writer shapes. Filtering, sorting and paging occur on the server after aggregation; neither the browser nor per-row enrichment performs filtering or counting. This deliberately avoids N+1 queries and Cosmos ordering on undefined/computed fields. Tied sort values use stable ID ordering and missing activity sorts last in either direction. Failed aggregates fail the request rather than silently reporting zero.

The response includes `groups`, `pagination`, and `metrics_freshness` with the snapshot's `calculated_at`, source and TTL. List/CSV totals can lag external writes by up to 90 seconds; **Refresh groups** bypasses the cache. Memory and rebuild cost scale with the group inventory and activity aggregates; this is not continuation-token pagination. Legacy storage-size estimates retain their own older refresh timestamp and are not represented as current counts.

`POST /api/v2/control-center/groups/bulk-status` accepts either `group_ids` or a `filter` object, plus `status` and `reason`. Filter selection accepts the same filter fields, supports `exclude_ids`, and resolves against a fresh server inventory. The full population is capped at 500 before any writes occur. Locked/inactive status requires a nonblank reason (maximum 2,000 characters). `PUT /api/v2/control-center/groups/<id>/status` has the same reason rule. Both call the classic single-status writer, preserving etag conflict handling, status history, activity logging and App Insights audit events. Partial results report `success_count`, `failed_count`, and individual `failed_groups`; unchanged groups succeed without duplicate audit records. The classic status route keeps its existing optional-reason behavior.

`GET /api/v2/control-center/groups/export.csv` exports the entire filtered/sorted inventory, not just the visible page, with spreadsheet-formula-safe cells.

### Drawer and existing actions

`GET /api/v2/control-center/groups/<id>` reads current ownership, members, roles and status history, then returns the overview, retention policy, document summary, token total and the 20 most recent projected activity records. It does not expose model endpoints, credentials, logos, or the raw group document. The activity view shows the returned record as JSON and exports that recent subset as CSV. **View in Activity Logs** carries `workspace_type=group`, `workspace_id`, and `group_id` to the Activity Logs section; that section remains a placeholder until Phase 6.

The drawer has Overview, Members, Ownership, Status, Retention, Activity and Documents tabs. Owner and member links open the Users drawer. `EntityDetailSections.tsx` provides reusable keyboard-operable detail tabs, timeline/JSON presentation and date formatting for later workspace management. `DetailDrawer` reuses the application's modal focus trap, focus restoration and innermost-dialog Escape handling.

Member addition reuses `/api/userSearch` and the existing admin `/groups/<id>/add-member` endpoint. The shared directory-search and CSV-import dialogs retain validation, a 1,000-row import limit, per-row outcomes and retry support. CSV columns are `userId,displayName,email,role`; the admin add flow trusts the supplied member identity fields, so verify CSV data before importing. Supported roles are Admin, DocumentManager and User, mapped to the existing endpoint's `admin`, `document_manager`, and `user` tokens.

Removing members and changing roles reuse the existing `/api/groups/<id>/members/<member_id>` DELETE/PATCH routes. Those operations still require current group Owner/Admin membership; a Control Center role alone does not confer it. The owner cannot be removed or assigned a member role. Retention uses the existing `/api/retention-policy/group/<id>` POST route, requires group Owner/Admin membership and enabled group retention, and accepts `default`, `none`, or organization-bounded whole-number days. Nonmember administrators can inspect these settings and request ownership rather than bypassing the existing membership rules.

Delete group, delete all documents, take ownership and transfer ownership reuse the existing admin approval APIs. Each requires a reason and returns an approval ID, not a performed deletion or ownership change. Transfer recipients must already be members; the UI excludes the current owner. The shared submitted notice links to `/v2/approvals/all/<approval_id>?group_id=<group_id>` using a basename-aware router link, matching the V2 Approvals contract (PR #1687), instead of adding an approvals queue to Control Center. User requests use the same detail destination without a group filter.

### Validation

`functional_tests/test_v2_control_center_groups.py` exercises filters/sorts/paging, cache reuse/expiry, detail projection, roles, bulk cap/exclusions/reasons, real status-writer audit parity, denied access, formula-safe export, and approval creation without direct mutation. `ui_tests/test_v2_control_center_groups.py` covers desktop/mobile drawers, URL filters, cross-page bulk selection, partial failures, status history, escaped text/raw JSON, member search/CSV/roles/removal, retention, ownership approvals and permission-limited controls. Route policy tests include all five new routes; prior Control Center layers and `test_v2_api_security.py` are included in regression validation.

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

Open **Account → Control Center**, then select a section in its internal rail. A bookmarked section URL opens that section directly. On the Dashboard, select a date range and optional token filters; charts include accessible data tables, and chart selections link to the corresponding filtered activity view. Export downloads the trend data as CSV. “Chat with these trends” creates a conversation containing the selected trend data. The Data health page is intended for explicit diagnosis or a known recovery scenario; check first, and run the backfill only when the result and operational context justify it.

## Testing and limitations

Functional checks cover dashboard status normalization, period deltas, cache expiry and refresh, dashboard-reader access, capability parity, bootstrap exposure, manual-only migration checks, and route wiring. Playwright coverage verifies the Data health interaction and capability visibility. Top activity and token rankings are limited to entities present in the recorded `user_id` and workspace-context fields; unlogged historical status snapshots and model/provider details are not inferred.

## Version tracking

The application version is defined by `VERSION` in `application/single_app/config.py`. The foundation was added in **0.261.278**, the dashboard in **0.261.279**, user management in **0.261.280**, group management in **0.261.282**, and public workspace management in **0.261.283**.
