# Cosmos Container Metrics Dimension Fix

Fixed/Implemented in version: **0.241.154**

## Issue Description

The Admin Settings Scale tab could show an aggregate Cosmos RU Utilization value, such as 11%, while every dedicated-throughput container row still showed `RU Utilization: Not available` and `Request Units: Not available`.

## Root Cause Analysis

The throughput refresh queried Azure Monitor for `NormalizedRUConsumption` and `TotalRequestUnits` without requesting Cosmos database and container dimensions. Azure Monitor could return a valid account-level metric series for the status card, but the response did not include `CollectionName` container metadata for the table rows.

## Technical Details

Files modified:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `functional_tests/test_cosmos_throughput_container_metrics.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `docs/explanation/release_notes.md`

Code changes summary:

- Added an Azure Monitor metrics query path that requests Cosmos container dimensions with `DatabaseName eq '*' and CollectionName eq '*'`.
- Kept an aggregate metrics fallback so the top-level RU utilization card remains populated when container-dimensional metrics lag or are not returned.
- Added backend logging fields for whether container dimensions were requested and how many container metric rows were returned.
- Added an Admin Settings warning when Azure Monitor returns aggregate utilization but no per-container metric dimensions for the selected window.
- Application version updated to `0.241.154` in `application/single_app/config.py`.

## Validation

Test results:

- Python syntax validation for `functions_cosmos_throughput.py` and the new metric regression test.
- Functional regression test for Cosmos Azure Monitor container metric parsing, dimension filter usage, and aggregate fallback behavior.
- JavaScript syntax validation for `admin_settings.js`.
- Focused UI regression test for the aggregate-only metrics warning.

Before/after comparison:

- Before: the refresh path often populated only the aggregate RU Utilization card, leaving all container rows without metric values.
- After: the refresh path requests per-container Azure Monitor series and clearly explains when Azure returns only aggregate metrics for the current window.

Related config.py version update

- Application version updated to `0.241.154` in `application/single_app/config.py`.