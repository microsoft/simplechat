# AOAI Model Discovery Empty List Fix (v0.236.015)

## Issue Description
Azure OpenAI endpoint discovery in the multi-endpoint modal returned a successful connection but always displayed zero models.

## Root Cause Analysis
The `/api/models/fetch` endpoint only handled Azure AI Foundry and returned an empty list for Azure OpenAI providers. The modal payload also lacked resource group support required to query deployments via ARM.

## Version Implemented
Fixed/Implemented in version: **0.236.015**

## Technical Details
### Files Modified
- application/single_app/templates/admin_settings.html
- application/single_app/static/js/admin/admin_model_endpoints.js
- application/single_app/route_backend_models.py
- application/single_app/config.py

### Code Changes Summary
- Added Resource Group input to the model endpoint modal for AOAI discovery.
- Required subscription + resource group for AOAI payloads.
- Implemented AOAI deployment listing via ARM in `/api/models/fetch` and `/api/models/test-connection`.
- Incremented the application version.

### Testing Approach
- Added a functional test to validate AOAI discovery wiring and resource group handling.

### Impact Analysis
- AOAI model fetch now returns deployments for the selected endpoint.
- Prevents misleading “success with zero models” results.

## Validation
- Functional test: functional_tests/test_model_endpoints_aoai_fetch_fix.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.015**.
