# Cosmos Throughput Portal-Managed Limit Fix - Version 0.241.199

Fixed/Implemented in version: **0.241.199**

## Issue Description

Cosmos throughput automation could present SimpleChat-managed scaling controls for targets above 10,000 RU/s. Capacity changes above this level can require a long Azure provisioning window, so admins needed clearer guidance that high-throughput targets should be monitored in SimpleChat but changed in the Azure portal.

## Root Cause Analysis

The Cosmos throughput default maximum and policy guardrails previously allowed values above the SimpleChat support ceiling. Backend decisions and admin UI controls did not consistently distinguish between throughput targets SimpleChat can scale directly and higher-capacity targets that should remain monitor-only.

## Technical Details

### Files Modified

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added a 10,000 RU/s SimpleChat scaling ceiling for Cosmos throughput decisions.
- Preserved utilization and request-unit monitoring for database or container throughput above 10,000 RU/s.
- Blocked backend scale and manual-to-autoscale update paths when the current or target throughput requires portal-managed capacity changes.
- Added portal-managed status metadata so the admin UI can show monitor-only indicators.
- Updated Admin Settings copy to explain that portal capacity changes above 10,000 RU/s can take 4 to 6 hours.
- Added a container policy modal filter and prefilled it when opening the modal from a row gear button.

### Testing Approach

- Added functional coverage for 9,000 to 10,000 scale-up, 10,000 scale-up advisory behavior, and >10,000 monitor-only decisions.
- Added functional coverage to reject manual scale requests for portal-managed targets.
- Added UI assertions for monitor-only labels, portal copy, the 10,000 maximum input cap, and the container policy modal filter.

### Impact Analysis

SimpleChat continues to scale targets at or below 10,000 RU/s. Throughput above 10,000 RU/s remains visible in Admin Settings for monitoring, but SimpleChat disables scale and conversion controls and instructs admins to use the Azure portal for capacity changes.

## Validation

### Test Results

Focused validation was run against the Cosmos throughput backend logic, admin JavaScript syntax, and Admin Settings UI tests.

### Before/After Comparison

Before this fix, a high-throughput Cosmos target could appear to be SimpleChat-managed and the policy modal required admins to hunt through large container lists. After this fix, high-throughput targets are marked monitor-only, SimpleChat blocks unsupported scaling paths, and row gear buttons open the policy modal filtered to the selected container.

### User Experience Improvements

Admins now see an explicit monitor-only designation for targets above 10,000 RU/s, with clear guidance that Azure portal capacity changes can take 4 to 6 hours. The container policy modal is faster to use because it includes filtering and opens directly to the selected container when launched from a table row.

## Version Reference

Application version updated in `application/single_app/config.py` from **0.241.198** to **0.241.199**.
