# New Foundry Provider API Version Guidance Fix

Fixed in version: **0.250.006**

## Issue Description

Admins configuring New Foundry project endpoints for non-OpenAI model providers could reasonably try a dated preview **OpenAI API Version** because the setup guide and in-product model endpoint modal did not clearly distinguish Foundry project discovery versions from the normalized `/openai/v1` inference path. Field testing with Grok, Meta/Llama, and DeepSeek showed that the `/v1` path rejects `api-version` query values.

## Root Cause Analysis

Simple Chat correctly stores Foundry **Project API Version** separately from **OpenAI API Version**, but the guidance did not clearly explain the difference. The OpenAI-compatible Foundry runtime normalizes project endpoints to `/openai/v1`, where the service expects endpoint-default version behavior and rejects an `api-version` query parameter.

## Technical Details

Files modified:

- `application/single_app/static/js/admin/admin_model_endpoints.js`
- `application/single_app/static/js/workspace/workspace_model_endpoints.js`
- `application/single_app/model_endpoint_clients.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/templates/_multiendpoint_modal.html`
- `scripts/openai_style_agent_harness.py`
- `application/single_app/config.py`
- `docs/how-to/model_endpoint_identity_setup.md`
- `functional_tests/test_new_foundry_endpoint_api_version_handling.py`
- `ui_tests/test_model_endpoint_request_uses_endpoint_id.py`

Code changes summary:

- Kept the New Foundry OpenAI API version default at endpoint default `v1` in both global and workspace endpoint editors after field testing showed Foundry project `/openai/v1` rejects `api-version` query parameters.
- Updated OpenAI-compatible Foundry runtime calls so configured dated preview values are not sent as `api-version` query values on the normalized `/openai/v1` inference path.
- Added a non-streaming retry when a provider completes a streaming chat response without emitting assistant text, preventing a blank assistant message when the fallback call can recover content.
- Limited `reasoning_effort` to known OpenAI reasoning model families after live probes showed Foundry-hosted non-OpenAI model families can fail or return empty content when this model-specific parameter is sent.
- Folded saved memory values into the latest user message as plain background notes for Foundry-hosted non-OpenAI chat-completions models after live app tests showed memory system messages can trigger provider-side content-filter blocks.
- Consolidated sync model endpoint client construction behind `build_model_endpoint_sync_chat_client()` so chat, workflows, and metadata extraction share the same provider/auth/protocol behavior. Existing Semantic Kernel consumers continue through `build_semantic_kernel_chat_service_for_model()`.
- Updated stream lifecycle counters so app thought events no longer count as assistant content events.
- Added modal guidance explaining that Foundry **Project API Version** controls discovery and usually stays `v1`, while **OpenAI API Version** controls model inference.
- Added setup guide guidance for Grok, Meta/Llama, DeepSeek, and other provider families that hit `/v1` API-version query errors.
- Clarified that API-key endpoints are inference-only and require manual deployment rows when discovery is unavailable.
- Updated tests that previously locked in the old `v1` New Foundry default.

## Validation

Validation should include:

- JavaScript syntax checks for global and workspace endpoint editors.
- Functional regression coverage for the New Foundry API version default, `/v1` query omission behavior, and setup copy.
- Optional authenticated Playwright UI coverage for the Admin Settings endpoint modal.

Before this fix, users could follow unclear UI and docs guidance and choose incompatible API-version values for non-OpenAI New Foundry models. The runtime could also silently save a blank assistant message if a provider completed a stream without normal assistant text. After this fix, the default and guidance keep Foundry project inference on endpoint default `v1`, the runtime omits invalid `api-version` query values for `/openai/v1`, and empty provider streams retry once without streaming before surfacing a clear endpoint-compatibility error.

Version reference: `application/single_app/config.py` is at **0.250.006** for this fix.