# Schema-v2 Agent Model Routing Fix

Fixed/Implemented in version: **0.261.060**

## Issue

Local Semantic Kernel agents bound to schema-v2 custom model endpoints failed
during initialization before sending a request to the configured gateway. The
agent loader attempted to read the endpoint with legacy routing helpers and did
not retain the selected model's resolved operation URL.

## Root cause

Direct model chat already resolved model-specific API paths, APIM revision
selectors, protocols, and authentication headers. The agent loader flattened
the selected endpoint into legacy endpoint, deployment, and API-version fields,
so the route-aware Semantic Kernel service builder did not receive the resolved
schema-v2 endpoint.

## Technical details

- The agent binding now opts into model-specific routing for schema-v2 records.
- The resolved route is retained in the in-memory agent configuration.
- The existing Semantic Kernel service builder receives the resolved endpoint
  instead of reconstructing an incomplete legacy client.
- Automatic tool invocation is omitted when the resolved route does not
  advertise tool-calling support, so text-only agents do not send an unsupported
  `tools` payload.
- Streaming preflight accepts an explicit schema-v2 model only when it matches
  the caller-accessible stored agent's endpoint and model binding.
- Legacy endpoint-bound agents continue through the existing service paths.

## Validation

Focused functional coverage verifies OpenAI-compatible and Anthropic bindings,
APIM revision path retention, custom authentication-header retention, resolved
service construction, and rejection of model selections that do not match the
stored agent binding.

The application version was updated in `config.py` to `0.261.060`.
