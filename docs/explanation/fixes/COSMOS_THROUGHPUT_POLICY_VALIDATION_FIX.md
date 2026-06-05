# Cosmos Throughput Policy Validation Fix

## Issue Description

Fixed in version: **0.241.161**

The Admin Settings Scale tab allowed Cosmos throughput automation settings to be saved with contradictory policy values. For example, an admin could set a Metrics Window longer than the scale-up or scale-down interval, or set Scale Up At to a value lower than or equal to Scale Down At.

## Root Cause Analysis

The backend normalization layer silently repaired invalid policy relationships so runtime automation stayed safe, but the Admin Settings save flow did not reject the invalid input or explain why the values could not work together. The frontend also had no save-blocking validation for these relationships.

## Version Implemented

Fixed in version: **0.241.161**

Related config.py version update: `VERSION = "0.241.161"`

## Technical Details

### Files Modified

- `application/single_app/functions_cosmos_throughput.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `functional_tests/test_cosmos_throughput_autoscale_logic.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `application/single_app/config.py`
- `docs/explanation/features/v0.241.147/COSMOS_THROUGHPUT_AUTOSCALE.md`

### Code Changes Summary

- Added explicit save validation for Cosmos throughput policy relationships.
- Blocked saves when Scale Up At is not higher than Scale Down At.
- Blocked saves when Scale Up Interval or Scale Down Interval is smaller than the Metrics Window.
- Applied the same policy relationship checks to enabled per-container policies when global defaults are not enforced.
- Grouped Scale Up Policy and Scale Down Policy controls in the Admin Settings Scale tab.
- Preserved runtime normalization repair behavior for existing saved settings while making new admin saves explicit.

### Testing Approach

- Backend functional tests verify invalid global and per-container policies produce validation errors.
- UI tests verify the grouped Scale tab sections and validation hooks exist.
- Syntax checks cover the changed backend route/helper and admin JavaScript.

### Impact Analysis

Admins now get immediate, clear feedback before an invalid Cosmos throughput policy is saved. Automation policy settings are easier to scan because scale-up controls and scale-down controls are grouped separately.

## Validation

The fix should be validated with:

- Python compilation for changed backend and test files.
- JavaScript syntax validation for Admin Settings.
- Focused Cosmos throughput functional tests.
- Focused Admin Settings Cosmos throughput UI tests.