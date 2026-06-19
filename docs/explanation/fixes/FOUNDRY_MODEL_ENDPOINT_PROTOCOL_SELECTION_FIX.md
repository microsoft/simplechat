# Foundry Model Endpoint Protocol Selection Fix

Fixed in version: **0.241.179**

## Issue Description

New Foundry model endpoints could be configured with Claude deployments, but runtime chat and model connection tests still used the Azure OpenAI client shape with an `api-version` query. Claude deployments require the Anthropic messages protocol, so those calls failed with API version compatibility errors.

Editing an existing API-key-backed endpoint also required the API key field to be filled again, even when the key was already stored securely and the user was only changing model metadata such as name or description.

## Root Cause Analysis

The multi-endpoint runtime selected the client from the configured provider only. Foundry and New Foundry endpoints were treated as Azure OpenAI-compatible even when the deployment name or endpoint path indicated Anthropic. New Foundry `/openai/v1` endpoints also inherited legacy dated Azure API versions in cases where the v1 endpoint should not receive an `api-version` query string.

## Technical Details

Files modified:

- `application/single_app/model_endpoint_clients.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/templates/_multiendpoint_modal.html`
- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/static/js/workspace/workspace_model_endpoints.js`

Code changes summary:

- Added protocol inference for Azure OpenAI, OpenAI-compatible Foundry `/openai/v1`, and Anthropic messages endpoints.
- Routed Claude deployments and `/anthropic/` endpoints through an Anthropic messages adapter that preserves the existing `chat.completions.create` call shape.
- Routed endpoint-bound Semantic Kernel agents through protocol-aware chat services, including an Anthropic service for Claude-backed local agents.
- Normalized New Foundry Project endpoints to `/openai/v1` for OpenAI-compatible models and to `/anthropic/v1/messages` for Claude deployments.
- Preserved OpenAI-compatible `/openai/v1` endpoint behavior by omitting the `api-version` query for this normalized inference path. A later 0.250.003 follow-up confirmed that Foundry project `/v1` model endpoints reject `api-version`, including dated preview values.
- Updated the endpoint modal to use API-version dropdowns with Custom fields, rename Foundry endpoint input copy to Project Endpoint, and derive the project name from `/api/projects/<project>` URLs.
- Updated endpoint edit validation so blank API key and client secret fields can reuse stored secrets when the existing endpoint indicates the secret is already saved.

## Validation

Test results:

- `python -m py_compile application/single_app/model_endpoint_clients.py application/single_app/route_backend_chats.py application/single_app/route_backend_models.py functional_tests/test_new_foundry_endpoint_api_version_handling.py functional_tests/test_model_endpoint_protocol_inference.py ui_tests/test_model_endpoint_request_uses_endpoint_id.py`
- `node --check application/single_app/static/js/admin/admin_model_endpoints.js`
- `node --check application/single_app/static/js/workspace/workspace_model_endpoints.js`
- `python functional_tests/test_new_foundry_endpoint_api_version_handling.py`
- `python functional_tests/test_model_endpoint_protocol_inference.py`
- `python functional_tests/test_model_endpoints_key_vault_secret_storage.py`
- `pytest ui_tests/test_model_endpoint_request_uses_endpoint_id.py -q` (skipped without UI environment variables)

Before this fix, Claude deployments on New Foundry could fail because the request used an Azure OpenAI `api-version` flow, and endpoint metadata edits could incorrectly demand a previously stored API key. After this fix, Claude deployments are inferred from the deployment name or endpoint path and are called through the Anthropic messages protocol, including for endpoint-bound local agents. Saved endpoint edits can preserve stored secrets without requiring users to paste them again.

Version reference: `application/single_app/config.py` is at **0.241.179** for this original fix.

## Tabular Analysis Follow-Up

Fixed in version: **0.241.186**

### Issue Description

Tabular analysis and large generated tabular exports could still fail after selecting a Claude model endpoint because the tabular helper paths rebuilt Azure-only Semantic Kernel chat services instead of preserving the selected model endpoint context. Some chat-route helper calls also sent Anthropic-incompatible system-only message payloads.

### Root Cause Analysis

The main chat client had protocol-aware endpoint routing, but tabular mini-agents, background generated-output workers, and several summary or history helper calls still assumed Azure OpenAI request behavior. Claude Semantic Kernel services do not support the SK auto function-calling loop used by tabular analysis, so the tabular path also needed a Claude-specific direct planner flow.

### Technical Details

Files modified:

- `application/single_app/functions_model_endpoint_runtime.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/model_endpoint_clients.py`
- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_models.py`
- `application/single_app/config.py`

Code changes summary:

- Added a shared model endpoint runtime helper that builds provider-aware Semantic Kernel chat services and stores only non-secret endpoint context with background work.
- Threaded selected endpoint and model metadata into foreground tabular analysis, schema summary generation, generated output creation, and background generated-output processing.
- Added a Claude/Anthropic tabular branch that uses the existing JSON reviewer planner and direct server-side tool execution instead of SK auto function calling.
- Allowed literal `anthropic` and `claude` providers in endpoint inference, frontend-visible endpoint filtering, and model connection tests.
- Converted chat-route summary and history helper calls from system-only payloads to system-plus-user payloads for Anthropic compatibility.

### Validation

Test results:

- `python -m py_compile application/single_app/model_endpoint_clients.py application/single_app/functions_model_endpoint_runtime.py application/single_app/functions_tabular_generated_exports.py application/single_app/route_backend_models.py application/single_app/functions_settings.py application/single_app/route_backend_chats.py functional_tests/test_model_endpoint_protocol_inference.py functional_tests/test_tabular_background_generated_exports.py functional_tests/test_tabular_claude_model_endpoint_support.py`
- `python functional_tests/test_model_endpoint_protocol_inference.py`
- `python functional_tests/test_tabular_background_generated_exports.py`
- `python functional_tests/test_tabular_claude_model_endpoint_support.py`

Before this follow-up, Claude-backed tabular analysis and background exports could silently fall back to Azure-only service construction or hit Anthropic payload/tool-calling constraints. After this follow-up, selected Claude endpoint metadata is preserved through tabular work and Claude uses an Anthropic-safe planner path.

Version reference: `application/single_app/config.py` is at **0.241.186** for this follow-up.