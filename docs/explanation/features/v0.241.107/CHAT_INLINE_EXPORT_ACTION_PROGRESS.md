# Chat Inline Export Action Progress Labels

## Overview

Version: 0.241.107

Implemented in version: **0.241.107**

Inline chat export actions now update their button text while the requested action is in progress. Create-style actions switch to a matching `Creating ...` label until the download is ready, and the email shortcut switches to `Opening Email Draft...` so the UI reflects that it opens a draft instead of silently sending mail.

Dependencies:

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/js/chat/chat-message-export.js`
- `ui_tests/test_chat_inline_export_action_buttons.py`

## Technical Specifications

### Architecture Overview

- The shared message export listener now applies a pending state only to the inline assistant export buttons.
- Pending buttons are temporarily disabled, show a spinner, and restore their original label when the existing export or email handler completes.
- The behavior reuses the existing export/email implementation instead of duplicating download or mail-draft logic.

### File Structure

- `application/single_app/static/js/chat/chat-messages.js`
- `ui_tests/test_chat_inline_export_action_buttons.py`

## Usage Instructions

1. Ask the assistant to create a supported export such as a PowerPoint, Word document, Markdown document, or email.
2. Click the inline action inside the new assistant reply.
3. Watch the button update to a matching in-progress label until the download or email-draft handoff begins.

## Testing And Validation

UI coverage:

- `ui_tests/test_chat_inline_export_action_buttons.py`

Known limitations:

- Progress labels are intentionally limited to the inline assistant buttons and do not alter the three-dots dropdown labels.