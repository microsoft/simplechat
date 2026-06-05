# Cosmos Autoscale Background Cadence Fix

Fixed/Implemented in version: **0.241.157**

## Issue Description

Admins needed to know whether Cosmos throughput background automation runs according to the Metrics Window setting. The prior implementation used a hard-coded 300-second scheduler sleep, which happened to match the default five-minute Metrics Window but did not follow the setting if admins changed it.

## Root Cause Analysis

The Metrics Window setting controlled only the Azure Monitor lookback range. The background scheduler loop slept for a fixed five minutes, and background logs were not clearly distinguishable from manual Admin Settings Refresh logs.

## Technical Details

Files modified:

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/background_tasks.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `functional_tests/test_cosmos_throughput_background_scheduler.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `docs/explanation/release_notes.md`

Code changes summary:

- Added a helper that calculates background autoscale cadence from `cosmos_throughput_metrics_window_minutes`.
- Updated the background loop to sleep for the calculated Metrics Window interval instead of a hard-coded 300 seconds.
- Added background autoscale start, completion, and sleep log markers with a `background-...` refresh ID.
- Kept Scale Up Interval and Scale Down Interval as cooldown controls after a scale action.
- Updated Admin Settings copy to say background automation refreshes on the Metrics Window cadence.
- Application version updated to `0.241.157` in `application/single_app/config.py`.

## Validation

Test results:

- Functional scheduler regression test validates Metrics Window-to-sleep interval mapping and background log markers.
- Python syntax validation for changed backend and test files.
- JavaScript syntax validation for `admin_settings.js`.
- Focused Cosmos throughput regression suite completed successfully.

Before/after comparison:

- Before: background checks always slept 300 seconds between runs.
- After: background checks sleep for the configured Metrics Window cadence, with one-minute minimum and one-hour maximum inherited from settings normalization.

Related config.py version update

- Application version updated to `0.241.157` in `application/single_app/config.py`.