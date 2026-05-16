# Control Center Auto-Refresh Schedule

Implemented in version: **0.241.026**

## Overview

Control Center administrators can now configure a daily UTC refresh schedule for Control Center metrics. The setting is enabled by default and runs at **06:00 UTC** unless an administrator changes the time under Admin Settings > Control Center.

## Technical Specifications

- **Settings defaults**: `control_center_auto_refresh_enabled`, `control_center_auto_refresh_time`, `control_center_auto_refresh_hour`, `control_center_auto_refresh_minute`, and `control_center_auto_refresh_next_run` are defined in `application/single_app/functions_settings.py`.
- **Schedule helpers**: `application/single_app/functions_control_center.py` normalizes the configured time and calculates the next daily UTC run.
- **Background execution**: `application/single_app/background_tasks.py` checks the schedule every five minutes and uses the existing distributed lock pattern before calling the Control Center refresh.
- **Admin UI**: `application/single_app/templates/admin_settings.html` exposes the enable toggle, UTC time input, and next-run display under the Control Center settings tab.
- **Status API**: `application/single_app/route_backend_control_center.py` returns auto-refresh schedule metadata from `/api/admin/control-center/refresh-status`.
- **Version update**: `application/single_app/config.py` was updated to version **0.241.026** for this feature.

## Usage Instructions

1. Open Admin Settings.
2. Select the Control Center tab.
3. Use Automatic Data Refresh to enable or disable the daily refresh.
4. Set the refresh time in UTC. The default is 06:00.
5. Save settings to calculate the next scheduled run.

## Testing and Validation

- Functional coverage: `functional_tests/test_control_center_auto_refresh_schedule.py`
- UI coverage: `ui_tests/test_admin_settings_control_center_auto_refresh.py`
- The background scheduler preserves the existing manual refresh behavior and only runs the automatic refresh when the saved next-run timestamp is due.

## Known Limitations

- The scheduler checks every five minutes, so the refresh may start a few minutes after the configured time.
- The configured time is UTC-only to avoid ambiguity across app instances and regional deployments.