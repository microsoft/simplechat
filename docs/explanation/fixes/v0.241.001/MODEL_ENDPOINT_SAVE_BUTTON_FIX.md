# Model Endpoint Save Button Fix (v0.236.021)

## Issue Description
Clicking the Save Endpoint button in the model endpoint modal did not trigger any visible action.

## Root Cause Analysis
The click handler did not guard against errors, and failures in the save flow were not surfaced to the user.

## Version Implemented
Fixed/Implemented in version: **0.236.021**

## Technical Details
### Files Modified
- application/single_app/static/js/admin/admin_model_endpoints.js
- application/single_app/config.py

### Code Changes Summary
- Wrapped `saveEndpoint()` in a try/catch with toast error handling.
- Ensured Save button prevents default behavior and always invokes the handler.
- Incremented the application version.

### Testing Approach
- Added a functional test to confirm Save button wiring and error handling exists.

### Impact Analysis
- Save Endpoint now reliably triggers and surfaces errors.

## Validation
- Functional test: functional_tests/test_model_endpoints_save_button.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.021**.
