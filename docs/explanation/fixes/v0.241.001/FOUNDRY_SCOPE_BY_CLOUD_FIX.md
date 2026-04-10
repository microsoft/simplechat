# Foundry Scope by Cloud Fix (v0.236.028)

## Header Information
- **Fix Title:** Foundry scope derived from cloud configuration
- **Issue Description:** Foundry tokens used a hardcoded audience and did not support government or custom cloud scopes.
- **Root Cause Analysis:** Scope selection was fixed to the public cloud audience and lacked a custom scope override.
- **Version Implemented:** 0.236.028

## Fixed/Implemented in version: **0.236.028**

## Technical Details
- **Files Modified:**
  - application/single_app/route_backend_models.py
  - application/single_app/static/js/admin/admin_model_endpoints.js
  - application/single_app/templates/admin_settings.html
  - functional_tests/test_foundry_inference_scope_fix.py
  - application/single_app/config.py
- **Code Changes Summary:**
  - Added Foundry scope resolver that maps to public/government audiences and supports a custom scope value.
  - Added a Foundry scope input for custom cloud service principal configurations.
  - Hid Azure OpenAI subscription/resource group fields for Foundry endpoints.
  - Updated the functional test to validate cloud-specific scope handling.
  - Incremented the application version to 0.236.028.
- **Testing Approach:**
  - Functional test validates presence of cloud-specific and custom scope logic.
- **Impact Analysis:**
  - Foundry model discovery and inference now use the correct audience for public, government, and custom clouds.

## Validation
- **Test Results:** Functional test updated (see functional_tests/test_foundry_inference_scope_fix.py).
- **Before/After Comparison:**
  - **Before:** Foundry scope was hardcoded to public cloud.
  - **After:** Foundry scope is derived from cloud configuration with custom override support.
- **User Experience Improvements:**
  - Admins can configure Foundry endpoints across supported clouds without manual code changes.

## References
- Config version updated in application/single_app/config.py to 0.236.028.
