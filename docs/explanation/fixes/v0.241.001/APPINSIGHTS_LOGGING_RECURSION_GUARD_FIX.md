# AppInsights Logging Recursion Guard Fix

## Issue Description

Running SimpleChat locally in Docker triggered a startup exception chain involving:

- `functions_settings.get_settings()`
- `functions_appinsights.log_event()`
- `functions_appinsights._load_logging_settings()`

The call path recursively re-entered settings retrieval while handling a settings-related error log.

## Root Cause Analysis

`_load_logging_settings()` attempted to call `get_settings()` whenever cache was unavailable.
At the same time, `get_settings()` used `log_event()` for error logging.
That created a re-entrant loop (`get_settings` → `log_event` → `_load_logging_settings` → `get_settings`) that could cascade during exception formatting.

## Version Implemented

Fixed/Implemented in version: **0.240.005**

Related config version update:

- `application/single_app/config.py` → `VERSION = "0.240.005"`

## Technical Details

### Files Modified

- `application/single_app/functions_appinsights.py`
- `functional_tests/test_appinsights_logging_recursion_guard.py`

### Code Changes Summary

- Added thread-local state (`_logging_settings_load_state`) to guard `_load_logging_settings()`.
- Added early return when guard is active to prevent recursive settings loads.
- Wrapped `get_settings()` call with guard activation and `finally` reset for safe cleanup.
- Added a functional regression test to verify guard markers are present.

## Validation

### Test Results

- `py -m py_compile application/single_app/functions_appinsights.py application/single_app/functions_settings.py application/single_app/config.py`
- `py functional_tests/test_appinsights_logging_recursion_guard.py`

### Before/After Comparison

- **Before**: logging path could recursively invoke settings retrieval and fail during traceback processing.
- **After**: recursive re-entry into settings retrieval is blocked; logging safely degrades to empty settings when re-entered.
