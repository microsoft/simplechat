# New Conversation Agent/Model Refresh Fix (0.236.066)

## Fix Title
Refresh agent and model lists on new conversation creation

## Issue Description
When starting a new conversation, the agent list did not refresh and depended on the previously selected conversation scope. The model list also did not re-apply user preferences after a new conversation was created.

## Root Cause Analysis
- New conversations are added without invoking the full selection flow, so the agent dropdown remained stale.
- Group agents were fetched only when `window.activeGroupId` was set; active group settings in user settings (`activeGroupOid`) were not used.

## Version Implemented
Fixed/Implemented in version: **0.236.066**

## Technical Details
### Files Modified
- application/single_app/static/js/agents_common.js
- application/single_app/static/js/chat/chat-agents.js
- application/single_app/static/js/chat/chat-retry.js
- application/single_app/static/js/chat/chat-conversations.js
- application/single_app/config.py
- functional_tests/test_new_conversation_agent_model_refresh.py

### Code Changes Summary
- Group agent fetching now accepts an explicit active group id.
- New conversation agent dropdown uses `activeGroupOid` from user settings.
- Model selection is refreshed on new conversation creation and on conversation switches.

## Testing Approach
- Added a functional test to verify active group fallback and refresh hooks.

## Validation
### Test Results
- Functional test: functional_tests/test_new_conversation_agent_model_refresh.py

### User Experience Improvements
- New conversations consistently show personal + active group agents.
- Model selection is re-applied to reflect user preferences.

## Related Updates
- Config version updated to 0.236.066.
