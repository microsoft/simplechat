# Plugin Validation Route Auth Fix

Fixed/Implemented in version: **0.241.206**

## Issue Description

Several plugin validation endpoints did not consistently enforce the runtime authentication and role decorators used by comparable SimpleChat API routes. The admin-namespaced validation helper routes could execute without `@login_required` and `@admin_required`, while the user-facing validation route only required login and did not require the standard user role boundary.

## Root Cause Analysis

`@swagger_route(security=get_auth_security())` documents the OpenAPI security requirement but does not enforce request authentication at runtime. Runtime enforcement in SimpleChat is provided by route decorators from `functions_authentication.py`, such as `@login_required`, `@user_required`, and `@admin_required`.

The affected routes in `application/single_app/plugin_validation_endpoint.py` had incomplete decorator stacks compared with nearby plugin routes in `application/single_app/route_backend_plugins.py`.

## Technical Details

Files modified:

- `application/single_app/plugin_validation_endpoint.py`
- `application/single_app/config.py`
- `functional_tests/test_plugin_validation_route_auth.py`
- `.github/prompts/route-authentication-audit.prompt.md`
- `.github/workflows/broken-access-control-check.yml`
- `functional_tests/test_broken_access_control_guardrails_checker.py`

Code changes summary:

- Added `@user_required` to the user-facing `/api/plugins/validate` route.
- Added `@login_required` and `@admin_required` to the admin plugin instantiation, health-check, and repair routes.
- Added a route-authentication audit prompt for broader Flask route decorator reviews.
- Wired the route-authentication audit prompt into the Broken Access Control guardrail workflow path list.
- Added a focused functional regression test for the plugin validation route auth contract.
- Updated `config.py` version to `0.241.206`.

## Testing Approach

Validation includes a static functional test that parses `plugin_validation_endpoint.py` and asserts the exact expected runtime auth decorators for each plugin validation route. This catches future accidental removal of `@login_required`, `@user_required`, or `@admin_required` without needing to execute state-changing plugin repair logic.

## Impact Analysis

After the fix:

- Anonymous callers are blocked before reaching plugin validation admin logic.
- Non-admin authenticated users are blocked from admin plugin validation operations.
- User-facing plugin manifest validation follows the same user-role boundary as similar plugin helper APIs.
- A reusable route-auth audit prompt is available for broader review of existing Flask route decorator coverage.

## Validation

Before the fix, a static decorator review showed the three admin plugin validation routes had no runtime auth decorators and the user-facing validation route was login-only.

After the fix, the expected contract is:

- `/api/plugins/validate`: `@login_required`, `@user_required`
- `/api/admin/plugins/validate`: `@login_required`, `@admin_required`
- `/api/admin/plugins/test-instantiation`: `@login_required`, `@admin_required`
- `/api/admin/plugins/health-check/<plugin_name>`: `@login_required`, `@admin_required`
- `/api/admin/plugins/repair/<plugin_name>`: `@login_required`, `@admin_required`

Related functional test: `functional_tests/test_plugin_validation_route_auth.py`

Related config version update: `application/single_app/config.py` version `0.241.206`