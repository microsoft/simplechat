# V2 Control Center

The V2 Control Center is a permission-aware administration pane for managing SimpleChat. The foundation release provides the shared navigation and capability contract, placeholders for management areas that will arrive in later phases, and a manual activity-log data-health tool.

**Implemented in version:** 0.261.278

**Dependencies:** React 18, TypeScript, Vite, Flask session authentication, and the existing Control Center APIs.

## Architecture

The Control Center is a distinct React route (`/control-center` and `/control-center/<section>`), reached from the account menu when the signed-in user has at least one Control Center capability. It is not a primary workspace-navigation item. The internal section rail has a separate per-user collapsed-state preference.

`get_control_center_capabilities()` in `functions_authentication.py` is the shared permission decision for both `control_center_required()` and the `/api/v2/bootstrap` response. When the ControlCenterAdmin role requirement is enabled, that role grants all capabilities; otherwise the regular Admin role grants them. The optional ControlCenterDashboardReader role grants dashboard viewing only when its setting is enabled. The bootstrap payload exposes `can_view_dashboard`, `can_manage_users`, `can_manage_groups`, `can_manage_workspaces`, `can_view_activity_logs`, and `can_run_maintenance`.

## Sections and data health

Dashboard, Users, Groups, Public Workspaces, and Activity Logs are permission-gated placeholders until their V2 implementations are delivered. They link to the classic Control Center at `/admin/control-center`.

Data health is available to users with `can_run_maintenance`. Its Check button calls `GET /api/admin/control-center/migrate/status` only when requested. Run backfill requires confirmation and calls `POST /api/admin/control-center/migrate/all`. The legacy-flag counts do not prove that activity logs are missing: normal application writers already record activity, so the backfill is normally unnecessary. The backfill checks for a matching resource creation record in the user's activity-log partition and uses stable per-resource IDs to avoid duplicate writes on repeated or concurrent runs.

## Usage

Open **Account → Control Center**, then select a section in its internal rail. A bookmarked section URL opens that section directly. The Data health page is intended for explicit diagnosis or a known recovery scenario; check first, and run the backfill only when the result and operational context justify it.

## Testing and limitations

Functional checks cover capability parity, bootstrap exposure, manual-only migration checks, deduplication, and route wiring. Playwright coverage verifies the Data health interaction and capability visibility. This foundation does not implement the dashboard, user/group/workspace administration, or activity-log browser; those sections remain in the classic page until their subsequent phases.

## Version tracking

The application version is defined by `VERSION` in `application/single_app/config.py`. This implementation was added in **0.261.278**.
