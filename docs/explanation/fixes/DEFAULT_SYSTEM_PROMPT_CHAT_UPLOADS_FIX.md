# Default System Prompt Preservation With Chat Uploads Fix

Fixed/Implemented in version: **0.261.054**

## Issue Description

When a user uploaded an image, XML file, or other file directly in the chat UI, `conversation_history_for_api` included system messages converted from `role: 'image'` or `role: 'file'` items (such as `"User uploaded an image with the following description: ..."` or `"User uploaded a file named ..."`), or other augmentation system messages. Because `has_general_system_prompt` previously treated any `role == 'system'` message other than conversation summaries or `"retrieved document excerpts"` as a general system prompt, `default_system_prompt` was not inserted into `conversation_history_for_api` in either standard or streaming chat turns.

Related issue: Refs #1855

## Root Cause Analysis

- In `application/single_app/route_backend_chats.py`, both the standard chat path and the streaming chat path checked whether `default_system_prompt` was already present using an exclusion list:
  ```python
  has_general_system_prompt = any(
      msg.get('role') == 'system' and not (
          msg.get('content', '').startswith('<Summary of previous conversation context>') or
          "retrieved document excerpts" in msg.get('content', '')
      )
      for msg in conversation_history_for_api
  )
  ```
- Chat-uploaded images and files (`role: 'image'` and `role: 'file'`) are converted into `role: 'system'` context messages during conversation history preparation, and several other features also inject `role: 'system'` context messages that do not match those two exclusions.
- As a result, `has_general_system_prompt` evaluated to `True` whenever a chat-uploaded image or file was present, suppressing `default_system_prompt`.

## Version Implemented

- **0.261.054**
- Application version updated in `application/single_app/config.py` to `0.261.054`.

## Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_default_system_prompt_chat_uploads_fix.py`
- `docs/explanation/fixes/DEFAULT_SYSTEM_PROMPT_CHAT_UPLOADS_FIX.md`
- `docs/explanation/release_notes.md`

## Code Changes Summary

- Updated `has_general_system_prompt` in both standard and streaming chat paths in `application/single_app/route_backend_chats.py` to check whether a `role == 'system'` message in `conversation_history_for_api` actually matches `default_system_prompt` (`str(msg.get('content') or '').strip() == default_system_prompt`).
- Preserved idempotency when `default_system_prompt` is already present in `conversation_history_for_api` while ensuring chat-uploaded images/files and other augmentation system messages no longer suppress `default_system_prompt`.

## Testing Approach

- Added `functional_tests/test_chat_default_system_prompt_chat_uploads_fix.py` to verify that both standard and streaming chat paths in `route_backend_chats.py` check for an exact match with `default_system_prompt` and that `default_system_prompt` is inserted even when chat-uploaded image/file system messages or other augmentation system messages are present in `conversation_history_for_api`.

## Impact Analysis

- Conversations with chat-uploaded images, files, tabular analysis messages, or other system context messages now consistently receive the configured `default_system_prompt` in both standard and streaming chat modes.
- Existing behavior when `default_system_prompt` is already present or after `<Summary of previous conversation context>` remains unchanged.

## Validation

- Before: Uploading an image or file in chat added a `role: 'system'` message to `conversation_history_for_api`, causing `has_general_system_prompt` to evaluate to `True` and skip inserting `default_system_prompt`.
- After: `has_general_system_prompt` only evaluates to `True` when `default_system_prompt` itself is already in `conversation_history_for_api`, so `default_system_prompt` is always included alongside chat-uploaded image/file context.
