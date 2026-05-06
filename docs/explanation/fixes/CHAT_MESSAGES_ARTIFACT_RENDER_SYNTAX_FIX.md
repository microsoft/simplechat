# Chat Messages Artifact Render Syntax Fix

Fixed in version: **0.241.129**

## Issue Description

Opening Chats could fail during page load with a JavaScript parse error in `chat-messages.js`, which prevented the chat message module from initializing.

## Root Cause

Generated artifact helper functions were accidentally inserted inside the `carouselButtonsHtml` template literal inside `appendMessage(...)`. That broke the surrounding footer assembly, cut off the citation setup, and left the browser parser reading stray `Generated ...` template text as code.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `ui_tests/test_chat_generated_tabular_output_card.py`

Code changes summary:

- Restored the AI message footer template so the carousel buttons, action buttons, and citation HTML are assembled as valid JavaScript again.
- Moved the generated analysis artifact hydration helpers back to function scope.
- Switched AI message rendering to hydrate all generated analysis artifacts instead of only the legacy tabular subset.
- Tightened the existing chat artifact UI regression test so page-level JavaScript errors fail the scenario.

Testing approach:

- `node --check application/single_app/static/js/chat/chat-messages.js`
- `pytest ui_tests/test_chat_generated_tabular_output_card.py`

## Validation

Before:

- Visiting Chats raised `Uncaught SyntaxError: Unexpected identifier 'Generated'` from `chat-messages.js`.
- Chat message rendering could stop before footer actions and generated artifact cards initialized.

After:

- `chat-messages.js` parses cleanly.
- Chats can initialize the AI message renderer again.
- The generated artifact card regression test now also guards against page parse errors.
