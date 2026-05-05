# Plugin Log Recent Invocations Admin Fix

Fixed/Implemented in version: **0.241.014**

## Overview

This follow-up hardening closes the adjacent plugin logging route that still exposed cross-user invocation history behind authentication only.

Version implemented:
`config.py` now reports `VERSION = "0.241.014"` for this fix.

## Issue Description

- `GET /api/plugins/invocations/recent` returned the most recent plugin invocations across all users.
- The route was documented in code as admin-only, but it was protected only by `@login_required`.
- Any authenticated non-admin user could read recent cross-user plugin invocation data if they knew the endpoint existed.

## Root Cause

- Route entry authentication existed.
- The destructive `clear-logs` path was hardened, but the adjacent cross-user read path still relied on an inline comment instead of an enforced admin-role check.

## Technical Changes

### Admin Gate For Recent Invocation Feed

Changes implemented:

- Added `@admin_required` to `get_recent_invocations()` in `application/single_app/route_plugin_logging.py`.
- Preserved the existing `@login_required` behavior so unauthenticated requests still receive `401 Unauthorized`.
- Left the successful admin response shape unchanged.

Security outcome:

Only administrators can access the cross-user recent invocation feed.

### Focused Regression Coverage

Changes implemented:

- Extended `functional_tests/test_plugin_logging_clear_logs_authorization.py` to cover both plugin logging admin-only endpoints.
- Added coverage for unauthenticated `401`, non-admin `403`, and admin `200` behavior on `/api/plugins/invocations/recent`.
- Verified non-admin requests fail before the logger's `get_recent_invocations()` method is called.

Security outcome:

The plugin logging admin surface now has regression coverage for both the shared clear operation and the shared recent-history feed.

## Files Modified

- `application/single_app/route_plugin_logging.py`
- `functional_tests/test_plugin_logging_clear_logs_authorization.py`
- `application/single_app/config.py`

## Validation

Testing approach:

- Recompiled the hardened route and the extended regression test.
- Executed the focused plugin logging admin authorization regression after the route change and again after the version and documentation updates.

Validation performed for this implementation:

- `python -m py_compile application/single_app/route_plugin_logging.py`
- `python -m py_compile functional_tests/test_plugin_logging_clear_logs_authorization.py`
- `python functional_tests/test_plugin_logging_clear_logs_authorization.py`

## Before And After

Before:

- Any authenticated user could read the cross-user recent invocation feed.
- The route's admin-only intent existed only as a comment.

After:

- Unauthenticated requests still return `401 Unauthorized`.
- Non-admin authenticated users now receive `403 Forbidden`.
- Administrators retain access to the recent shared invocation feed.

## User Experience Impact

Normal admin troubleshooting flows remain unchanged. The visible change is the expected secure outcome: non-admin users can no longer access the cross-user recent plugin invocation history.