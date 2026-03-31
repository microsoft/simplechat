# Streaming Model Resolution Fix (v0.239.200)

Fixed/Implemented in version: **0.239.200**

## Issue Description

Streaming chat requests could successfully test a model endpoint in admin or workspace settings and still fail with `DeploymentNotFound` during `/api/chat/stream` execution.

## Root Cause Analysis

The streaming route accepted `model_id`, `model_endpoint_id`, and `model_provider` from the chat UI, but the runtime initialization path ignored those fields. It fell back to legacy global or APIM settings and treated `model_deployment` as the deployment name, which sent requests to the wrong endpoint for multi-endpoint Azure OpenAI and Foundry selections.

## Technical Details

Files modified:
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_agent_gpt_init_skips_multiendpoint.py`
- `functional_tests/test_default_model_selection_fallback.py`
- `functional_tests/test_streaming_multi_endpoint_resolution.py`

Code changes summary:
- Added streaming-specific helpers to resolve model endpoints by `model_endpoint_id` and `model_id`.
- Hydrated endpoint secrets through `keyvault_model_endpoint_get_helper()` before building inference clients.
- Added provider-aware client creation for Azure OpenAI and Foundry-backed streaming requests.
- Wired agent-triggered streaming requests to use `default_model_selection` when explicit model fields are absent.
- Preserved legacy global/APIM fallback only when multi-endpoint routing is not active.

Testing approach:
- Updated existing functional tests covering agent streaming fallback and default model selection wiring.
- Added a focused regression test for streaming multi-endpoint model resolution.

Impact analysis:
- Prevents streaming requests from falling through to the wrong endpoint when a scoped model is selected.
- Keeps streaming behavior aligned with the chat model catalog emitted to the frontend.
- Improves diagnostics with safe stream-time resolution logging for endpoint and model identifiers.

## Validation

Before:
- `/api/chat/stream` could ignore the selected endpoint/model metadata and send the request to the legacy global endpoint.
- Foundry and scoped Azure OpenAI models could test successfully but fail at stream time with 404 deployment errors.

After:
- `/api/chat/stream` resolves explicit model selections from saved endpoint metadata before any legacy fallback.
- Agent streaming requests without explicit model fields can use the saved default multi-endpoint selection.
- Stream initialization uses provider-aware endpoint, auth, deployment, and API-version values.

## Config Version Reference

`config.py` updated to `VERSION = "0.239.200"`.