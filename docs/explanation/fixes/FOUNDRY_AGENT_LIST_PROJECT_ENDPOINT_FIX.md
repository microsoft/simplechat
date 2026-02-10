# Foundry Agent List Project Endpoint Fix (v0.236.048)

## Issue Description
Listing Azure AI Foundry agents returned a 404 Resource not found error for endpoints configured without the project path.

## Root Cause Analysis
Agent listing used the base endpoint and omitted the required `/api/projects/{project_name}` segment when a project name was configured.

## Version Implemented
Fixed/Implemented in version: **0.236.048**

## Technical Details
### Files Modified
- application/single_app/foundry_agent_runtime.py
- application/single_app/route_backend_models.py
- application/single_app/config.py
- functional_tests/test_foundry_agent_list_project_endpoint.py

### Code Changes Summary
- Added project name to Foundry settings.
- Appended `/api/projects/{project_name}` when missing.
- Incremented the application version.

### Testing Approach
- Functional test checks for project name wiring and endpoint normalization.

## Impact Analysis
- Foundry agent listing works for project-scoped endpoints.

## Validation
- Functional test: functional_tests/test_foundry_agent_list_project_endpoint.py

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.048**.
