# Group Model Endpoint Membership Guard Fix

Fixed/Implemented in version: **0.239.188**

## Header Information

### Issue Description

The group model endpoint read route returned sanitized endpoint metadata based only on the caller's stored `activeGroupOid`.

If that stored group ID became stale or was tampered with, the route could read group endpoint metadata without proving the caller still belonged to that group.

### Root Cause Analysis

`require_active_group()` only returns the stored active group ID from user settings.

Unlike the adjacent write, fetch, test, and Foundry routes, the GET `/api/group/model-endpoints` path did not call `assert_group_role()` to verify current membership before reading group-scoped model endpoint metadata.

### Version Implemented

`0.239.188`

## Technical Details

### Files Modified

- `application/single_app/route_backend_models.py`
- `application/single_app/config.py`
- `functional_tests/test_group_model_endpoint_membership_guard.py`

### Code Changes Summary

- Added `assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin", "DocumentManager", "User"))` to the group model endpoint GET route.
- Added `LookupError` and `PermissionError` handling so the read route returns consistent `404` and `403` responses.
- Bumped the application version to `0.239.188`.

### Testing Approach

- Added a functional regression test that verifies the group endpoint read route includes the current-membership guard and the corresponding `404` and `403` error handling.

### Impact Analysis

- Prevents users from reading group endpoint metadata solely from a stored active group reference.
- Aligns the read route with the stricter authorization pattern already used by adjacent group model endpoint routes.

## Validation

### Before/After Comparison

Before: the route trusted `activeGroupOid` and returned sanitized group endpoint metadata without verifying the caller still had access to the group.

After: the route verifies the caller still holds one of the allowed group roles before returning any group endpoint metadata.

### Test Results

- Functional regression test added for the group model endpoint membership guard.
- Manual validation performed with a focused route authorization review.