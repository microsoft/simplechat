# Admin Activity Log User ID Fix

## Overview

Fixed a Control Center activity log failure caused by some `admin_action` records storing `user_id` as a full session identity object instead of a string identifier.

Fixed in version: **0.241.021**

## Root Cause

The admin settings route passed the entire `session['user']` payload into `log_general_admin_action(...)` for the multi-model endpoint migration event. That helper persisted the value directly into the activity log record, so some `admin_action` rows were written with a dictionary-valued `user_id`.

The Control Center activity log API later built a user lookup cache with those values as dictionary keys, which raised `TypeError: unhashable type: 'dict'`.

## Technical Details

Files modified:

- `application/single_app/functions_activity_logging.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/route_backend_control_center.py`
- `application/single_app/config.py`
- `functional_tests/test_admin_action_activity_log.py`
- `functional_tests/test_control_center_activity_logs_hardening.py`

Code changes summary:

- Added `coerce_activity_log_user_id(...)` to extract a stable string id from session-style identity objects.
- Updated `log_general_admin_action(...)` to normalize `admin_user_id` before persisting the activity record.
- Fixed the admin settings route to pass the scalar `user_id` returned by `get_current_user_id()`.
- Hardened Control Center activity log normalization and user-map building so older malformed records no longer crash the reader path.

Testing approach:

- Updated activity logging regression coverage to assert user id normalization in the writer path.
- Updated Control Center activity log hardening checks to assert malformed user id normalization support.

Impact analysis:

- Newly created admin action records now store string user identifiers consistently.
- Existing malformed activity log records remain readable without requiring an immediate data migration.

## Validation

Before:

- Loading the Control Center activity log page could fail with `TypeError: unhashable type: 'dict'`.

After:

- The writer normalizes admin identifiers before persistence.
- The reader normalizes legacy malformed records before user lookup.

Related functional tests:

- `functional_tests/test_admin_action_activity_log.py`
- `functional_tests/test_control_center_activity_logs_hardening.py`