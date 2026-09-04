# Control Center Auto-Refresh Schedule

Implemented in version: **0.241.026**
Updated in version: **0.250.102**

## Overview

Control Center administrators can configure a daily refresh schedule for cached Control Center metrics. The setting is enabled by default and new installations run at **02:00 America/New_York** unless an administrator changes the time under Admin Settings > Control Center. The IANA timezone keeps the recurring rule at 2:00 AM across Eastern Standard Time and Eastern Daylight Time.

## Technical Specifications

- **Dependency**: `tzdata==2026.3` supplies the IANA timezone database on platforms such as Windows that do not ship one with Python.
- **Settings defaults**: `control_center_auto_refresh_enabled`, `control_center_auto_refresh_time`, `control_center_auto_refresh_hour`, `control_center_auto_refresh_minute`, `control_center_auto_refresh_timezone`, and `control_center_auto_refresh_next_run` are defined in `application/single_app/functions_settings.py`.
- **Schedule helpers**: `application/single_app/functions_control_center.py` normalizes the configured wall-clock time and IANA timezone, then calculates the next run as a timezone-aware UTC timestamp.
- **Background execution**: `application/single_app/background_tasks.py` checks the schedule every five minutes and uses the existing distributed lock pattern before calling the Control Center refresh.
- **Admin UI**: `application/single_app/templates/admin_settings.html` exposes the enable toggle, recurring time, configured timezone, browser timezone, and browser-local next-run display under the Control Center settings tab.
- **Status API**: `application/single_app/route_backend_control_center.py` returns the recurring rule and canonical UTC next-run timestamp from `/api/admin/control-center/refresh-status`.
- **Control Center display**: `application/single_app/static/js/control-center.js` formats last-run and next-run UTC timestamps in the viewer's browser timezone.
- **Version update**: `application/single_app/config.py` was updated to version **0.250.102** for the DST-aware schedule and browser-local display.

## Storage and Compatibility

- Concrete timestamps such as `control_center_last_refresh` and `control_center_auto_refresh_next_run` are stored as timezone-aware UTC ISO values.
- The recurring rule stores a wall-clock time plus an IANA timezone because a fixed UTC clock value cannot preserve a local run time across daylight-saving transitions.
- Existing installations using the original 06:00 UTC default migrate to 02:00 `America/New_York`.
- Existing custom UTC schedules retain their UTC behavior until an administrator changes the schedule.

## Usage Instructions

1. Open Admin Settings.
2. Select the Control Center tab.
3. Use Automatic Data Refresh to enable or disable the daily refresh.
4. Set the refresh time. The default rule is 02:00 `America/New_York`.
5. Review the browser-local next-run value and save settings.

## Testing and Validation

- Functional coverage: `functional_tests/test_control_center_auto_refresh_schedule.py`
- UI coverage: `ui_tests/test_admin_settings_control_center_auto_refresh.py`
- The background scheduler preserves the existing manual refresh behavior and only runs the automatic refresh when the saved UTC next-run timestamp is due.
- Regression coverage verifies winter, summer, spring-forward, and fall-back UTC calculations.

## Known Limitations

- The scheduler checks every five minutes, so the refresh may start a few minutes after the configured time.
- A configured time that does not exist during a spring-forward transition runs at the first valid instant after the skipped local hour.
- Deployed environments must enable SimpleChat background tasks through `SIMPLECHAT_RUN_BACKGROUND_TASKS=1`.