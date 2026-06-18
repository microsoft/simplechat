# Chat Model Icon Avatar Fix

Fixed in version: **0.242.070**

## Issue Description

Model endpoint icons uploaded or selected in Admin Settings were saved with the endpoint model rows, but model-only chat responses still showed the default AI avatar on the chat page. Agent responses could show their configured agent icons because assistant message rendering already consumed `agent_icon` metadata.

## Root Cause Analysis

The multi-endpoint catalog and chat model selector already carried model icon payloads, but assistant message metadata did not persist the resolved model icon. The chat avatar renderer only checked `agent_icon` metadata before falling back to `/static/images/ai-avatar.png`, so saved model icons were not used for normal model responses.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_model_icon_avatar.py`
- `ui_tests/test_chat_model_icon_avatar.py`

### Code Changes Summary

- Normalized the saved model endpoint icon from the resolved endpoint model configuration.
- Added `model_icon` to model selection metadata, assistant message documents, streaming cancellation events, and final streaming/non-streaming response payloads.
- Updated chat assistant avatar rendering to prefer agent icons, then model icons, then the default AI avatar.
- Added a fallback lookup from `window.chatModelOptions` so older messages can render a model icon when the saved message has enough model/deployment metadata.
- Added regression coverage for backend metadata propagation and frontend avatar rendering hooks.

## Validation

Validation includes:

- Python compile checks for the changed backend route and new tests.
- `node --check application/single_app/static/js/chat/chat-messages.js`.
- `functional_tests/test_chat_model_icon_avatar.py`.
- Skip-safe Playwright coverage in `ui_tests/test_chat_model_icon_avatar.py`.
- Existing XSS guardrail functional test.
- Repository whitespace diff check.

## Impact Analysis

Model-only assistant bubbles can now show the configured model icon or uploaded model image. Agent bubbles continue to prefer agent icons, preserving the existing agent branding behavior. Legacy messages without persisted model icon metadata can still render icons when the current chat model catalog can match the saved deployment metadata.

## Related Version Updates

- `application/single_app/config.py` updated to `0.242.070`.
