# ADMIN SETTINGS SAFE INT FALLBACK FIX

## Overview

- **Issue**: Admin settings save flow could throw a `TypeError` when `safe_int()` returned a non-integer fallback value.
- **Root Cause**: `safe_int()` returned `fallback_value` as-is after parse failure; if persisted fallback values were malformed (for example strings that cannot be converted), subsequent `max(1, ...)` / `max(0, ...)` operations could fail.
- **Fixed/Implemented in version: `0.239.006`**
- **Related version update**: `application/single_app/config.py` updated to `VERSION = "0.239.006"`.

## Technical Details

### Files Modified

- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/admin_settings_int_utils.py`
- `application/single_app/config.py`
- `functional_tests/test_admin_settings_safe_int_fallback_fix.py`
- `functional_tests/test_idle_logout_timeout.py`
- `functional_tests/test_settings_deep_merge_persistence_fix.py`

### Code Changes Summary

- Extracted integer parsing into module-level helper functions (`safe_int`, `safe_int_with_source`) in `admin_settings_int_utils.py`.
- Updated admin settings route to use the extracted helper while preserving existing fallback and hard-default `log_event` diagnostics.
- Kept idle-timeout call sites using explicit hard defaults (`30` and `28`).

### Testing Approach

- Refactored `functional_tests/test_admin_settings_safe_int_fallback_fix.py` to behavior-level helper tests (malformed raw and fallback values) plus AST route wiring validation.
- Kept existing functional tests version-aligned with release version.

### Impact Analysis

- Prevents runtime `TypeError` in admin settings save flow for malformed persisted fallback values.
- Improves resiliency of idle-timeout configuration handling without changing intended behavior for valid values.

## Validation

### Before

- Invalid form input could cause `safe_int()` to return non-int fallback values, potentially raising `TypeError` in `max()`.

### After

- `safe_int()` always returns a valid integer from raw input, parsed fallback, or hard default.

### Test Result

- Verified by running `py -3 functional_tests/test_admin_settings_safe_int_fallback_fix.py`.
