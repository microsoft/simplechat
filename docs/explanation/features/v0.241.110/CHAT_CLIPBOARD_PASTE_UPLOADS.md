# Chat Clipboard Paste Uploads

## Overview

Version: 0.241.110

Implemented in version: **0.241.110**

The chat composer now accepts clipboard images and browser-exposed clipboard files directly from the main message input. When a user focuses the chat textbox and pastes supported file content, the client routes the pasted `File` objects through the same upload path used by the existing file picker, including conversation auto-creation and upload consent checks.

Dependencies:

- `application/single_app/static/js/chat/chat-input-actions.js`
- `functional_tests/test_chat_clipboard_paste_upload_support.py`
- `ui_tests/test_chat_clipboard_paste_upload_workflow.py`

## Technical Specifications

### Architecture Overview

- The chat upload flow now uses a shared `beginChatFileUpload(...)` helper so selected files and pasted files follow the same conversation-creation, consent, and upload sequence.
- Clipboard file extraction reads `clipboardData.items` first and falls back to `clipboardData.files` so pasted images from common browser flows are captured without affecting normal text paste behavior.
- Clipboard files with empty names are normalized into a generated filename derived from MIME type before the upload request is sent, which preserves backend extension-based processing for pasted screenshots and nameless blobs.

### File Structure

- `application/single_app/static/js/chat/chat-input-actions.js`
- `functional_tests/test_chat_clipboard_paste_upload_support.py`
- `ui_tests/test_chat_clipboard_paste_upload_workflow.py`

## Usage Instructions

1. Open Chats and place the cursor inside the main message textarea.
2. Copy an image or browser-exposed file to the clipboard.
3. Press `Ctrl+V` inside the message input.
4. The pasted file uploads into the current conversation, or into a newly created conversation if none exists yet.

## Testing And Validation

Functional coverage:

- `functional_tests/test_chat_clipboard_paste_upload_support.py`

UI coverage:

- `ui_tests/test_chat_clipboard_paste_upload_workflow.py`

Known limitations:

- Clipboard file availability depends on browser support. The feature handles images and any file objects the browser exposes through the paste event, while plain-text paste remains unchanged.