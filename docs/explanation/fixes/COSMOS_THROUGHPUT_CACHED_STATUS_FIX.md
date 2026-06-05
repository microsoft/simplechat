# Cosmos Throughput Cached Status Fix

Fixed/Implemented in version: **0.241.152**

## Issue Description

After restarting the server and returning to Admin Settings, the Cosmos DB Throughput card showed no containers until an admin clicked Refresh. This made container-targeted scaling look unavailable even though background automation could still evaluate and scale throughput.

## Root Cause Analysis

Cosmos throughput refreshes and background autoscale checks stored only summary runtime fields such as last checked time, last observed utilization, and last mode. The detailed capacity scope, throughput summary, metrics, and container rows were not persisted for the initial Admin Settings render.

## Technical Details

Files modified:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/route_backend_settings.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `functional_tests/test_cosmos_throughput_cached_status.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `docs/explanation/release_notes.md`

Code changes summary:

- Added a compact cached Cosmos throughput status containing admin-display-safe resource identifiers, capacity scope, throughput summary, metrics, container rows, errors, and timestamps.
- Saved the cached status after manual Refresh and background autoscale checks.
- Rendered the cached status immediately on Admin Settings page load before any live Refresh request.
- Preserved the last good cached view when an autoscale check fails before producing a usable status.
- Added Admin Settings copy explaining that automation checks throughput about every 5 minutes while enabled.
- Added a versioned `admin_settings.js` script URL so browser caching does not keep old Cosmos UI logic after version updates.
- Application version updated to `0.241.152`.

## Validation

Test results:

- JavaScript syntax validation for `admin_settings.js`.
- Python syntax validation for `functions_cosmos_throughput.py`.
- Functional regression test for cached Cosmos throughput status persistence.
- Focused UI regression test for cached status first render and Cosmos throughput controls.

Before/after comparison:

- Before: server restart showed an empty container table until an admin clicked Refresh.
- After: Admin Settings renders the last saved database or container-targeted Cosmos view immediately, and Refresh remains available for an on-demand live check.

Related config.py version update

- Application version updated to `0.241.152` in `application/single_app/config.py`.