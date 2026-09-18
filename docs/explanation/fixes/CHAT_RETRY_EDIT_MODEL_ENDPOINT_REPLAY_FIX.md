# Chat Retry and Edit Model Endpoint Replay Fix

Retrying a response or editing a prompt could fail before receiving content even though the original request succeeded. The replay request restored only the saved model name, so multi-endpoint models could be sent to the default Azure OpenAI resource instead of the endpoint that handled the original request.

Fixed/Implemented in version: **0.261.033**

Related config.py update: `VERSION = "0.261.033"`

## Root Cause

Initial chat sends include the request model, model ID, endpoint ID, and provider. Retry and edit preparation rebuilt `model_deployment` from `metadata.model_selection.selected_model` but discarded the other routing fields. Without `model_endpoint_id`, streaming model resolution could fall through to the default Azure OpenAI client and use a model identifier as an Azure deployment name, resulting in `DeploymentNotFound`.

## Technical Details

Files modified:

- `application/single_app/route_backend_conversations.py`
- `application/single_app/static/js/chat/chat-retry.js`
- `functional_tests/test_chat_retry_edit_model_endpoint_replay.py`
- `application/single_app/config.py`

The backend now rebuilds the complete model routing context from the original message metadata for retry and edit. The retry modal also sends the selected option's request model, model ID, endpoint ID, provider, and icon, matching the initial chat request contract. A retry that explicitly selects another model does not inherit stale endpoint metadata.

## Validation

Regression coverage verifies that:

- Edit restores the original request model and endpoint identity.
- Retrying the same model preserves the saved endpoint identity.
- Selecting a different model does not retain stale endpoint fields.
- The retry frontend sends the complete selected model identity.

The Python route compiles successfully and the retry JavaScript passes `node --check`.

## Impact

Retry and edit requests for multi-endpoint models are routed to the same configured endpoint as the original response, avoiding false Azure OpenAI `DeploymentNotFound` failures before streaming begins.