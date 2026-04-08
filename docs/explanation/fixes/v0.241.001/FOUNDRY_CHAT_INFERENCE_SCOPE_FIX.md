# Foundry Chat Inference Scope Fix (v0.236.030)

## Header Information
- **Fix Title:** Foundry chat inference uses cloud-aware scopes
- **Issue Description:** Multi-endpoint Foundry inference in chat returned 401 Unauthorized due to incorrect token audience.
- **Root Cause Analysis:** Chat route always used the Cognitive Services scope and did not apply the Foundry scope per cloud.
- **Version Implemented:** 0.236.030

## Fixed/Implemented in version: **0.236.030**

## Technical Details
- **Files Modified:**
  - application/single_app/route_backend_chats.py
  - functional_tests/test_foundry_chat_scope_resolution.py
  - application/single_app/config.py
- **Code Changes Summary:**
  - Added Foundry scope resolution for multi-endpoint chat inference.
  - Applied service principal cloud tags and endpoint-based scope inference for managed identity.
  - Added a functional test validating scope resolution.
  - Incremented the application version to 0.236.030.
- **Testing Approach:**
  - Functional test checks for cloud-aware scope logic in chat routes.
- **Impact Analysis:**
  - Foundry chat inference now requests tokens with the correct audience per cloud.

## Validation
- **Test Results:** Functional test added (see functional_tests/test_foundry_chat_scope_resolution.py).
- **Before/After Comparison:**
  - **Before:** Foundry chat inference always used Cognitive Services scope.
  - **After:** Foundry chat inference derives scope based on cloud and endpoint.
- **User Experience Improvements:**
  - Foundry model inference works in multi-endpoint chat without unauthorized errors.

## References
- Config version updated in application/single_app/config.py to 0.236.030.
