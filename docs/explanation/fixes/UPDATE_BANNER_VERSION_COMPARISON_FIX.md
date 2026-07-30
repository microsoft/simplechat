# Update Banner Version Comparison Fix

Fixed in version: **0.250.003**

Fixed/Implemented in version: **0.250.003**

## Issue Description

Admin Settings could display a stale cached update banner such as `New version available, v0.250.001` even when the running application version was already newer, for example `0.250.003`.

## Root Cause Analysis

The fresh update-check path compared the discovered release version against the running version, but the render path trusted persisted `update_available` and `latest_version_available` settings. When those cached settings were created by an older deployment, the page could continue to render the stale banner until the next scheduled update check refreshed the values.

## Technical Details

Files modified:

- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/config.py`
- `functional_tests/test_admin_update_banner_version_comparison.py`

Code changes summary:

- Added a helper that treats an update as available only when `latest_version > current_version` using the existing numeric version comparator.
- Recomputed `update_available` from cached `latest_version_available` and the running app version before rendering Admin Settings.
- Normalized stale persisted `update_available` values back to the computed value.

## Validation

Functional coverage is provided by `functional_tests/test_admin_update_banner_version_comparison.py`.

Before the fix, cached settings could show an older release as available. After the fix, older or equal cached versions are suppressed and only strictly newer versions show the update banner.
