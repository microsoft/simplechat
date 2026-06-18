# Chat Model Icon Avatar Fix

Fixed in version: **0.242.071**

## Issue Description

Model endpoint icons uploaded or selected in Admin Settings were saved with endpoint model rows, but model-only chat responses still showed the default AI avatar on the chat page. After adding model avatar support, agent responses that did not carry an `agent_icon` payload could fall through to the selected model icon even though an agent identity was present.

## Root Cause Analysis

The multi-endpoint catalog and chat model selector already carried model icon payloads, but assistant message metadata did not persist the resolved model icon. The chat avatar renderer only checked `agent_icon` metadata before falling back to `/static/images/ai-avatar.png`, so saved model icons were not used for normal model responses.

The follow-up regression happened because model-icon fallback looked only for a missing valid agent icon. Some agent response paths can include `agent_display_name` or `agent_name` while omitting `agent_icon`, so the renderer needed to treat agent identity as enough to block model-icon fallback.

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
- Updated chat assistant avatar rendering to prefer agent icons, then model icons only for model-only responses, then the default AI avatar.
- Added an agent-identity guard so agent responses do not use model icons when `agent_display_name`, `agent_name`, or agent selection metadata is present.
- Added a fallback lookup from `window.chatModelOptions` so older model-only messages can render a model icon when the saved message has enough model/deployment metadata.
- Added regression coverage for backend metadata propagation, frontend model avatar rendering, and agent-priority behavior.

## Validation

Validation includes:

- Python compile checks for the changed backend route and tests.
- `node --check application/single_app/static/js/chat/chat-messages.js`.
- `functional_tests/test_chat_model_icon_avatar.py`.
- Skip-safe Playwright coverage in `ui_tests/test_chat_model_icon_avatar.py`.
- Existing XSS guardrail functional test.
- Repository whitespace diff check.

## Impact Analysis

Model-only assistant bubbles can now show the configured model icon or uploaded model image. Agent bubbles continue to prefer configured agent icons, and agent responses without an icon fall back to the normal assistant avatar instead of being overwritten by the model icon. Legacy model-only messages without persisted model icon metadata can still render icons when the current chat model catalog can match the saved deployment metadata.

## Related Version Updates

- `application/single_app/config.py` updated to `0.242.071`.