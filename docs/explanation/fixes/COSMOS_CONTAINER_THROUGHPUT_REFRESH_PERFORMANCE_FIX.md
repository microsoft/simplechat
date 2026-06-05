# Cosmos Container Throughput Refresh Performance Fix

Fixed/Implemented in version: **0.241.155**

## Issue Description

Container-targeted Cosmos throughput scaling requires per-container RU utilization. Admins could see per-container `Normalized RU Consumption` in the Azure portal, but SimpleChat still needed to request the same Azure Monitor dimensions and avoid using aggregate account utilization for individual container scale decisions. Refreshes were also slow because the app read each container throughput setting serially, with each ARM request taking hundreds or thousands of milliseconds.

## Root Cause Analysis

The Azure Monitor query needed to match the portal-style split by configured `DatabaseName` and `CollectionName`. Separately, ARM exposes current dedicated throughput through each container's `throughputSettings/default` child resource, so the app still has to read per-container throughput resources. The previous implementation did those reads one after another and acquired ARM credentials for each read.

## Technical Details

Files modified:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `functional_tests/test_cosmos_throughput_container_metrics.py`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `docs/explanation/release_notes.md`

Code changes summary:

- Added a database-specific Azure Monitor filter builder: `DatabaseName eq '<database>' and CollectionName eq '*'`.
- Kept aggregate metrics only as a display fallback for the summary card when container-dimensional metrics lag or are unavailable.
- Added an explicit `container_metrics_unavailable` no-scale decision when scalable containers lack per-container utilization.
- Reused a single ARM token/context for container throughput reads during a refresh.
- Parallelized container throughput reads with a bounded worker pool while preserving container row order and per-container error handling.
- Clarified Admin Settings messaging that individual container autoscale waits for per-container utilization.
- Application version updated to `0.241.155` in `application/single_app/config.py`.

## Validation

Test results:

- Python syntax validation for Cosmos throughput helpers and functional tests.
- JavaScript syntax validation for `admin_settings.js`.
- Functional regression tests for Azure Monitor container dimensions, aggregate fallback, shared ARM context throughput reads, and no-scale behavior when per-container metrics are unavailable.
- Focused UI regression test for the aggregate-only warning copy.

Before/after comparison:

- Before: container refreshes could show only aggregate utilization, and throughput reads ran serially across containers.
- After: utilization is requested as per-container Azure Monitor rows, aggregate values are not used for individual container autoscale, and ARM throughput reads run concurrently with a shared token.

Related config.py version update

- Application version updated to `0.241.155` in `application/single_app/config.py`.