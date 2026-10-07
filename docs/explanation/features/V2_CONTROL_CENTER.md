# V2 Control Center

The V2 Control Center is a permission-aware administration pane for managing SimpleChat. The foundation release provides the shared navigation and capability contract, placeholders for management areas that will arrive in later phases, and a manual activity-log data-health tool.

**Dashboard implemented in version:** 0.261.279
**Foundation implemented in version:** 0.261.278

**Dependencies:** React 18, TypeScript, Vite, Flask session authentication, and the existing Control Center APIs.

## Architecture

The Control Center is a distinct React route (`/control-center` and `/control-center/<section>`), reached from the account menu when the signed-in user has at least one Control Center capability. It is not a primary workspace-navigation item. The internal section rail has a separate per-user collapsed-state preference.

`get_control_center_capabilities()` in `functions_authentication.py` is the shared permission decision for both `control_center_required()` and the `/api/v2/bootstrap` response. When the ControlCenterAdmin role requirement is enabled, that role grants all capabilities; otherwise the regular Admin role grants them. The optional ControlCenterDashboardReader role grants dashboard viewing only when its setting is enabled. The bootstrap payload exposes `can_view_dashboard`, `can_manage_users`, `can_manage_groups`, `can_manage_workspaces`, `can_view_activity_logs`, and `can_run_maintenance`.

## Dashboard

Users, Groups, Public Workspaces, and Activity Logs remain permission-gated placeholders until their V2 implementations are delivered. They link to the classic Control Center at `/admin/control-center`.

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
| Activity Logs | `activity_type`, `date`, `start_date`, `end_date`, `workspace_type`, `token_type`, `model`, `status` |

Section paths are `/control-center/users`, `/control-center/groups`, `/control-center/public-workspaces`, and `/control-center/activity-logs`. IDs and parameter values are URL-encoded. `date` is a UTC calendar date; `start_date` and `end_date` are inclusive UTC dates.

## Data health

Data health is available to users with `can_run_maintenance`. Its Check button calls `GET /api/admin/control-center/migrate/status` only when requested. Run backfill requires confirmation and calls `POST /api/admin/control-center/migrate/all`. The legacy-flag counts do not prove that activity logs are missing: normal application writers already record activity, so the backfill is normally unnecessary. The backfill checks for a matching resource creation record in the user's activity-log partition and uses stable per-resource IDs to avoid duplicate writes on repeated or concurrent runs.

## Usage

Open **Account → Control Center**, then select a section in its internal rail. A bookmarked section URL opens that section directly. On the Dashboard, select a date range and optional token filters; charts include accessible data tables, and chart selections link to the corresponding filtered activity view. Export downloads the trend data as CSV. “Chat with these trends” creates a conversation containing the selected trend data. The Data health page is intended for explicit diagnosis or a known recovery scenario; check first, and run the backfill only when the result and operational context justify it.

## Testing and limitations

Functional checks cover dashboard status normalization, period deltas, cache expiry and refresh, dashboard-reader access, capability parity, bootstrap exposure, manual-only migration checks, and route wiring. Playwright coverage verifies the Data health interaction and capability visibility. Top activity and token rankings are limited to entities present in the recorded `user_id` and workspace-context fields; unlogged historical status snapshots and model/provider details are not inferred.

## Version tracking

The application version is defined by `VERSION` in `application/single_app/config.py`. The foundation was added in **0.261.278** and the dashboard in **0.261.279**.
