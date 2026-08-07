# getAToken Missing Code Redirect Fix

Fixed/Implemented in version: **0.250.129**

## Issue Description

Unauthenticated users who browsed directly to protected SimpleChat pages could be redirected to `/getAToken` without first completing Microsoft Entra sign-in. Because the OAuth callback did not receive an authorization `code`, the page returned an "Authorization code not found" error and created avoidable support tickets.

## Root Cause Analysis

The `/getAToken` frontend OAuth callback treated every request without a `code` query parameter as a failed callback. Direct browser visits to the callback path are not valid token exchanges, but they are recoverable user navigation events and should route users back to the normal sign-in entry point.

## Technical Details

Files modified:

- `application/single_app/route_frontend_authentication.py`
- `application/single_app/config.py`
- `functional_tests/test_getatoken_missing_code_redirect.py`

Code changes summary:

- Updated the `/getAToken` callback missing-code branch to log the recoverable condition and redirect to `public_app.index`.
- Preserved the valid OAuth authorization-code exchange flow.
- Left `/getATokenApi` unchanged so API token callback callers still receive explicit request errors.
- Updated `config.py` version to `0.250.129` after merging the latest `Development` changes.

## Validation

Testing approach:

- Added a focused functional regression test that verifies the `/getAToken` missing-code branch redirects to the home sign-in route instead of returning the previous error text.

Impact analysis:

- Users see the normal SimpleChat sign-in entry point rather than a technical OAuth callback error.
- Valid Microsoft Entra callback requests with authorization codes continue through the existing token redemption path.
