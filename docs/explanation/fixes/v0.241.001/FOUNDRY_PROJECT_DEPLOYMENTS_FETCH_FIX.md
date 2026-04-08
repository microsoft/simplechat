# Foundry Project Deployments Fetch Fix (v0.236.026)

## Header Information
- **Fix Title:** Foundry project deployments fetch uses project-scoped API
- **Issue Description:** Foundry model discovery was pulling from account-level or data-plane lists, which did not align with project-scoped deployments shown in Foundry projects.
- **Root Cause Analysis:** The discovery logic relied on generic model list fallbacks and management-plane deployments, instead of the project deployments list endpoint.
- **Version Implemented:** 0.236.026

## Fixed/Implemented in version: **0.236.026**

## Technical Details
- **Files Modified:**
  - application/single_app/route_backend_models.py
  - application/single_app/static/js/admin/admin_model_endpoints.js
  - functional_tests/test_foundry_model_list_fallback.py
  - application/single_app/config.py
- **Code Changes Summary:**
  - Switched Foundry discovery to the project deployments list endpoint using the project API scope.
  - Removed subscription/resource group requirement for Foundry project discovery in the admin modal validation.
  - Updated the functional test to validate project deployments discovery.
  - Incremented the application version to 0.236.026.
- **Testing Approach:**
  - Updated functional test validates project deployments discovery helper and scope usage.
- **Impact Analysis:**
  - Foundry model discovery now reflects project-scoped deployments.
  - Admin configuration flow no longer blocks on subscription/resource group for Foundry discovery.

## Validation
- **Test Results:** Functional test updated (see functional_tests/test_foundry_model_list_fallback.py).
- **Before/After Comparison:**
  - **Before:** Foundry model discovery used account-level or data-plane model listings.
  - **After:** Foundry model discovery uses the project deployments list endpoint.
- **User Experience Improvements:**
  - Admins see the same project deployments as the Foundry project UI.

## References
- Config version updated in application/single_app/config.py to 0.236.026.
