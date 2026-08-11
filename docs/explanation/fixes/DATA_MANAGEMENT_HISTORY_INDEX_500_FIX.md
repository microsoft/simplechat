# Data Management History Index 500 Fix (v0.250.157)

## Issue Description

The Data Management Backup Inventory and Job History panels could fail to load with HTTP 500 responses from:

- `/api/admin/data-management/backups`
- `/api/admin/data-management/jobs`

The browser then showed a non-JSON response message in the table because Flask returned an HTML error page instead of the Data Management API contract.

## Root Cause

Data Management history pagination orders durable job records by `created_at` and `id`. Existing `data_management_jobs` Cosmos DB containers can be missing the composite index required for that ordered cross-partition query, especially if the container was created before the history pagination index was introduced. The route only handled validation errors, so Cosmos provider failures could escape as generic HTML 500 responses.

## Fixed in version: **0.250.157**

`application/single_app/config.py` was updated from `0.250.156` to `0.250.157`.

## Technical Details

### Files Modified

- `application/single_app/config.py`
- `application/single_app/functions_data_management.py`
- `application/single_app/route_backend_data_management.py`
- `functional_tests/test_data_management_history_pagination.py`

### Code Changes

- Added the required `/created_at` descending + `/id` descending composite index to new app-created `data_management_jobs` containers.
- Added a Data Management history unavailable error that converts Cosmos provider/index failures into safe API responses.
- Added JSON route handling for Backup Inventory and Job History history-store failures.
- Added maintenance guidance when the existing container needs the Cosmos indexing policy maintenance step.

## Validation

Targeted regression coverage verifies:

- Missing history composite-index provider failures become admin-safe maintenance guidance.
- Backup Inventory and Job History endpoints return JSON instead of HTML 500 responses.
- Provider error text is not exposed to the browser.
- Deployers, app-created container policy, and expected Data Management history composite indexes stay aligned.
