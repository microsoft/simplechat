# Inline Export Action Streaming Placeholder Fix

## Header Information

Fixed in version: **0.241.033**

Issue description:

Assistant responses that matched a create/export request showed inline actions such as `Create PowerPoint Presentation` on the temporary streaming placeholder. The button appeared before the final assistant message and generated artifacts existed, which made the action confusing and unusable during response generation.

Root cause analysis:

The inline export action renderer looked only at the latest user prompt intent. It did not distinguish temporary `temp_ai_...` streaming placeholders from completed assistant messages, so the placeholder inherited the same create/export buttons as the final response.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.033"`.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `ui_tests/test_chat_inline_export_action_buttons.py`

Code changes summary:

- Added detection for streaming assistant placeholder messages.
- Suppressed inline create/export action buttons while an assistant message is still streaming.
- Suppressed export-related overflow menu items on streaming placeholders.
- Preserved the completed-message behavior so the final assistant reply still shows the expected create/export buttons after streaming finishes.

Testing approach:

- Updated the chat inline export UI regression test to render a user request, a temporary streaming assistant placeholder, and a completed assistant response.
- Verified the placeholder does not expose inline or overflow export actions.
- Verified the completed response still exposes the expected PowerPoint action.

## Validation

Before:

- A temporary `Streaming...` assistant card could show `Create PowerPoint Presentation` before the final content or generated artifact was available.

After:

- Create/export controls appear only on the completed assistant response.
- The final response and generated artifact cards remain the place where users can download, view, add to workspace, or create PowerPoint output.

Related UI test:

- `ui_tests/test_chat_inline_export_action_buttons.py`