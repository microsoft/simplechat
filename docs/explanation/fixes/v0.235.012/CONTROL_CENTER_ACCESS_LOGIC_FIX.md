# Control Center Access Control Logic Fix

**Version**: 0.235.011  
**Fixed in**: 0.235.011  
**Category**: Access Control / Authorization

## Issue Description

The Control Center access control logic had a discrepancy where:

1. When `require_member_of_control_center_admin` was **disabled** (the default), users with the `ControlCenterAdmin` role (but NOT the regular `Admin` role) were incorrectly granted access.

2. The intended behavior is that the `ControlCenterAdmin` role should ONLY be checked when that role feature is enabled. When disabled, only the regular `Admin` role should grant access.

## Root Cause

The `control_center_required` decorator in `functions_authentication.py` was checking for `ControlCenterAdmin` role unconditionally, allowing access regardless of whether the role feature was enabled or not.

## Expected Behavior

### When `require_member_of_control_center_admin` is DISABLED (default):
| User Role | Access Level |
|-----------|-------------|
| `Admin` | Full access (Dashboard + Management + Activity Logs) |
| `ControlCenterAdmin` only | **No access** (role feature not enabled) |
| `Admin` + `ControlCenterAdmin` | Full access (via Admin role) |
| `ControlCenterDashboardReader` | Dashboard only (if that setting is enabled) |
| Normal user | No access |

### When `require_member_of_control_center_admin` is ENABLED:
| User Role | Access Level |
|-----------|-------------|
| `Admin` only | **No access** (must have ControlCenterAdmin) |
| `ControlCenterAdmin` | Full access |
| `Admin` + `ControlCenterAdmin` | Full access (via ControlCenterAdmin role) |
| `ControlCenterDashboardReader` | Dashboard only (if that setting is enabled) |
| Normal user | No access |

## Key Insight

The setting `require_member_of_control_center_admin` acts as a **switch** between two access control modes:
- **OFF (default)**: Use `Admin` role for access control
- **ON**: Use `ControlCenterAdmin` role for access control

The `ControlCenterAdmin` role is **only relevant when the setting is enabled**. Otherwise, it's ignored.

## Files Modified

### 1. `functions_authentication.py`
- Updated `control_center_required` decorator to:
  - Check for both `ControlCenterAdmin` and regular `Admin` roles
  - Properly fall back to Admin role when ControlCenterAdmin requirement is disabled
  - Deny access to non-admin users with appropriate error messages
  - Comprehensive docstring explaining both access modes

### 2. `route_frontend_control_center.py`
- Updated the `control_center()` route to:
  - Compute `has_full_admin_access` based on user roles AND settings
  - Pass the correct value to the template for conditional tab rendering

### 3. `config.py`
- Version updated to `0.235.011`

## Code Changes Summary

### Decorator Logic (functions_authentication.py)
```python
# New logic flow:
# 1. Check if ControlCenterAdmin requirement is ENABLED
#    - If ENABLED: Only ControlCenterAdmin role grants access
#    - Regular Admin role is NOT sufficient
# 2. If ControlCenterAdmin requirement is DISABLED:
#    - Only regular Admin role grants access
#    - ControlCenterAdmin role is IGNORED (feature not enabled)
#    - DashboardReader gets dashboard-only (if that setting enabled)
# 3. Non-admin users are denied with appropriate message
```

### Frontend Route Logic (route_frontend_control_center.py)
```python
# Compute has_full_admin_access based on which mode is active:
if require_member_of_control_center_admin:
    # ControlCenterAdmin role is required
    has_full_admin_access = has_control_center_admin_role
else:
    # Only regular Admin role grants access
    has_full_admin_access = has_regular_admin_role
```

## Testing

Functional test created: `functional_tests/test_control_center_access_logic.py`

The test validates:
1. Decorator checks for regular Admin role
2. Decorator checks for ControlCenterAdmin role
3. ControlCenterAdmin gets access when setting is enabled
4. ControlCenterAdmin is ignored when setting is disabled
5. Regular Admin gets access when requirement is disabled
6. Non-admin users are denied access
7. Comprehensive docstring exists

## Validation Steps

1. **Test as Admin (CC admin requirement DISABLED)**:
   - User with `Admin` role should see all Control Center tabs
   
2. **Test as ControlCenterAdmin ONLY (CC admin requirement DISABLED)**:
   - User with only `ControlCenterAdmin` role should be DENIED access
   
3. **Test as Admin (CC admin requirement ENABLED)**:
   - User with only `Admin` role should be DENIED access
   
4. **Test as ControlCenterAdmin (CC admin requirement ENABLED)**:
   - User with `ControlCenterAdmin` role should have full access
   
5. **Test as DashboardReader**:
   - Should see only Dashboard tab when that requirement is enabled

## Related Settings

| Setting | Description |
|---------|-------------|
| `require_member_of_control_center_admin` | When enabled, requires ControlCenterAdmin role for full access. When disabled, uses Admin role instead. |
| `require_member_of_control_center_dashboard_reader` | When enabled, allows DashboardReader role for dashboard-only access |
