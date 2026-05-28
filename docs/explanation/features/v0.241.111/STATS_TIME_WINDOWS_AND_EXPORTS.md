# Stats Time Windows and Exports

Implemented in version: **0.241.111**

## Overview

Personal profile stats, group stats, and public workspace stats now support the same 7-day, 30-day, 90-day, and custom date-window pattern used by Control Center activity trends.

## Dependencies

- `application/single_app/functions_stats_windows.py` for shared date-window parsing and daily bucket generation.
- Existing activity log records in the `activity_logs` container.
- Existing Chart.js rendering on profile, group, and public workspace stats pages.

## Technical Specifications

- Personal stats use `/api/user/activity-trends` with `days`, `start_date`, and `end_date` query parameters.
- Group stats use `/api/groups/<group_id>/stats` with the same date-window parameters.
- Public workspace stats use `/api/public_workspaces/<ws_id>/stats` with the same date-window parameters.
- Each stats API returns a `window` payload and `dateRange` values so the frontend can label charts accurately.

## Usage

Users can select 7 Days, 30 Days, 90 Days, or Custom in the stats tab. Export buttons on personal, group, and public stats pages create CSV files for the selected metric sections and selected date window.

## Testing and Validation

- `functional_tests/test_stats_time_windows.py` validates shared window parsing, custom range handling, and timestamp bucket normalization.
- `ui_tests/test_stats_time_windows_and_exports.py` validates the browser controls and export modals when authenticated UI test environment variables are available.

## Version Reference

- `application/single_app/config.py` was updated to `0.241.111` for this feature.