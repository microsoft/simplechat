# Approvals Route Authorization Helper Fix

Fixed/Implemented in version: **0.241.027**

## Issue Description

The approvals page could return HTTP 500 with `NameError: name '_can_user_approve' is not defined` when loading approval requests. This affected users who should have been able to see targeted document deletion approvals, including the requesting admin and the user whose files were queued for deletion.

## Root Cause Analysis

`route_backend_control_center.py` imported approval helpers with `from functions_approvals import *`, but Python star imports intentionally skip names that start with an underscore unless a module defines `__all__`. The route already used `_can_user_approve` to calculate each approval row's `can_approve` flag, so the authorization helper was unavailable at runtime even though the helper existed in `functions_approvals.py`.

## Technical Details

### Files Modified

- `application/single_app/route_backend_control_center.py`
- `application/single_app/config.py`
- `functional_tests/test_approvals_route_helper_import.py`
- `docs/explanation/fixes/v0.241.027/APPROVALS_ROUTE_AUTHORIZATION_HELPER_FIX.md`

### Code Changes Summary

- Explicitly imported `_can_user_approve` in the Control Center backend route module.
- Reused `_can_user_approve` for the admin approval list `can_approve` calculation so list responses match the same authorization helper used by detail and action endpoints.
- Updated `application/single_app/config.py` to version `0.241.027` for this fix.

### Testing Approach

- Added `functional_tests/test_approvals_route_helper_import.py` to verify the route explicitly imports the underscore authorization helper.
- Validated targeted document deletion approval boundaries: the requesting admin and target user can view and approve, while an unrelated non-admin user cannot view or approve.
- Verified the fix document references the functional test and current config version.

## Validation

### Before

- `/api/approvals` could fail during row decoration with a `NameError` even after `get_pending_approvals()` had already applied eligibility filtering.
- The admin approval list used a separate requester-based `can_approve` rule that could diverge from the route authorization helper.

### After

- Approval list and detail routes can calculate `can_approve` without crashing.
- Approval visibility and approval rights continue to use the existing centralized authorization helper.
- Unrelated users remain blocked from targeted approval records.