# Chat User Setting Partial Save Fix

Fixed in version: **0.242.051**

## Issue Description

The Chats page could log `Failed to save user setting: HTTP error! status: 404` after changing a model or other chat preference, even when `/api/user/settings` was available and earlier settings loads succeeded.

## Root Cause

The chat `saveUserSetting(...)` helper fetched the full current settings document, merged one changed key in the browser, and posted the full settings object back to `/api/user/settings`. If the existing settings included a stale `activeGroupOid` or `activePublicWorkspaceOid`, the backend could reject the entire save while processing that unrelated stale value.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-layout.js`
- `application/single_app/route_backend_users.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_user_setting_partial_save.py`
- `functional_tests/test_user_settings_allowlist_keys.py`

Code changes summary:

- Changed `saveUserSetting(...)` to POST only the requested partial settings update.
- Kept server-side merging in `update_user_settings(...)` as the source of truth.
- Added `deepResearchDefaultEnabled` to the backend user settings allowlist because the chat UI already persists it.
- Added regression coverage for partial chat setting saves and chat preference allowlist keys.

## Validation

- `node --check application/single_app/static/js/chat/chat-layout.js`
- `python -m py_compile functional_tests/test_chat_user_setting_partial_save.py functional_tests/test_user_settings_allowlist_keys.py`
- `python functional_tests/test_chat_user_setting_partial_save.py`
- `python functional_tests/test_user_settings_allowlist_keys.py`

## Impact

Chat preference saves no longer fail because of unrelated stale workspace or group settings, and the Deep Research default preference can be saved through the same user settings route.