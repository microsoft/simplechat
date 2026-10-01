# Chat Message Markdown Sanitizer Guard Fix (v0.261.047)

Fixed and implemented in version: **0.261.047**

## Issue Description

Some chat message rendering paths assumed the global `DOMPurify` and `marked` browser objects were always available. If either local asset had not loaded when a user sent a message, `appendMessage()` could throw `ReferenceError: DOMPurify is not defined` and interrupt the send flow.

## Root Cause Analysis

The chat page loads local Markdown and sanitizer assets from `base.html`, but `chat-messages.js` used those globals directly in multiple message rendering paths. Other chat modules already guarded this dependency. The user and collaborator message branches did not, so a missing global became a runtime crash instead of a safe escaped-text fallback.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-messages.js`
- `functional_tests/test_chat_message_markdown_sanitizer_guard.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added guarded Markdown rendering helpers in `chat-messages.js`.
- Preserved sanitized Markdown rendering when `DOMPurify` and `marked` are available.
- Added escaped-text fallbacks when either global is unavailable.
- Replaced direct `DOMPurify.sanitize(...)` and `marked.parse(...)` calls in chat message rendering paths.

### Testing Approach

- Added a functional static regression that checks the guarded helpers exist and direct sanitizer/parser calls are not reintroduced in `chat-messages.js`.
- Ran JavaScript syntax checks for the changed chat modules.

## Validation

### Test Results

- `node --check application/single_app/static/js/chat/chat-messages.js`

### Before And After

- Before: sending a message could fail if `DOMPurify` was unavailable at render time.
- After: chat rendering uses sanitized Markdown when the local libraries are present and safely falls back to escaped text when they are not.

### User Experience Improvements

- Sending a chat message no longer fails because of a missing sanitizer global.
- The fallback keeps message text visible without widening the browser rendering trust boundary.