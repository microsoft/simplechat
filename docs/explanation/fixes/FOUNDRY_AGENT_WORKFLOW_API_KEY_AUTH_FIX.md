# Foundry Agent and Workflow API-Key Auth Fix

Fixed/Implemented in version: **0.241.188**

## Issue Description

Saved Azure AI Foundry model endpoints already supported API-key authentication for OpenAI-compatible GPT model calls, but Foundry agents and workflows always used delegated user access. Users with a Foundry project key could expose GPT models from that project, but could not use the same saved project connection to fetch or run Foundry applications and workflows.

## Root Cause Analysis

The Foundry agent/workflow runtime treated every non-managed-identity or non-service-principal configuration as delegated user authentication. Discovery and invocation paths built bearer-token headers directly, and endpoint hydration did not propagate API-key auth from saved model endpoint connections into new Foundry application or workflow settings.

## Version Implemented

- Application version updated in `application/single_app/config.py` from `0.241.187` to `0.241.188`.

## Technical Details

### Files Modified

- `application/single_app/foundry_agent_runtime.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/static/js/agent_modal_stepper.js`
- `application/single_app/config.py`
- `functional_tests/test_foundry_delegated_user_auth.py`

### Code Changes Summary

- Added API-key credential handling for OpenAI-compatible Foundry REST calls.
- Reused the shared REST header builder for new Foundry application invocation, streaming, workflow streaming, and application discovery.
- Propagated saved model endpoint API-key auth into new Foundry application and workflow settings during server-side endpoint hydration.
- Updated agent creation payloads to save `authentication_type: "api_key"` for new Foundry applications and workflows when the selected saved endpoint uses API-key auth, without storing the key in agent settings.
- Kept classic SDK-based Foundry agents on delegated/token-based authentication because the current Azure AI Projects SDK path expects an async token credential.

### Testing Approach

- Extended the Foundry delegated-auth functional regression test to verify API-key auth resolution, REST header construction, endpoint hydration, backend discovery settings, modal payload behavior, and version documentation traceability.

## Impact Analysis

Users can now use a saved API-key-backed Foundry project connection for OpenAI-compatible Foundry applications and workflows, matching the existing key-based model endpoint capability. Delegated user auth remains the default and classic Foundry agent SDK behavior remains token-based.

## Validation

Run:

```bash
python functional_tests/test_foundry_delegated_user_auth.py
node --check application/single_app/static/js/agent_modal_stepper.js
python -m py_compile application/single_app/foundry_agent_runtime.py application/single_app/semantic_kernel_loader.py application/single_app/route_backend_models.py functional_tests/test_foundry_delegated_user_auth.py
```
