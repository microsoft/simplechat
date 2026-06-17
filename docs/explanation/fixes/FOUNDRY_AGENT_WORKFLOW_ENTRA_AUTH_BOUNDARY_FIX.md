# Foundry Agent and Workflow Entra Auth Boundary Fix

Fixed/Implemented in version: **0.241.196**

## Issue Description

Foundry application agents and Foundry Workflow agents could inherit API-key authentication from saved model endpoints or manual agent settings. That made SimpleChat attempt API-key invocation for Foundry agents/workflows even though current Foundry agent and Agent Application invocation paths require Microsoft Entra ID/RBAC.

## Root Cause Analysis

SimpleChat blurred two different authentication surfaces: API-key model endpoint inference and Foundry agent/workflow invocation. Saved `new_foundry` and `foundry_workflow` model endpoints with `auth.type = api_key` were promoted into chat-selectable agent runtime settings, and the modal exposed a manual Foundry Project API Key field. The workflow runtime also had a fallback that routed API-key workflow configurations through the application protocol.

## Technical Details

### Files Modified

- `application/single_app/foundry_agent_runtime.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/functions_agent_payload.py`
- `application/single_app/functions_keyvault.py`
- `application/single_app/static/js/agent_modal_stepper.js`
- `application/single_app/templates/_agent_modal.html`
- `application/single_app/config.py`
- `functional_tests/test_foundry_delegated_user_auth.py`
- `functional_tests/test_foundry_workflow_agent_payload.py`
- `ui_tests/test_agent_modal_foundry_workflow.py`

### Code Changes Summary

- Restricted Foundry agent and workflow invocation to Microsoft Entra ID/RBAC auth.
- Preserved API-key support for model endpoint inference through the model endpoint client path.
- Stopped saved API-key model endpoint auth from being promoted into New Foundry or Foundry Workflow agent runtime settings.
- Removed the manual Foundry Project API Key field from the agent modal.
- Stripped `api_key` and `key` from Foundry agent and workflow payloads before storage.
- Removed agent-level Key Vault registration for New Foundry and Foundry Workflow API keys.
- Removed the workflow API-key application-protocol fallback.

## Validation

Run:

```bash
python functional_tests/test_foundry_delegated_user_auth.py
python functional_tests/test_foundry_workflow_agent_payload.py
python -m pytest ui_tests/test_agent_modal_foundry_workflow.py
node --check application/single_app/static/js/agent_modal_stepper.js
python -m py_compile application/single_app/foundry_agent_runtime.py application/single_app/semantic_kernel_loader.py application/single_app/route_backend_models.py application/single_app/functions_agent_payload.py application/single_app/functions_keyvault.py functional_tests/test_foundry_delegated_user_auth.py functional_tests/test_foundry_workflow_agent_payload.py
```

## Impact Analysis

Users can continue using API-key saved model endpoints for normal model inference. Chat-selectable Foundry agents and workflows now require signed-in user, managed identity, or service principal access with the appropriate Foundry RBAC permissions. In commercial Foundry, use the renamed role names such as `Foundry User`; in Azure Government and custom clouds, use the equivalent role name shown in the portal, which may still be `Azure AI User`. Web Search configuration remains isolated and unchanged.