# Foundry Management Fields Cleanup Fix (v0.236.029)

## Header Information
- **Fix Title:** Remove management fields from Foundry endpoint configuration
- **Issue Description:** Foundry endpoint configuration still referenced subscription/resource group/location fields after moving to project-scoped discovery.
- **Root Cause Analysis:** The modal payload and debug logging retained AOAI management metadata for Foundry endpoints.
- **Version Implemented:** 0.236.029

## Fixed/Implemented in version: **0.236.029**

## Technical Details
- **Files Modified:**
  - application/single_app/static/js/admin/admin_model_endpoints.js
  - application/single_app/route_backend_models.py
  - functional_tests/test_foundry_management_fields_cleanup.py
  - application/single_app/config.py
- **Code Changes Summary:**
  - Removed location field usage from the endpoint modal script.
  - Ensured management metadata is only included for Azure OpenAI payloads.
  - Cleaned backend debug logging to remove location references.
  - Added a functional test for Foundry management field cleanup.
  - Incremented the application version to 0.236.029.
- **Testing Approach:**
  - Functional test validates the modal payload uses management fields only for AOAI.
- **Impact Analysis:**
  - Foundry endpoint configuration is now project-only without AOAI management metadata.

## Validation
- **Test Results:** Functional test added (see functional_tests/test_foundry_management_fields_cleanup.py).
- **Before/After Comparison:**
  - **Before:** Foundry payload carried AOAI management fields and location debug logs.
  - **After:** Foundry payload excludes management fields and location is removed.
- **User Experience Improvements:**
  - Admins no longer see or save unnecessary management fields for Foundry endpoints.

## References
- Config version updated in application/single_app/config.py to 0.236.029.
