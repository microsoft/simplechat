# Swagger Route Integration Fix

Fixed in version: **0.240.004**

## Issue Description

Three Flask routes were missing the required `@swagger_route(security=get_auth_security())` decorator even though the repository standard requires every route to expose authenticated swagger metadata.

## Root Cause Analysis

The routes were added without the swagger decorator during earlier feature work, so they were reachable at runtime but absent from the authenticated swagger coverage expected by the project.

## Technical Details

Files modified:

- `application/single_app/route_backend_control_center.py`
- `application/single_app/route_backend_speech.py`
- `application/single_app/route_frontend_control_center.py`
- `application/single_app/config.py`
- `functional_tests/test_missing_swagger_routes_fix.py`

Code changes summary:

- Added `@swagger_route(security=get_auth_security())` to `/api/approvals`.
- Added swagger imports and `@swagger_route(security=get_auth_security())` to `/api/speech/transcribe-chat`.
- Added `@swagger_route(security=get_auth_security())` to `/approvals`.
- Bumped the app version to `0.240.004`.
- Added a regression test covering the three previously missing routes.

Testing approach:

- Run `python functional_tests/test_missing_swagger_routes_fix.py`.
- Re-scan the route inventory artifacts to confirm that no routes remain in `artifacts/routes_missing_swagger.txt`.

Impact analysis:

- Restores swagger consistency for the missing routes.
- Keeps decorator order aligned with the repository standard.
- Ensures future regressions are caught by a focused functional test.

## Validation

Before:

- `artifacts/routes_missing_swagger.txt` listed three routes without swagger integration.

After:

- The three routes now include authenticated swagger decorators.
- The regression test validates imports and decorator order for the fixed routes.
- The route inventory can be regenerated with zero missing swagger routes.