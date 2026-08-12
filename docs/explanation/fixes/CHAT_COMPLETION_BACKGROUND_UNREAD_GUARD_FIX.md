# Chat Completion Background Unread Guard Fix

## Header Information

**Issue description**: After conversation mark-read cache invalidation tuning, a chat response that finished while the user was viewing another conversation could lose its notification and green unread dot.

**Root cause analysis**: Streaming finalization still force-called `markConversationRead()` for the completed conversation and updated `window.currentConversationId` to the finished stream's conversation id. That made a background completion look active to the client and immediately cleared the unread state that the backend had just set.

**Fixed in version**: **0.250.036**

**Related config.py version update**: `application/single_app/config.py` was updated to version **0.250.036**.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-streaming.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_streaming_background_unread_guard.py`
- `functional_tests/test_chat_completion_notifications.py`
- `docs/explanation/features/COSMOS_PERFORMANCE_OPTIMIZATION_PLAN.md`

### Code Changes Summary

- Added an active-conversation guard around streaming finalization mark-read calls.
- Kept forced mark-read behavior for the currently visible conversation so active readers do not see stale unread dots.
- Prevented a completed background stream from switching `window.currentConversationId` away from the conversation the user is currently viewing.
- Added a static regression test that verifies streaming finalization cannot call `markConversationRead()` directly with `finalData.conversation_id`.

### Testing Approach

- JavaScript syntax validation for `chat-streaming.js`.
- Focused static functional test for the background unread guard.
- Existing chat completion notification contract updated to require the guarded streaming helper.

### Impact Analysis

- Active conversation streaming behavior remains unchanged for users watching the response complete.
- Background chat completions keep their backend-created notification and green unread dot until the user opens that conversation.
- Conversation cache remains optional and source/Cosmos-backed fallback behavior is unchanged.

## Validation

### Test Results

- `node --check application\single_app\static\js\chat\chat-streaming.js`
- `venv\Scripts\python.exe functional_tests\test_chat_streaming_background_unread_guard.py`
- `venv\Scripts\python.exe -m py_compile functional_tests\test_chat_completion_notifications.py functional_tests\test_chat_streaming_background_unread_guard.py`
- `git diff --check`

### Before/After Comparison

- **Before**: Finalizing a background stream force-cleared unread state and could remove the notification/dot before the user returned.
- **After**: Only the active visible conversation is force-cleared. Background completions stay unread until opened.

### User Experience Improvements

- Restores the expected "chat finished while I am away" notification behavior.
- Restores the green unread dot for conversations that complete in the background.
