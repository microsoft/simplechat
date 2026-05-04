# Chat Inline Export Action Persistence Fix

## Header Information

Version implemented: **0.241.108**

Issue description:

Inline assistant export buttons were visible when the response first arrived, but they disappeared after leaving the conversation and returning later.

Root cause analysis:

The inline action renderer only created the buttons when `appendMessage(...)` was called with `isNewMessage = true`. Conversation history always reloads with `isNewMessage = false`, so the same assistant reply lost its inline actions even when the immediately preceding user request still clearly asked for Word, PowerPoint, Markdown, or email output.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.108"`.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `ui_tests/test_chat_inline_export_action_buttons.py`

Code changes summary:

- Replaced the strict `isNewMessage` gate with a check against the most recently rendered chat message.
- Inline export buttons now render for assistant replies when they directly follow a qualifying user prompt, even during history reload.
- Kept the progress-label behavior for inline actions so reload persistence and in-progress button text share the same listener path.

Testing approach:

- Updated the focused Playwright regression to cover a history-loaded assistant reply with `isNewMessage = false`.
- Re-ran JavaScript syntax validation for `chat-messages.js`.

## Validation

Before:

- A qualifying assistant response showed inline export buttons only on first render.
- Returning to the same conversation removed the inline export actions because history messages never met the `isNewMessage` condition.

After:

- Returning to a conversation preserves inline export buttons for assistant replies that still directly follow a qualifying user request.
- Non-qualifying assistant replies still stay clean and do not gain inline export actions.

Related UI tests:

- `ui_tests/test_chat_inline_export_action_buttons.py`