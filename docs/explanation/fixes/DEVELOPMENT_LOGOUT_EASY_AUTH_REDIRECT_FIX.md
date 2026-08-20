# Development Logout Easy Auth Redirect Fix

Fixed/Implemented in version: **0.250.225**

## Issue Description

In the development environment, user-initiated logout and idle-timeout logout could redirect to `/.auth/logout?post_logout_redirect_uri=%2Flogin`. That platform Easy Auth URL returned a 404 when the development deployment was not actually serving App Service Easy Auth logout endpoints.

## Root Cause Analysis

The logout route detected Azure hosting variables and Easy Auth-related signals, then routed local logout through `/.auth/logout`. Development deployments can still expose those hosting signals even when the Easy Auth endpoint is unavailable for the current custom-domain path.

## Technical Details

- Modified `application/single_app/route_frontend_authentication.py` so Easy Auth logout routing is skipped when `IS_DEVELOPMENT` is enabled.
- Preserved the existing Easy Auth logout path for non-development Azure App Service deployments with Easy Auth signals.
- Updated `application/single_app/config.py` to version `0.250.225`.
- Added regression coverage in `functional_tests/test_app_service_easy_auth_logout.py` for the development-mode fallback.

## Validation

- Ran `functional_tests/test_app_service_easy_auth_logout.py`.
- Confirmed production-style Easy Auth local and full logout still redirect through `/.auth/logout`.
- Confirmed development-mode local logout avoids `/.auth/logout` and redirects to the local app index after clearing the Flask session.