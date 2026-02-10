# Chat Type Normalization Fix (0.236.065)

## Fix Title
Chat Type Normalization for New and Personal Conversations

## Issue Description
New conversations and legacy personal conversations could lack a consistent `chat_type`, which made scope-aware UI logic inconsistent across agent dropdowns, badges, and metadata views.

## Root Cause Analysis
Chat type values were optional in conversation items. Missing or legacy values were not normalized, causing ambiguous scope handling and inconsistent UI state.

## Version Implemented
Fixed/Implemented in version: **0.236.065**

## Technical Details
### Files Modified
- application/single_app/static/js/chat/chat-conversations.js
- application/single_app/static/js/chat/chat-agents.js
- application/single_app/static/js/chat/chat-retry.js
- application/single_app/static/js/chat/chat-conversation-details.js
- application/single_app/route_backend_conversations.py
- application/single_app/route_backend_chats.py
- application/single_app/functions_conversation_metadata.py
- application/single_app/config.py
- functional_tests/test_chat_type_normalization.py

### Code Changes Summary
- Normalize missing or legacy personal chat types to `personal_single_user`.
- Mark new conversations with `chat_type = "new"` on creation.
- Persist normalization server-side for legacy conversations.
- Update chat detail rendering and badges to handle `personal_single_user` and `new`.

## Testing Approach
- Added a functional test to assert chat type normalization across UI and backend sources.

## Validation
### Test Results
- Functional test: functional_tests/test_chat_type_normalization.py

### User Experience Improvements
- Consistent agent scope determination for new and personal chats.
- Stable chat type metadata in conversation lists and details.

## Related Updates
- Config version updated to 0.236.065.
- Functional test added for chat type normalization coverage.
