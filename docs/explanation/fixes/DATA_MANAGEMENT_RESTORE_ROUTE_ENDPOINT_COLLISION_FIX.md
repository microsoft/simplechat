# Data Management Restore Route Endpoint Collision Fix

Fixed/Implemented in version: **0.250.111**

## Issue Description

Application startup failed while registering the Data Management Blueprint because two restore review routes used the same URL and endpoint function name.

## Root Cause Analysis

An earlier restore review handler remained in `route_backend_data_management.py` after the authorization-aware restore review workflow was added. Flask therefore attempted to register `backend_data_management.review_admin_data_management_restore` twice and raised an `AssertionError`.

## Technical Details

Files modified:

- `application/single_app/route_backend_data_management.py`
- `application/single_app/config.py`
- `functional_tests/test_data_management_security_patterns.py`

Code changes summary:

- Removed the obsolete duplicate restore review route.
- Retained the complete handler that validates settings and restore plans and issues restore review authorization tokens.
- Added a regression assertion requiring unique route endpoint names in the Data Management Blueprint.
- Updated the application version to `0.250.111`.

Impact analysis:

- The Data Management Blueprint can register during application startup.
- The restore review API path and authorization-aware behavior remain unchanged.

## Validation

Test results:

- The endpoint uniqueness regression test passes with 28 unique Data Management routes.
- Data Management route security and route policy tests validate authentication and Blueprint registration contracts.

Before: Flask stopped startup because the restore review endpoint was registered twice.

After: Flask registers one restore review endpoint backed by the guarded restore workflow.

Version reference: `application/single_app/config.py` version `0.250.111`.