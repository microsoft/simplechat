# Model Endpoint API Key Manual Models (v0.236.019)

## Overview and Purpose
Adds manual model entry for API key-authenticated endpoints, with per-model connection tests and guidance to prefer identity-based discovery.

## Version Implemented
Fixed/Implemented in version: **0.236.019**

## Dependencies
- Admin model endpoint modal
- Backend model test endpoint
- Azure OpenAI / Foundry inference clients

## Technical Specifications
### Architecture Overview
- API key endpoints skip discovery and allow manual model entries.
- Each model row supports per-model connection testing.
- Service principal auth includes management cloud and custom authority inputs.

### API Endpoints
- `/api/models/test-model` — tests a specific model deployment using the endpoint settings.

### Configuration Options
- `auth.management_cloud` — Public, Government, or Custom authority.
- `auth.custom_authority` — custom authority URL for service principal auth.

### File Structure
- Modal UI: application/single_app/templates/admin_settings.html
- Modal logic: application/single_app/static/js/admin/admin_model_endpoints.js
- Backend test endpoint: application/single_app/route_backend_models.py

## Usage Instructions
### API Key Flow
1. Choose Authentication Type: API Key.
2. Use Add Model to enter deployment name, display name, and description.
3. Use the per-model Test Connection button to verify access.

### Service Principal Flow
1. Choose Authentication Type: Service Principal.
2. Select Management Cloud (Public/Government/Custom).
3. For Custom, enter the authority URL.

## Testing and Validation
- Functional test: functional_tests/test_model_endpoints_api_key_manual_models.py

## Known Limitations
- API key auth supports inference only; discovery requires identity-based auth.

## Reference to Config Version Update
- Version updated in application/single_app/config.py to **0.236.019**.
