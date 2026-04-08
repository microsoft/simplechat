# Foundry Deployment Disabled Filter Fix (v0.236.025)

## Issue Description
Model discovery included deployments that were disabled, causing unavailable models to appear in the UI.

## Root Cause Analysis
The deployment list responses were not filtered by provisioning state.

## Version Implemented
Fixed/Implemented in version: **0.236.025**

## Technical Details
### Files Modified
- application/single_app/route_backend_models.py
- application/single_app/static/js/admin/admin_model_endpoints.js
- application/single_app/config.py

### Code Changes Summary
- Added deployment provisioning state filtering (exclude non-succeeded deployments).
- Switched Foundry management discovery to deployments list.
- Updated Foundry validation to require resource group.
- Incremented the application version.

### Testing Approach
- Added a functional test for deployment state filtering.

### Impact Analysis
- Prevents disabled deployments from appearing in model selection.

## Validation
- Functional test: functional_tests/test_foundry_deployment_disabled_filter.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.025**.
