# Rendered Markdown Message Masking Fix

Fixed/Implemented in version: **0.250.029**

## Issue Description

Selected-text masking could fail with `Selection no longer matches the stored message content` when users selected text from rendered assistant responses, especially Markdown tables and bolded summary text.

## Root Cause Analysis

The browser calculated selection offsets from the rendered `.message-text` content, while the backend validated those offsets against the raw stored Markdown. Formatting characters such as `**` and Markdown table separators changed the visible text positions, so valid user selections were rejected.

## Technical Details

Files modified:

* `application/single_app/functions_message_masking.py`
* `application/single_app/static/js/chat/chat-messages.js`
* `application/single_app/config.py`
* `functional_tests/test_chat_layered_message_masking.py`
* `docs/explanation/features/MESSAGE_LAYERED_MASKING.md`

Code changes summary:

* Added a conservative Markdown-to-visible-text projection fallback for selection validation.
* Preserved canonical `start` and `end` offsets for model-history masking.
* Added optional `display_start`, `display_end`, and `display_text` range metadata for browser-side rendered highlighting.
* Updated the chat client to send display offsets and prefer them when wrapping masked ranges in the rendered DOM.

## Validation

Test coverage validates:

* Existing layered mask state transitions.
* Rendered bold Markdown selections mapping back to raw stored Markdown.
* Rendered Markdown table cell selections mapping back to canonical table source.
* Frontend payload and display-offset wrapping contract.

Before the fix, formatted rendered selections could be rejected with a 400 response. After the fix, selected rendered text is accepted when it maps uniquely to the stored message content, while ambiguous duplicate selections are still rejected.

Related version update: `application/single_app/config.py` was incremented to `0.250.029`.