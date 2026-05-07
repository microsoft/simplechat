# Control Center Activity Logs Hardening Fix

Fixed/Implemented in version: **0.241.015**

## Issue Description

The Control Center Activity Logs tab had two related problems.

When the page width became narrower, the Activity Logs table relied on the generic table layout with no column contract, so the Details column could expand unpredictably and squeeze the other columns into unreadable widths.

Separately, customers could hit 500 errors while paging activity logs or exporting them. The browser logs only showed failures from `/api/admin/control-center/activity-logs`, including an export path that requested `per_page=10000`, but they did not prove that the logs were empty or corrupted.

## Root Cause Analysis

The Activity Logs table in `application/single_app/templates/control_center.html` only used Bootstrap `table-responsive` with generic `.user-table` styling. It had no fixed table layout, no column width ratios, and no truncation wrappers for long user or details content.

The backend route in `application/single_app/route_backend_control_center.py` returned raw Cosmos activity log documents directly through the interactive paging endpoint. It also reused that endpoint for export by fetching a `per_page=10000` JSON payload from `application/single_app/static/js/control-center.js`. That left three failure classes open:

- Oversized interactive requests for export.
- Generic 500 handling with very little diagnostic detail.
- Page-specific failures if a historical activity log document shape was valid in Cosmos but not safe to serialize or consume as-is in the browser.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/route_backend_control_center.py`, `application/single_app/templates/control_center.html`, `application/single_app/static/js/control-center.js`, `functional_tests/test_control_center_activity_logs_hardening.py`, `ui_tests/test_control_center_activity_logs_layout.py`

Code changes summary:

- Added Activity Logs-specific pagination validation, query construction, response normalization, and structured diagnostics in `route_backend_control_center.py`.
- Moved activity log export onto a dedicated `/api/admin/control-center/activity-logs/export` route so export no longer depends on the interactive paged JSON API or a `per_page=10000` fetch.
- Normalized activity log records before returning them to the browser so heterogeneous historical log shapes can degrade safely instead of failing the entire page response.
- Added Activity Logs-specific table layout rules in `control_center.html`, including a fixed table layout, explicit column widths, minimum table width, truncation wrappers, and hover styling.
- Updated `control-center.js` to remove leftover debug console logging, show server-provided error messages, clear stale pagination UI on failure, and use the dedicated export endpoint.

Impact analysis:

- The Activity Logs table stays readable on smaller page widths while preserving horizontal scroll as a fallback.
- Export requests no longer overload the interactive API path with a 10000-row JSON request.
- Paging failures now have server-side diagnostics that can distinguish validation problems from backend exceptions.
- A single unexpected activity log document shape is less likely to break page 2 while page 1 still works.

## Validation

Test coverage: `functional_tests/test_control_center_activity_logs_hardening.py`, `ui_tests/test_control_center_activity_logs_layout.py`

Test results:

- Validates that the backend exposes activity log pagination validation, shared query helpers, normalized response handling, and a dedicated export route.
- Validates that the template includes Activity Logs-specific fixed-layout and truncation hooks.
- Validates that the client uses the dedicated export route, removes the old `per_page=10000` export pattern, and clears stale pagination UI when loading fails.
- Validates in the browser that the Activity Logs table uses the fixed layout, preserves overflow handling on a narrow viewport, keeps the raw-log modal path available, and issues export through the dedicated export endpoint.

Before/after comparison:

- Before: Narrower layouts could distort the Activity Logs columns, export reused the paged JSON endpoint with `per_page=10000`, and backend failures surfaced as generic 500s with limited diagnostic context.
- After: The Activity Logs table has a stable responsive layout contract, export uses a dedicated backend CSV route, and the backend emits structured diagnostics while returning normalized log payloads.

Related config.py version update: `VERSION = "0.241.015"`