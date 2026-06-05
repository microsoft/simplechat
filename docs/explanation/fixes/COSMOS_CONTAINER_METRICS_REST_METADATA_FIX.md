# Cosmos Container Metrics REST Metadata Fix

Fixed/Implemented in version: **0.241.156**

## Issue Description

The Admin Settings Scale tab still showed `Not available` for every container's RU Utilization and Request Units even though Azure Metrics Explorer showed per-container `Normalized RU Consumption` and total request-unit metrics for the same Cosmos account.

## Root Cause Analysis

The Azure Monitor Query SDK returned the correct number of container-split time series, but the SDK model exposed blank metadata entries for those series. The app saw the metric values but could not map each series to a Cosmos container name. The raw Azure Monitor Metrics REST API returned the same series with usable `collectionname` and `databasename` metadata, matching the portal view.

## Technical Details

Files modified:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/config.py`
- `functional_tests/test_cosmos_throughput_container_metrics.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `docs/explanation/release_notes.md`

Code changes summary:

- Removed the Cosmos throughput metrics dependency on the Azure Monitor Query SDK response model.
- Added a raw Azure Monitor Metrics REST request for `NormalizedRUConsumption,TotalRequestUnits` with `Maximum,Total` aggregation and the existing database/container dimension filter.
- Extended metric metadata parsing to support REST `metadatavalues` dictionaries with lowercase `collectionname` and `databasename` keys.
- Reused one metrics ARM token/context across the container-dimensional query and aggregate fallback query.
- Application version updated to `0.241.156` in `application/single_app/config.py`.

## Validation

Test results:

- Live read-only metrics probe confirmed named container rows are returned for the configured Cosmos account.
- Functional regression test now uses REST-shaped metric payloads instead of SDK-shaped fake objects.
- Python and JavaScript syntax validation completed for touched files.
- Focused Cosmos throughput regression suite completed successfully.

Before/after comparison:

- Before: Azure returned container-split metric series, but the SDK metadata loss left every container row unmapped and displayed as unavailable.
- After: SimpleChat parses the raw Metrics REST metadata and fills row-level RU Utilization and Request Units for individual containers.

Related config.py version update

- Application version updated to `0.241.156` in `application/single_app/config.py`.