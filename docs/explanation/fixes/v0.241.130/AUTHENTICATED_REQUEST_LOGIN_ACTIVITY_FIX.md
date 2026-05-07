# Authenticated Request Login Activity Fix

Fixed/Implemented in version: **0.241.130**

## Overview

This fix closes the gap between explicit OAuth callback logins and real authenticated usage. Previously, activity tracking only recorded `user_login` when the `/getAToken` callback completed. Users who arrived with an already-authenticated session or seamless SSO reuse could browse the app without creating the login-style activity that the Control Center and profile dashboards rely on.

Version implemented:
`config.py` now reports `VERSION = "0.241.130"` for this fix.

## Issue Description

- Login analytics depended on an explicit callback event rather than the broader fact that the user had an authenticated browser session.
- Passive SSO or session reuse could authenticate the user successfully but leave login metrics empty or understated.
- Simply logging every authenticated request would have created noisy over-counting, especially for API-heavy pages.

## Root Cause

- The application treated `user_login` as a one-time OAuth callback event instead of a reusable authenticated-session signal.
- The authenticated request pipeline had no throttled activity writer for browser page access.
- The explicit callback flow had no session marker to prevent a duplicate login record on the immediate redirect to the landing page.

## Technical Changes

### Throttled Authenticated Request Tracking

Changes implemented:

- Added a shared authenticated-request helper in `functions_activity_logging.py` that records a `user_login` activity with `login_method = authenticated_request`.
- Added a session-scoped throttle window so repeated authenticated page loads do not emit a record on every request.
- Captured request metadata such as `request_path`, `request_method`, and `auth_signal` for later diagnostics.

Files involved:

- `application/single_app/functions_activity_logging.py`
- `application/single_app/app.py`

Behavioral outcome:

Authenticated page visits now show up in the existing login analytics even when the user did not intentionally click a login button during that session.

### OAuth Callback Deduplication

Changes implemented:

- Marked the session immediately after the explicit `/getAToken` callback logs `user_login`.
- Reused that session marker to suppress an immediate second `user_login` on the redirect to `/`.

Files involved:

- `application/single_app/route_frontend_authentication.py`

Behavioral outcome:

Explicit callback logins remain single-counted while passive authenticated navigation still becomes visible later in the session.

## Files Modified

- `application/single_app/functions_activity_logging.py`
- `application/single_app/app.py`
- `application/single_app/route_frontend_authentication.py`
- `application/single_app/config.py`
- `functional_tests/test_authenticated_request_login_activity.py`

## Validation

Testing approach:

- Added a focused functional regression test that loads `functions_activity_logging.py` with stubbed dependencies so the new throttle and dedup behavior can be exercised without a live Cosmos dependency.
- Ran targeted compile checks on the edited Python files.

Validation performed for this implementation:

- `python -m py_compile application/single_app/functions_activity_logging.py`
- `python -m py_compile application/single_app/app.py`
- `python -m py_compile application/single_app/route_frontend_authentication.py`
- `python -m py_compile functional_tests/test_authenticated_request_login_activity.py`
- `python functional_tests/test_authenticated_request_login_activity.py`

## Before And After

Before:

- Login metrics depended almost entirely on explicit OAuth callback completions.
- Passive SSO/session-reuse visits could authenticate successfully without contributing to login analytics.
- A naive request-level fix risked over-counting every authenticated browser/API request.

After:

- Authenticated browser page requests can emit a throttled `user_login` record when no recent login activity has been recorded in the current session.
- Explicit OAuth callback logins still record normally and are not immediately double-counted on redirect.
- Existing dashboards that already query `activity_type = 'user_login'` now see a more representative picture of real authenticated use.

## User Experience Impact

- Admins get more representative login activity in the Control Center and profile trends for users who rely on seamless SSO.
- Users do not see any UI change.
- Login metrics should remain substantially less noisy than per-request tracking because the authenticated-request signal is throttled and limited to browser GET requests.