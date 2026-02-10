# Foundry Inference Scope Fix (v0.236.027)

## Header Information
- **Fix Title:** Foundry inference token scope uses AI Foundry audience
- **Issue Description:** Testing Foundry models returned 401 Unauthorized due to an incorrect token audience.
- **Root Cause Analysis:** The inference token used the Cognitive Services scope instead of the AI Foundry scope for Foundry project endpoints.
- **Version Implemented:** 0.236.027

## Fixed/Implemented in version: **0.236.027**

## Technical Details
- **Files Modified:**
  - application/single_app/route_backend_models.py
  - application/single_app/config.py
  - functional_tests/test_foundry_inference_scope_fix.py
- **Code Changes Summary:**
  - Updated inference client to use the AI Foundry token scope for Foundry endpoints.
  - Added a functional test to assert provider-aware scope selection.
  - Incremented the application version to 0.236.027.
- **Testing Approach:**
  - Functional test validates the Foundry-specific scope is present in the inference path.
- **Impact Analysis:**
  - Foundry model tests authenticate successfully when using managed identity or service principal.

## Validation
- **Test Results:** Functional test added (see functional_tests/test_foundry_inference_scope_fix.py).
- **Before/After Comparison:**
  - **Before:** Foundry model test used Cognitive Services token scope.
  - **After:** Foundry model test uses AI Foundry token scope.
- **User Experience Improvements:**
  - Admins can test Foundry model connections without unauthorized errors.

## References
- Config version updated in application/single_app/config.py to 0.236.027.
