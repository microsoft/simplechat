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
- Ignored legacy dated Azure API versions for OpenAI-compatible `/openai/v1` requests unless the user selects `preview` or `latest`.
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

Version reference: `application/single_app/config.py` is at **0.241.179** for this fix.