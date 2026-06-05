# Cosmos Container Policy Save Button Fix

Fixed/Implemented in version: **0.241.150**

## Issue Description

After selecting Containers in the Admin Settings Scale tab and choosing Save Container Policies, the page showed that the policies were staged but the floating Admin Settings Save button remained disabled. Admins could not persist the staged container policies.

## Root Cause Analysis

The container policy staging code updated the hidden policy JSON field and set the internal `formModified` flag directly. It did not call the existing `markFormAsModified()` helper, which is responsible for enabling and restyling the main Save Settings button.

## Technical Details

Files modified:

- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `ui_tests/test_admin_cosmos_throughput_settings_ui.py`
- `docs/explanation/release_notes.md`

Code changes summary:

- `writeCosmosContainerPolicies()` now calls `markFormAsModified()` after updating the hidden container policy JSON field.
- Added UI regression coverage to verify container policy staging uses the standard admin form dirty-state path.
- Application version updated to `0.241.150`.

## Validation

Test results:

- JavaScript syntax validation for `admin_settings.js`.
- Focused UI regression test for Admin Settings Cosmos throughput controls and container policy staging.

Before/after comparison:

- Before: Save Container Policies staged the JSON but left the main Save Settings button disabled.
- After: Save Container Policies stages the JSON and immediately enables the main Save Settings button.

Related config.py version update

- Application version updated to `0.241.150` in `application/single_app/config.py`.
