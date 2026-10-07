# V2 Control Center

The V2 Control Center is a permission-aware administration pane for managing SimpleChat. The foundation release provides the shared navigation and capability contract, placeholders for management areas that will arrive in later phases, and a manual activity-log data-health tool.

**Dashboard implemented in version:** 0.261.279
**Foundation implemented in version:** 0.261.278
**Users implemented in version:** 0.261.280
**Groups implemented in version:** 0.261.281

**Dependencies:** React 18, TypeScript, Vite, Flask session authentication, and the existing Control Center APIs.

## Architecture

The Control Center is a distinct React route (`/control-center` and `/control-center/<section>`), reached from the account menu when the signed-in user has at least one Control Center capability. It is not a primary workspace-navigation item. The internal section rail has a separate per-user collapsed-state preference.

`get_control_center_capabilities()` in `functions_authentication.py` is the shared permission decision for both `control_center_required()` and the `/api/v2/bootstrap` response. When the ControlCenterAdmin role requirement is enabled, that role grants all capabilities; otherwise the regular Admin role grants them. The optional ControlCenterDashboardReader role grants dashboard viewing only when its setting is enabled. The bootstrap payload exposes `can_view_dashboard`, `can_manage_users`, `can_manage_groups`, `can_manage_workspaces`, `can_view_activity_logs`, and `can_run_maintenance`.

## Dashboard

Public Workspaces remains a permission-gated placeholder linking to the classic Control Center at `/admin/control-center`. Users and Groups management are available with `can_manage_users` and `can_manage_groups`, respectively.

The Dashboard is available to users with `can_view_dashboard`, including users assigned the configured ControlCenterDashboardReader role. `GET /api/v2/control-center/dashboard/summary` returns counts and period comparisons; `GET /api/v2/control-center/dashboard/insights` returns grouped chart data. Both use a 90-second in-process cache keyed by the date range and token filters. Pass `force_refresh=1` to bypass it.

The date presets are 7, 30, and 90 UTC calendar days. Custom ranges use `start_date` and `end_date` in `YYYY-MM-DD` format and are limited to 366 days. The trend charts reuse the existing activity-trends and token-filter APIs, CSV export, and “Chat with these trends” endpoint. Chart data is grouped from the fields written by `functions_activity_logging.py`: `user_login.timestamp`, creation activity types and `workspace_type`, and `token_usage.usage.model`, `usage.total_tokens`, `token_type`, `user_id`, and `workspace_context` IDs. The login heatmap uses UTC and Monday=0.

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

Implemented in version: **0.261.281**, tracked in `application/single_app/config.py`.

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

Delete group, delete all documents, take ownership and transfer ownership reuse the existing admin approval APIs. Each requires a reason and returns an approval ID, not a performed deletion or ownership change. Transfer recipients must already be members; the UI excludes the current owner. The submitted notice links to the shared approvals destination instead of adding an approvals queue to Control Center.

### Validation

`functional_tests/test_v2_control_center_groups.py` exercises filters/sorts/paging, cache reuse/expiry, detail projection, roles, bulk cap/exclusions/reasons, real status-writer audit parity, denied access, formula-safe export, and approval creation without direct mutation. `ui_tests/test_v2_control_center_groups.py` covers desktop/mobile drawers, URL filters, cross-page bulk selection, partial failures, status history, escaped text/raw JSON, member search/CSV/roles/removal, retention, ownership approvals and permission-limited controls. Route policy tests include all five new routes; prior Control Center layers and `test_v2_api_security.py` are included in regression validation.

## Usage

Open **Account → Control Center**, then select a section in its internal rail. A bookmarked section URL opens that section directly. On the Dashboard, select a date range and optional token filters; charts include accessible data tables, and chart selections link to the corresponding filtered activity view. Export downloads the trend data as CSV. “Chat with these trends” creates a conversation containing the selected trend data. The Data health page is intended for explicit diagnosis or a known recovery scenario; check first, and run the backfill only when the result and operational context justify it.

## Testing and limitations

Functional checks cover dashboard status normalization, period deltas, cache expiry and refresh, dashboard-reader access, capability parity, bootstrap exposure, manual-only migration checks, and route wiring. Playwright coverage verifies the Data health interaction and capability visibility. Top activity and token rankings are limited to entities present in the recorded `user_id` and workspace-context fields; unlogged historical status snapshots and model/provider details are not inferred.

## Version tracking

The application version is defined by `VERSION` in `application/single_app/config.py`. The foundation was added in **0.261.278**, the dashboard in **0.261.279**, user management in **0.261.280**, and group management in **0.261.281**.
