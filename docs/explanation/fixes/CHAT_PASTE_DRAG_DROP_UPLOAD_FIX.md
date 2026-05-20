# Chat Paste and Drag-and-Drop Upload Fix

Fixed/Implemented in version: **0.241.056**

## Issue Description

Chat supported pasted clipboard images, but a later plain-text paste could still be interpreted as an image upload when the clipboard event contained stale nameless image data. Chat also lacked direct drag-and-drop upload support in the message input area.

## Root Cause Analysis

The chat paste handler treated any file-like clipboard item as an upload and prevented the browser's default paste behavior. Some clipboard sources can expose both text and stale nameless image data, so the handler needed to prefer real text paste unless the clipboard file has an explicit filename.

## Technical Details

Files modified:
- `application/single_app/static/js/chat/chat-input-actions.js`
- `application/single_app/templates/chats.html`
- `application/single_app/config.py`
- `functional_tests/test_chat_clipboard_paste_upload_support.py`
- `ui_tests/test_chat_clipboard_paste_upload_workflow.py`

Code changes summary:
- Added a plain-text guard for clipboard uploads so normal text paste is not blocked by stale nameless image files.
- Preserved paste uploads for nameless screenshots/images when no text is present and for named files copied from file managers.
- Added drag-and-drop file uploads on the chat input area using the same chat upload helper and user agreement flow.
- Added a lightweight drag-active visual state for the chat input.

Related version update: `application/single_app/config.py` was incremented from `0.241.055` to `0.241.056`.

## Validation

Testing approach:
- Functional coverage checks the shared upload helper, text-paste guard, drag-and-drop binding, and version marker.
- UI coverage simulates a pasted clipboard image, a subsequent text paste with stale image data, and a dropped text file upload.

Expected behavior after the fix:
- Pasted screenshots/images upload into the current chat.
- Pasted text remains text, even after a prior image paste.
- Dropped files upload into the current chat through the existing upload flow.