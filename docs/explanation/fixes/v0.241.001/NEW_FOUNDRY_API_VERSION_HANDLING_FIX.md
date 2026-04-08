# NEW_FOUNDRY_API_VERSION_HANDLING_FIX.md

# New Foundry API Version Handling Fix

Fixed in version: **0.239.180**

## Issue

The New Foundry endpoint modal had already stopped defaulting the OpenAI API version to `2024-05-01-preview`, but existing New Foundry agents could still be loaded with that endpoint-level fallback value. This happened both in the edit modal and at runtime, even when the agent document in Cosmos already stored the correct `responses_api_version`.

## Root Cause

- The runtime loader merged endpoint connection settings over the saved New Foundry agent settings and treated the endpoint API version as authoritative.
- The agent modal re-applied endpoint defaults after loading the saved agent, which overwrote the stored `responses_api_version` in the form.
- New Foundry agents need endpoint metadata for discovery, but an explicitly saved agent `responses_api_version` must take precedence during edit and invocation.

## Files Modified

- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/static/js/agent_modal_stepper.js`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/templates/_multiendpoint_modal.html`
- `ui_tests/test_model_endpoint_request_uses_endpoint_id.py`
- `functional_tests/test_new_foundry_endpoint_api_version_handling.py`
- `application/single_app/config.py`

## Validation

- Functional coverage verifies New Foundry endpoints no longer receive the generic AOAI API-version default.
- Functional coverage verifies the fetch response can populate the Responses API version back into the agent modal when available.
- Functional coverage verifies existing New Foundry agents preserve their saved `responses_api_version` when the endpoint configuration contains a different fallback value.
- UI coverage now expects the endpoint modal to clear the OpenAI API version field when `new_foundry` is selected for a new endpoint.

## Impact

New New Foundry endpoint configurations no longer silently inherit `2024-05-01-preview`, and existing New Foundry agents now keep their saved Responses/OpenAI API version during both modal editing and runtime invocation. Endpoint configuration remains the default source for incomplete agents, but it no longer clobbers an agent-specific version that was already persisted correctly.