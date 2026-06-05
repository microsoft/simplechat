# Cosmos Throughput Table Clarity Fix

Fixed/Implemented in version: **0.241.151**

## Issue Description

The Admin Settings Scale tab showed Cosmos container metrics in a crowded table that mixed database name, RU utilization, and request-unit volume without enough explanation. Admins could confuse request units with utilization percentage, and the text Configure action took unnecessary space in each container row.

## Root Cause Analysis

The container table was originally shaped around database-level throughput and later gained container-targeted scaling. The table still kept the redundant Database column and did not distinguish unavailable Azure Monitor container metrics from a real zero-value metric row.

## Technical Details

Files modified:

- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/config.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `docs/explanation/release_notes.md`

Code changes summary:

- Removed the Database column from the Cosmos container metrics table.
- Added tooltip explanations for RU Utilization and Request Units.
- Replaced the visible Configure row action with a gear-only button and accessible label.
- Added a Cosmos Throughput Setup Guide modal with a Run Test button that reuses the refresh/status check path.
- Preserved missing Azure Monitor container request-unit metrics as unavailable instead of showing a misleading zero.
- Application version updated to `0.241.151`.

## Validation

Test results:

- JavaScript syntax validation for `admin_settings.js`.
- Python syntax validation for `functions_cosmos_throughput.py`.
- Focused UI regression test for Admin Settings Cosmos throughput controls, setup guide, and compact container table rendering.

Before/after comparison:

- Before: the table included a redundant Database column, unclear metric labels, and a wide Configure text button.
- After: the table focuses on container, mode, current RU/s, utilization, request-unit volume, policy, and compact actions with explanatory tooltips.

Related config.py version update

- Application version updated to `0.241.151` in `application/single_app/config.py`.