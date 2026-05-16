# Generated Analysis JSON Preview Wrap Fix

Fixed in version: **0.241.130**

## Issue Description

Generated analysis artifact cards could render JSON preview content as a single unwrapped line segment, which let long preview text extend past the chat card and outside the visible chat window.

## Root Cause

The generated analysis preview fallback and text preview helpers rendered JSON inside `pre` elements without overriding the browser default `white-space: pre`. That preserved line breaks, but it also prevented long lines from wrapping inside the available card width.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `ui_tests/test_chat_generated_tabular_output_card.py`

Code changes summary:

- Added a shared generated-analysis preview block formatter in `chat-messages.js`.
- Applied `white-space: pre-wrap`, `word-break: break-word`, and `overflow-wrap: anywhere` to generated JSON preview blocks so long lines stay inside the card.
- Added a UI regression test that injects an analysis JSON artifact with a very long preview token and asserts the preview block wraps instead of overflowing.
- Bumped the application version to `0.241.130`.

Testing approach:

- `node --check application/single_app/static/js/chat/chat-messages.js`
- `e:/repos/simplechat/.venv/Scripts/python.exe -m py_compile application/single_app/config.py ui_tests/test_chat_generated_tabular_output_card.py`
- `e:/repos/simplechat/.venv/Scripts/python.exe -m pytest ui_tests/test_chat_generated_tabular_output_card.py -q`

## Validation

Before:

- Long JSON preview lines could overflow the generated artifact card in Chats.
- Document analysis previews were difficult to read because the preview block preferred horizontal overflow over wrapping.

After:

- Generated JSON preview blocks wrap long lines within the chat card.
- The UI regression suite now includes a targeted long-line preview scenario for this rendering path.