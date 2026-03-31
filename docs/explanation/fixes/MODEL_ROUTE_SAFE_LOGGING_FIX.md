# Model Route Safe Logging Fix

Fixed/Implemented in version: **0.239.190**

## Header Information

### Issue Description

Several model-management routes returned raw exception text directly to the browser and mixed route logging between `debug_print` and `log_event`.

That exposed internal error details to end users and made route diagnostics inconsistent.

### Root Cause Analysis

The route handlers used broad `except Exception` blocks that surfaced `str(e)` in JSON responses.

The file also relied on ad hoc debug logging instead of routing all logging through `log_event`.

### Version Implemented

`0.239.190`

## Technical Details

### Files Modified

- `application/single_app/route_backend_models.py`
- `application/single_app/config.py`
- `functional_tests/test_route_backend_models_safe_logging.py`

### Code Changes Summary

- Replaced route-level `debug_print` usage with `log_event`-based helpers.
- Added shared helpers for safe user-facing JSON error responses and group access error mapping.
- Removed raw exception text from model fetch, model test, model listing, and group authorization responses.
- Preserved actionable validation messages where the route is intentionally returning a controlled client error.
- Bumped the application version to `0.239.190`.

### Testing Approach

- Added a functional regression test that verifies `route_backend_models.py` uses `log_event`, no longer imports `debug_print`, and does not return raw exception text in JSON error responses.

### Impact Analysis

- Reduces accidental disclosure of internal exception details.
- Makes model route logging consistent with the repository logging guidance.
- Keeps user-facing errors understandable without exposing backend internals.

## Validation

### Before/After Comparison

Before: multiple model routes returned direct exception text such as `str(e)` and mixed logging implementations.

After: model routes log through `log_event` and return controlled, safe error messages to the browser.

### Test Results

- Functional regression test added for safe logging and safe error response enforcement.