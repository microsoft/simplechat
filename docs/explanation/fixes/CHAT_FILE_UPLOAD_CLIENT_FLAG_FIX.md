# Chat File Upload Client Flag Fix

Fixed in version: **0.241.110**

## Issue Description

Chat file uploads could be enabled in Admin Settings, but users still saw `Chat file uploads are not enabled for your account.` when selecting, pasting, or dropping a file in chat.

## Root Cause Analysis

The `/chats` route calculated the effective per-user `enable_chat_file_uploads` value, including the optional `ChatFileUploadUser` role requirement, but the chat template did not serialize that value into `window.appSettings`. The chat upload JavaScript checked `window.appSettings.enable_chat_file_uploads`, so the missing property evaluated to `false` and blocked uploads before the browser posted to `/upload`.

## Technical Details

Files modified:
- `application/single_app/templates/chats.html`
- `application/single_app/config.py`
- `functional_tests/test_chat_file_upload_access_control.py`
- `ui_tests/test_chat_file_upload_access_control.py`
- `docs/explanation/features/CHAT_FILE_UPLOAD_ACCESS_CONTROL.md`

Code changes summary:
- Added `enable_chat_file_uploads` to the chat page `window.appSettings` object using the effective server-rendered setting.
- Wrapped the chat file input and paperclip controls in the effective setting so users without chat upload permission do not see unavailable controls.
- Updated functional coverage to assert the client upload gate receives the effective setting.

Related config.py version update: `application/single_app/config.py` was incremented to `0.241.110`.

## Validation

Test results:
- `python functional_tests/test_chat_file_upload_access_control.py`
- `python -m pytest ui_tests/test_chat_file_upload_access_control.py -q`
- `python -m py_compile application/single_app/config.py functional_tests/test_chat_file_upload_access_control.py`

Before the fix, the JavaScript upload guard treated the missing app setting as disabled. After the fix, chat upload controls and selected, pasted, or dropped uploads use the same effective setting produced by the backend.