# Foundry Model List Endpoint Fallback Fix (v0.236.024)

## Issue Description
Model discovery for Azure AI Foundry returned a 400 error against `/openai/v1/models` for certain Foundry endpoints.

## Root Cause Analysis
Some Foundry endpoints expect the Azure OpenAI data-plane path `/openai/models` rather than `/openai/v1/models`.

## Version Implemented
Fixed/Implemented in version: **0.236.024**

## Technical Details
### Files Modified
- application/single_app/route_backend_models.py
- application/single_app/config.py

### Code Changes Summary
- Attempt `/openai/models` first, fall back to `/openai/v1/models`.
- Added debug output for the attempted URLs.
- Incremented the application version.

### Testing Approach
- Added a functional test to validate the fallback order.

### Impact Analysis
- Reduces 400 errors when listing models from Foundry endpoints.

## Validation
- Functional test: functional_tests/test_foundry_model_list_fallback.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.024**.
