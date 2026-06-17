# Foundry Delegated User Auth Fix

Fixed/Implemented in version: **0.241.185**

## Issue Description

Foundry agents and workflows could work locally but fail after deployment to Azure App Service because the server-side runtime used the host identity. Local development resolved to the developer's Azure credentials, while App Service resolved to the app's managed identity. That made Foundry access app-wide unless the app identity had access, instead of enforcing each signed-in user's Foundry permissions.

## Root Cause Analysis

The Foundry runtime built credentials with Azure Identity defaults unless a service principal was configured. Saved Foundry model endpoint authentication also flowed into agent runtime settings, so model endpoint connectivity and Foundry agent/workflow authorization were coupled. The product requirement is different: model endpoint inference remains app/configured auth, but Foundry agents and workflows should use delegated signed-in user access.

## Version Implemented

- Application version updated in `application/single_app/config.py` from `0.241.184` to `0.241.185`.

## Technical Details

### Files Modified

- `application/single_app/foundry_agent_runtime.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/agent_modal_stepper.js`
- `application/single_app/templates/_agent_modal.html`
- `application/single_app/config.py`
- `functional_tests/test_foundry_delegated_user_auth.py`
- `ui_tests/test_agent_modal_foundry_workflow.py`
- `ui_tests/test_agent_modal_dual_foundry_modes.py`

### Code Changes Summary

- Added delegated user token support for Foundry agents and workflows using the existing MSAL token helper with the Azure AI Foundry scope.
- Made Foundry agent/workflow runtime auth default to `delegated_user`, while preserving explicit `managed_identity` and `service_principal` advanced modes.
- Prevented saved model endpoint managed identity or service principal settings from implicitly becoming Foundry agent/workflow runtime credentials.
- Updated Foundry discovery and chat streaming error contracts to return `auth_required`, `auth_url`, `consent_url`, and scope information when the user needs consent or sign-in.
- Updated the agent modal copy, saved payloads, and discovery error rendering to reflect signed-in user Foundry access.

### Testing Approach

- Added a functional regression test that verifies delegated auth defaults, endpoint auth separation, structured auth-required responses, and modal payload/link contracts.
- Updated UI coverage for the Foundry modal text and auth-required discovery link.

## Impact Analysis

Foundry agents and workflows now follow each signed-in user's Azure AI Foundry permissions by default. Users without Foundry access receive a sign-in or consent path instead of silently depending on the App Service identity. In commercial Foundry, grant the user `Foundry User` or another appropriate renamed Foundry role. In Azure Government and custom clouds, the equivalent role may still appear under its earlier Azure AI role name. Model endpoint inference remains separate and continues to use its configured endpoint authentication.

## Validation

Run:

```bash
python functional_tests/test_foundry_delegated_user_auth.py
node --check application/single_app/static/js/agent_modal_stepper.js
pytest ui_tests/test_agent_modal_foundry_workflow.py ui_tests/test_agent_modal_dual_foundry_modes.py -q
python -m py_compile application/single_app/foundry_agent_runtime.py application/single_app/semantic_kernel_loader.py application/single_app/route_backend_models.py application/single_app/route_backend_chats.py functional_tests/test_foundry_delegated_user_auth.py ui_tests/test_agent_modal_foundry_workflow.py ui_tests/test_agent_modal_dual_foundry_modes.py
```
