# Personal Agent Dropdown Scope Fix (0.236.062)

## Issue Description
Personal agents were hidden in the chat dropdown whenever an active group ID existed in global page state, even when the user was chatting in the personal tab.

## Root Cause Analysis
The dropdown treated any non-empty `activeGroupId` as a group context. Because the chat page always renders `active_group_id`, personal agents were filtered out even in user chat.

## Version Implemented
Fixed/Implemented in version: **0.236.062**

## Technical Details
- **Files modified**:
  - application/single_app/static/js/chat/chat-agents.js
  - application/single_app/static/js/chat/chat-retry.js
  - application/single_app/config.py
- **Change summary**:
  - Determine group scope using `window.activeChatTabType === 'group'` before using `activeGroupId`.
  - Personal agents now show in the user chat tab; group agents only show in group chat.

## Testing Approach
- Added functional test: functional_tests/test_personal_agent_dropdown_scope_fix.py
- Test verifies the group chat scope guard is present in chat dropdown scripts.

## Impact Analysis
- Restores personal agent visibility in personal chat.
- Preserves group agent visibility in group chat.
- No changes to backend agent data.

## Validation
- Open personal chat and confirm personal + global agents appear.
- Switch to group chat tab and confirm group + global agents appear.
