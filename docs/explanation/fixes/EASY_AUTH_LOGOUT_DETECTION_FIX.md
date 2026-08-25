# Easy Auth Logout Detection Fix

Fixed/Implemented in version: **0.260.019**

## Issue Description

User-initiated logout and idle-timeout logout could redirect to
`/.auth/logout?post_logout_redirect_uri=%2Flogin` and return a 404 on Azure App Service
deployments that were not actually serving App Service Easy Auth. The problem was first
reported on a development custom domain, but it was never limited to development
environments; any deployment matching the same conditions was affected, including
production.

## Root Cause Analysis

`_use_app_service_easy_auth_logout()` in
`application/single_app/route_frontend_authentication.py` decided that Easy Auth was active
when either the `X-MS-CLIENT-PRINCIPAL` request headers were present **or** the
`WEBSITE_AUTH_AAD_ALLOWED_TENANTS` environment variable was set:

```python
return any(easy_auth_headers) or bool(os.getenv('WEBSITE_AUTH_AAD_ALLOWED_TENANTS'))
```

That environment variable is not evidence that Easy Auth is running. SimpleChat's own
advanced configuration guidance in
`application/single_app/example_advance_edit_environment_variables.json` instructs
operators to set it by hand, so any deployment that followed those instructions without
enabling Easy Auth was misdetected. Logout then redirected to a platform endpoint that the
App Service was not serving, producing the 404.

A secondary case exists where Easy Auth genuinely is enabled but `/.auth/*` is not routed
through to the App Service origin, for example behind a custom domain, gateway or front
door with restrictive path routing. Request-based detection cannot distinguish that case,
so it needs an explicit opt-out.

## Technical Details

- Modified `application/single_app/route_frontend_authentication.py` so Easy Auth detection
  relies only on the `X-MS-CLIENT-PRINCIPAL`, `X-MS-CLIENT-PRINCIPAL-ID` and
  `X-MS-CLIENT-PRINCIPAL-NAME` headers that App Service injects into requests it actually
  intercepts. The `WEBSITE_AUTH_AAD_ALLOWED_TENANTS` fallback was removed.
- Added `debug_print` output on both non-Easy-Auth paths so the logout routing decision and
  its reason are visible with `FLASK_DEBUG=1`.
- Added the `DISABLE_APP_SERVICE_EASY_AUTH_LOGOUT` environment flag in
  `application/single_app/config.py` for deployments where Easy Auth is active but
  `/.auth/logout` is unreachable on the public host.
- Documented the flag in `application/single_app/example.env` and added a
  "Logout Behavior Across Environments" section to
  `docs/explanation/running_simplechat_locally.md` covering the behavior per environment
  and the troubleshooting steps for a logout 404.
- Updated `application/single_app/config.py` to version `0.260.019`.
- Reworked regression coverage in `functional_tests/test_app_service_easy_auth_logout.py`.

### Behavior by environment

| Environment | Easy Auth headers | Logout path |
| --- | --- | --- |
| Local machine (`python app.py`) | No | Local logout |
| App Service with Easy Auth enabled | Yes | Easy Auth logout via `/.auth/logout` |
| App Service without Easy Auth enabled | No | Local logout |
| Easy Auth enabled, `/.auth/*` not routed | Yes | Local logout after setting the opt-out flag |

Local development was never affected by the original defect, because `WEBSITE_HOSTNAME` is
not set outside App Service and the function returned early.

## Validation

- `functional_tests/test_app_service_easy_auth_logout.py` — 5/5 passing, covering Easy Auth
  local logout, Easy Auth full logout, the reported no-headers case, preservation of Easy
  Auth logout on a non-production host, and the opt-out flag.
- `functional_tests/test_idle_logout_timeout.py` — 4/4 passing. The idle-timeout path routes
  through `local_logout`, so it inherits the corrected behavior.
- Confirmed deployments genuinely behind Easy Auth still redirect through `/.auth/logout`,
  so the upstream platform session continues to be cleared.
- Confirmed deployments with Azure hosting variables but no Easy Auth headers now perform a
  local logout instead of redirecting to a missing platform endpoint.

## Notes

The previous iteration of this fix skipped Easy Auth logout whenever the `is_development`
environment flag was set. That approach was replaced because it left the underlying
detection defect in place for production, it reused a flag documented for Latest Features
navigation to control session termination, and it disabled platform logout even in
development environments where Easy Auth was genuinely active and working.
