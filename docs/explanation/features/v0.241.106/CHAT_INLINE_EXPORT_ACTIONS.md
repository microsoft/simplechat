# Chat Inline Export Actions

## Overview

Version: 0.241.106

Implemented in version: **0.241.106**

Chat assistant replies can now surface inline export buttons directly inside the message bubble when the latest user prompt explicitly asks for a supported output format. The quick actions reuse the existing per-message export flows, so Word, PowerPoint, Markdown, and email drafts are still only generated when the user clicks the button.

Dependencies:

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-message-export.js`
- `ui_tests/test_chat_inline_export_action_buttons.py`

## Technical Specifications

### Architecture Overview

- The chat renderer inspects the latest user message already present in the chat DOM when a new assistant message is appended.
- Inline action buttons are shown only for fresh assistant replies and only when the prompt contains a supported export intent such as presentation, Word, Markdown, or email.
- Generic `presentation` requests surface both Word and PowerPoint shortcuts, while explicit Markdown and email requests show their matching buttons.
- Button clicks reuse the existing shared per-message export handlers instead of adding a second export implementation path.

### File Structure

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-message-export.js`
- `ui_tests/test_chat_inline_export_action_buttons.py`

## Usage Instructions

1. Ask the assistant to create a supported artifact such as a presentation, Word document, Markdown document, or email.
2. Wait for the assistant reply to appear.
3. Click the inline action inside that reply to trigger the existing export or email workflow.

## Testing And Validation

Test coverage:

- `ui_tests/test_chat_inline_export_action_buttons.py`

Known limitations:

- The quick actions rely on keyword intent detection from the latest visible user message, so very indirect phrasing may continue to fall back to the existing three-dots menu.
- Inline buttons are intentionally limited to new assistant replies so older messages do not change retroactively when the page reloads.