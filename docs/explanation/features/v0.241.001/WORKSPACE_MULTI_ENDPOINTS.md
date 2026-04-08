# WORKSPACE MULTI ENDPOINTS (Version 0.236.045)

## Overview
Workspace multi-endpoint management extends the admin multi-endpoint system to personal and group workspaces. Users can configure workspace endpoints that live alongside global endpoints, and agent model selection is driven by these combined lists.

**Implemented in version: 0.236.045**

## Dependencies
- Global model endpoints configured in admin settings
- Workspace endpoint storage in user settings and group documents
- Agent modal updates for multi-endpoint and Foundry agent discovery

## Technical Specifications
### Architecture Overview
- Global endpoints remain in application settings.
- Personal endpoints are stored in user settings under `personal_model_endpoints`.
- Group endpoints are stored on group documents under `model_endpoints`.
- Agent modal requests a combined, sanitized endpoint list for model selection.
- Foundry agent lookup uses endpoint IDs to resolve authentication and list agents.

### API Endpoints
- `GET /api/user/model-endpoints` / `POST /api/user/model-endpoints`
- `GET /api/group/model-endpoints` / `POST /api/group/model-endpoints`
- `GET /api/user/agent/settings`
- `GET /api/group/agent/settings`
- `POST /api/models/foundry/agents`
- `POST /api/user/models/fetch` / `POST /api/user/models/test-model`
- `POST /api/group/models/fetch` / `POST /api/group/models/test-model`

### Configuration
- Global toggle: `enable_multi_model_endpoints` in [application/single_app/config.py](application/single_app/config.py)
- Workspace endpoints stored per user and per group

### File Structure
- Frontend templates: [application/single_app/templates/workspace.html](application/single_app/templates/workspace.html), [application/single_app/templates/group_workspaces.html](application/single_app/templates/group_workspaces.html), [application/single_app/templates/_agent_modal.html](application/single_app/templates/_agent_modal.html)
- Frontend logic: [application/single_app/static/js/workspace/workspace_model_endpoints.js](application/single_app/static/js/workspace/workspace_model_endpoints.js), [application/single_app/static/js/agent_modal_stepper.js](application/single_app/static/js/agent_modal_stepper.js)
- Backend: [application/single_app/route_backend_models.py](application/single_app/route_backend_models.py), [application/single_app/route_backend_agents.py](application/single_app/route_backend_agents.py), [application/single_app/semantic_kernel_loader.py](application/single_app/semantic_kernel_loader.py)

## Usage Instructions
### Enable/Configure
1. Admin enables multi-endpoint model management in admin settings.
2. Users open Personal Workspace or Group Workspace and add endpoints under the new Workspace/Group Model Endpoints card.
3. In the agent modal, select a model from the combined endpoint list.

### Foundry Agent Import
1. Select an Azure AI Foundry endpoint in the Foundry section of the agent modal.
2. Click **Fetch Agents** to list available agents.
3. Select an agent to import its identity, then save.

### User Workflows
- Personal agents can select models from global + personal endpoints.
- Group agents can select models from global + group endpoints.
- Foundry agents auto-populate identities from the selected Foundry endpoint.

## Testing and Validation
- Functional test: [functional_tests/test_workspace_multi_endpoints.py](functional_tests/test_workspace_multi_endpoints.py)
- Manual validation:
  - Add workspace endpoints and ensure they appear in agent model dropdowns.
  - Verify Foundry agent list import using configured endpoints.

## Performance Considerations
- Model discovery uses on-demand API calls to Azure/Foundry endpoints.

## Known Limitations
- Workspace endpoints require configured credentials; only stored secrets are used for runtime resolution.
