# Get Settings Deep-Merge Bool Regression Fix

## Issue Description

SimpleChat startup in local Docker repeatedly logged settings retrieval errors and failed app initialization.

Primary error signature:

- `TypeError: argument of type 'bool' is not iterable`
- Triggered in `apply_custom_endpoint_setting_migration()` during `get_settings()`.

## Root Cause Analysis

`deep_merge_dicts()` mutates the target dictionary and returns a boolean change flag.

`get_settings()` incorrectly assigned this boolean return value to `merged`, then passed `merged` into migration logic that expected a dictionary. This caused migration checks like `"allow_user_custom_endpoints" not in settings_item` to fail because `settings_item` was actually a `bool`.

## Version Implemented

Fixed/Implemented in version: **0.240.006**

Related config version update:

- `application/single_app/config.py` → `VERSION = "0.240.006"`

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `functional_tests/test_get_settings_merge_bool_regression.py`

### Code Changes Summary

- Updated `get_settings()` to store deep-merge return in `merge_changed` and keep `merged = settings_item`.
- Updated persistence condition to `if merge_changed or migration_updated:`.
- Added defensive type check in `apply_custom_endpoint_setting_migration()` to return safely when input is not a dict.
- Added regression test to verify merge flag usage and guard against legacy assignment.

## Validation

### Test Results

- `py -m py_compile application/single_app/functions_settings.py application/single_app/functions_appinsights.py application/single_app/config.py`
- `py functional_tests/test_get_settings_merge_bool_regression.py`
- `py functional_tests/test_appinsights_logging_recursion_guard.py`

### Before/After Comparison

- **Before**: `get_settings()` could pass a boolean into migration logic, causing startup failures and repeated settings logging errors.
- **After**: `get_settings()` preserves dictionary payload for migrations; merge changes are tracked via explicit boolean flag.
