# Control Center Activity Log Auto-Refresh

Fixed/Implemented in version: **0.241.028**

## Overview and Purpose

The Control Center Activity Logs tab now lets admins enable browser-side auto-refresh while they monitor recent activity. The control is designed for live operations views where admins previously stayed on the page and repeatedly clicked Reload.

Dependencies: `application/single_app/templates/control_center.html`, `application/single_app/static/js/control-center.js`, browser `localStorage`, Bootstrap form controls, and the existing Activity Logs API.

## Technical Specifications

Architecture overview:

- The Activity Logs tab exposes an Auto-refresh switch, interval slider, seconds input, and quick interval presets.
- The interval range is 1 to 300 seconds with a 30-second default.
- The browser stores the enabled state and interval in `localStorage` using `simplechat_activityLogsAutoRefreshEnabled` and `simplechat_activityLogsAutoRefreshIntervalSeconds`.
- Auto-refresh only schedules while the Activity Logs tab is active and the document is visible.
- Auto-refresh pauses after authorization failures or repeated refresh errors to avoid noisy background polling.

Configuration options:

- Minimum interval: 1 second
- Maximum interval: 300 seconds
- Default interval: 30 seconds
- Quick presets: 1s, 10s, 30s, 60s, 5m

File structure:

- `application/single_app/templates/control_center.html` - Activity Logs auto-refresh toolbar and responsive styling.
- `application/single_app/static/js/control-center.js` - persisted auto-refresh state, interval controls, timer scheduling, and failure handling.
- `functional_tests/test_control_center_activity_logs_auto_refresh.py` - source-level regression coverage.
- `ui_tests/test_control_center_activity_logs_auto_refresh.py` - browser workflow and persistence validation.
- `application/single_app/config.py` - version updated to 0.241.028 for this feature.

## Usage Instructions

1. Open Control Center.
2. Select Activity Logs.
3. Turn on Auto-refresh.
4. Set the interval with a quick preset, slider, or seconds input.

Integration points:

- Manual Reload still works and resets the next auto-refresh timer.
- Search, activity type, and per-page changes continue to reload immediately and then resume the configured interval.
- Interval choices persist per browser and device.

## Testing and Validation

Test coverage:

- `functional_tests/test_control_center_activity_logs_auto_refresh.py`
- `ui_tests/test_control_center_activity_logs_auto_refresh.py`

Validation highlights:

- Confirms the template exposes the switch, range control, seconds input, presets, status region, and responsive toolbar styling.
- Confirms the JavaScript persists the enabled state and interval, schedules with `setTimeout`, pauses while hidden, and stops after auth or repeated failures.
- Confirms the browser workflow can enable auto-refresh, change intervals, persist settings, and trigger repeated Activity Logs API requests.

Known limitations:

- Auto-refresh is a per-browser preference, not an administrator-wide server setting.
- The timer refreshes the current Activity Logs page and filters; it does not force a metrics recalculation.