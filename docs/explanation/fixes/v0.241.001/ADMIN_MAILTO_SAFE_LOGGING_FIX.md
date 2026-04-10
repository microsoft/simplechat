# Admin Mailto Safe Logging Fix

Fixed/Implemented in version: **0.240.002**

## Header Information

### Issue Description

The Admin Settings mailto endpoints returned raw exception text to the browser and used route-local logger calls instead of the application's centralized `log_event` telemetry.

The associated activity logging also forwarded overly detailed contact and free-form feedback data into telemetry for mailto draft preparation events.

### Root Cause Analysis

Both admin mailto routes handled unexpected exceptions with `current_app.logger.error(...)` and JSON error strings built from `str(e)`.

The mailto activity log helpers reused their full activity payloads for telemetry, which included more user-entered data than was required for monitoring and audit.

### Version Implemented

`0.240.002`

## Technical Details

### Files Modified

- `application/single_app/route_backend_settings.py`
- `application/single_app/functions_activity_logging.py`
- `application/single_app/config.py`
- `functional_tests/test_admin_mailto_safe_logging.py`
- `docs/explanation/features/SEND_FEEDBACK_ADMIN.md`
- `docs/explanation/features/RELEASE_NOTIFICATIONS_REGISTRATION.md`

### Code Changes Summary

- Replaced route-level `current_app.logger.error(...)` calls with `log_event(...)` error logging that captures traceback details centrally.
- Removed raw exception text from the Admin Settings feedback and release-notification mailto responses.
- Reduced mailto activity metadata to contact-presence, email-domain, organization-length, and details-length fields instead of full contact values or feedback previews in telemetry.
- Bumped the application version to `0.240.002`.

### Testing Approach

- Added a focused functional regression test that verifies generic client-facing 500 responses, centralized `log_event` error logging, and removal of free-form feedback previews from activity logging metadata.

### Impact Analysis

- Reduces accidental disclosure of internal exception details in browser-visible responses.
- Makes admin mailto route failures observable through the standardized telemetry path.
- Lowers the sensitivity of admin mailto activity metadata while preserving audit usefulness.

## Validation

### Before/After Comparison

Before: admin mailto failures returned `str(e)` to the client and used ad hoc route logging, while activity telemetry carried full contact fields and a feedback preview.

After: admin mailto failures log through `log_event`, return generic error messages, and store reduced activity metadata for telemetry.

### Test Results

- Functional regression coverage added in `functional_tests/test_admin_mailto_safe_logging.py`.
- Related feature documentation updated in `docs/explanation/features/SEND_FEEDBACK_ADMIN.md` and `docs/explanation/features/RELEASE_NOTIFICATIONS_REGISTRATION.md`.
