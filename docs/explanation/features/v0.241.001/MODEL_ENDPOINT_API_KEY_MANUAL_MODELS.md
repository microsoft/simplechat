# Model Endpoint API Key Manual Models (v0.250.172)

## Overview and Purpose
Adds manual model entry for API key-authenticated endpoints, with per-model connection tests and guidance to prefer identity-based discovery.

## Version Implemented
Fixed/Implemented in version: **0.236.019**

Updated in version: **0.250.172**

## Dependencies
- Admin model endpoint modal
- Backend model test endpoint
- Azure OpenAI / Foundry inference clients

## Technical Specifications
### Architecture Overview
- API key endpoints skip discovery and allow manual model entries.
- Each model row supports per-model connection testing.
- Service principal auth includes management cloud and custom authority inputs.
- The Custom provider uses API-key-only authentication and always uses manual model entry.
- Custom OpenAI API and Anthropic models use Model Name; Custom Azure OpenAI API models use Deployment Name.

### API Endpoints
- `/api/models/test-model` — tests a specific model deployment using the endpoint settings.

### Configuration Options
- `auth.management_cloud` — Public, Government, or Custom authority.
- `auth.custom_authority` — custom authority URL for service principal auth.

### File Structure
- Modal UI: application/single_app/templates/_multiendpoint_modal.html
- Modal logic: application/single_app/static/js/admin/admin_model_endpoints.js
- Workspace modal logic: application/single_app/static/js/workspace/workspace_model_endpoints.js
- Backend test endpoint: application/single_app/route_backend_models.py

## Usage Instructions
### API Key Flow
1. Choose Authentication Type: API Key.
2. Use Add Model to enter deployment name, display name, and description.
3. Use the per-model Test Connection button to verify access.

### Custom Provider Flow
1. Choose Provider: Custom.
2. Select OpenAI API, Azure OpenAI API, or Anthropic.
3. Enter the HTTPS endpoint and API key.
4. Add models manually using the type-specific Model Name or Deployment Name field.

### Service Principal Flow
1. Choose Authentication Type: Service Principal.
2. Select Management Cloud (Public/Government/Custom).
3. For Custom, enter the authority URL.

## Testing and Validation
- Functional test: functional_tests/test_model_endpoints_api_key_manual_models.py
- Functional test: functional_tests/test_custom_model_endpoint_provider.py

## Known Limitations
- API key auth supports inference only; discovery requires identity-based auth.
- Custom endpoints never use discovery.

## Reference to Config Version Update
- Initial version updated in application/single_app/config.py to **0.236.019**.
- Custom provider update in application/single_app/config.py: **0.250.172**.
