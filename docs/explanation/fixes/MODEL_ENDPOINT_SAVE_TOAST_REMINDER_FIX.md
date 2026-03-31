# Model Endpoint Save Toast Reminder Fix (v0.236.022)

## Issue Description
The endpoint modal displayed a success toast after saving a model endpoint, which led admins to assume settings were persisted without clicking the main Save Settings button.

## Root Cause Analysis
The toast message did not clarify that modal changes are staged and require saving the admin settings form.

## Version Implemented
Fixed/Implemented in version: **0.236.022**

## Technical Details
### Files Modified
- application/single_app/static/js/admin/admin_model_endpoints.js
- application/single_app/config.py

### Code Changes Summary
- Updated the success toast to remind users to save settings to persist changes.
- Incremented the application version.

### Testing Approach
- Added a functional test to confirm the updated toast message.

### Impact Analysis
- Reduces accidental data loss when navigating away without saving.

## Validation
- Functional test: functional_tests/test_model_endpoints_save_toast_message.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.022**.
