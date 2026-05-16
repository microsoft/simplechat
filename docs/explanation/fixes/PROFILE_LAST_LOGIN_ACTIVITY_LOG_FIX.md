# Profile Last Login Activity Log Fix

Fixed/Implemented in version: **0.241.027**

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.027"`.

## Issue Description

The profile page hero displayed `Last Login` from cached user metrics stored in user settings. Those metrics are refreshed separately from live authentication activity, so the profile value could lag behind the current chat session and the actual `user_login` records in `activity_logs`.

## Root Cause Analysis

- The profile page loaded `/api/user/settings` and read `settings.metrics.login_metrics.last_login` directly.
- That value came from the metrics refresh/cache path, not the live `activity_logs` source used by login activity charts and audit reporting.
- The profile hero is a current-activity signal, so it should not depend on refreshed aggregate metrics.

## Technical Details

Files modified:

- `application/single_app/functions_activity_logging.py`
- `application/single_app/route_frontend_profile.py`
- `application/single_app/templates/profile.html`
- `application/single_app/config.py`
- `functional_tests/test_profile_last_login_activity_logs.py`
- `ui_tests/test_profile_last_login_activity_log_badge.py`

Code changes summary:

- Added `get_user_login_activity_summary(...)` to read login activity from the `activity_logs` container using the user's `/user_id` partition.
- Updated the profile settings API response to overlay `metrics.login_metrics.last_login` from activity logs before returning data to the profile page.
- Kept cached aggregate metrics, including total logins and chat/document totals, unchanged.
- Added a response-only `last_login_source` marker of `activity_logs` for the overlaid profile value.
- Updated the profile badge to show `Never` when activity logs contain no login record instead of leaving the placeholder text visible.

Testing approach:

- Added a dependency-free functional regression test with a fake activity log container.
- Covered newest-login selection across `timestamp` and `created_at` fields.
- Covered profile settings response overlay behavior and confirmed the cached settings document is not mutated.
- Added a Playwright UI regression test for the empty activity-log fallback shown in the profile hero.

## Validation

Before:

- The profile hero could show an older last-login date from refreshed cached metrics.
- Clearing or aging the metrics cache changed the displayed profile value even when activity logs had a newer login.

After:

- The profile hero receives last-login data from the live `activity_logs` lookup.
- Cached aggregate metrics remain available for total counts and the existing metrics calculated-date note.
- If activity logs contain no login record, the response clears the stale cached last-login value instead of presenting it as current activity.

Related functional tests:

- `functional_tests/test_profile_last_login_activity_logs.py`

Related UI tests:

- `ui_tests/test_profile_last_login_activity_log_badge.py`