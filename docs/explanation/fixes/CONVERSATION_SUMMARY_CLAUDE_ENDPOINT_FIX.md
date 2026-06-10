# Conversation Summary Claude Endpoint Fix

Fixed/Implemented in version: **0.241.182**

## Issue Description

Conversation export summary intros and the Chat Details "Generate Summary" action could fail when the selected summary model was a Claude deployment from a configured Foundry or New Foundry model endpoint. The summary helper only created the legacy Azure OpenAI client, so Claude deployments were sent through the wrong API shape and could return `DeploymentNotFound` or API-version errors.

## Root Cause Analysis

Direct chat and endpoint tests had protocol-aware model endpoint resolution, but the shared summary generator still resolved only APIM or the default Azure OpenAI GPT configuration. The summary UI also sent only the deployment name, dropping the endpoint id, model id, and provider metadata already available on the chat model selector.

## Technical Details

Files modified:

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/route_backend_conversations.py`
- `application/single_app/static/js/chat/chat-export.js`
- `application/single_app/static/js/chat/chat-conversation-details.js`
- `application/single_app/config.py`
- `functional_tests/test_conversation_summary_model_endpoint_protocol.py`

Code changes summary:

- Added summary-specific model endpoint resolution that checks configured global, personal, and group endpoints before falling back to APIM or default Azure OpenAI settings.
- Routed Claude summary models through the Anthropic messages adapter and OpenAI-compatible Foundry models through the `/openai/v1` adapter.
- Preserved existing Azure OpenAI behavior for non-endpoint summary models.
- Passed endpoint id, model id, and provider metadata from export summary and Chat Details summary requests.
- Added regression coverage for explicit endpoint metadata and deployment-only Claude summary resolution.

## Validation

Test results:

- `python -m py_compile application/single_app/route_backend_conversation_export.py application/single_app/route_backend_conversations.py functional_tests/test_conversation_summary_model_endpoint_protocol.py`
- `node --check application/single_app/static/js/chat/chat-export.js`
- `node --check application/single_app/static/js/chat/chat-conversation-details.js`
- `python functional_tests/test_conversation_summary_model_endpoint_protocol.py`

Before this fix, Claude summary generation could be attempted against the configured Azure OpenAI endpoint even when the selected chat model came from a Claude-capable model endpoint. After this fix, export summaries and Chat Details summaries resolve the selected endpoint metadata and use the correct runtime protocol.

Version reference: `application/single_app/config.py` is at **0.241.182** for this fix.