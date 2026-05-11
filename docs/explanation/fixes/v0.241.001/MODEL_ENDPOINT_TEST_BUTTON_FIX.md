# Model Endpoint Test Button Fix (v0.236.020)

## Issue Description
The per-model Test Connection button did not trigger a test because the payload builder referenced `authType` before it was defined, which caused a runtime error.

## Root Cause Analysis
`buildEndpointPayload()` used `authType` in validation checks before declaring it, resulting in a `ReferenceError` and preventing any request from being sent.

## Version Implemented
Fixed/Implemented in version: **0.236.020**

## Technical Details
### Files Modified
- application/single_app/static/js/admin/admin_model_endpoints.js
- application/single_app/config.py

### Code Changes Summary
- Defined `authType` before provider-specific validation checks in `buildEndpointPayload()`.
- Incremented the application version.

### Testing Approach
- Added a functional test to verify `authType` is declared before validation checks.

### Impact Analysis
- Per-model Test Connection now triggers correctly.

## Validation
- Functional test: functional_tests/test_model_endpoint_payload_auth_type_order.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.020**.
