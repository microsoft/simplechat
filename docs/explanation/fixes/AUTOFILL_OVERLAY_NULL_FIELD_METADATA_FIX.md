# Autofill Overlay Null Field Metadata Fix (v0.240.007)

## Issue Description
The Admin Settings experience could trigger browser autofill overlay errors after the Send Feedback and Latest Features updates. The page introduced new utility inputs and mirrored proxy controls that some browser extensions attempted to classify, and the page could stop rendering cleanly when that metadata was incomplete.

## Root Cause Analysis
The page markup still contained mirrored Latest Features controls that relied only on element `id` values and did not expose explicit proxy `name` values or autofill-ignore metadata. That worked for the app logic because JavaScript syncs those controls to the canonical settings fields, but some autofill tools expect conventional field metadata and can fail when a classification path encounters missing values on password-like or form controls.

## Version Implemented
Fixed/Implemented in version: **0.240.007**

## Technical Details
- Files modified:
  - `application/single_app/static/js/admin/admin_settings.js`
  - `application/single_app/templates/admin_settings.html`
  - `application/single_app/config.py`
  - `functional_tests/test_admin_send_feedback_tab.py`
  - `functional_tests/test_admin_latest_features_tab.py`
- Code changes summary:
  - Added explicit proxy `name` attributes to mirrored Latest Features controls.
  - Added `autocomplete="off"` and common password-manager ignore attributes to the mirrored proxy fields that load on the default admin tab.
  - Added a JavaScript normalization pass that applies `autocomplete="off"` and password-manager ignore attributes to admin settings controls that still lacked explicit autofill metadata.
  - Kept the mirrored controls out of normal settings-change tracking while preserving explicit JavaScript synchronization with the canonical saved fields.
  - Extended the focused Latest Features and Send Feedback functional tests to lock in the broader autofill metadata normalization.
  - Bumped the application version to `0.240.007`.
- Testing approach:
  - Run the focused Send Feedback functional test.

## Validation
- Before: the page could surface autofill overlay null-reference errors when extensions inspected Send Feedback fields.
- After: the default-load Latest Features proxy controls and the remaining admin settings form controls expose standard metadata and ignore hints, reducing the chance of extension-side null handling failures during admin page load.
- User experience improvement:
  - The Admin Settings page remains unchanged visually, but browser autofill integrations have more complete field metadata to work with on first load.