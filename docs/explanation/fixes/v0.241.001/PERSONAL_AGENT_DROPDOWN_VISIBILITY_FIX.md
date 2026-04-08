# Personal Agent Dropdown Visibility Fix (0.236.061)

## Issue Description
Personal agents were missing from the chat agent dropdown when no active group was actually selected. The UI treated string values like "None" as a valid active group ID, so the dropdown only showed group and global agents.

## Root Cause Analysis
The chat dropdown logic relied on `window.activeGroupId` and treated any non-empty string as a real group ID. When templates rendered `None` as a string, the code mistakenly filtered out personal agents.

## Version Implemented
Fixed/Implemented in version: **0.236.061**

## Technical Details
- **Files modified**:
  - application/single_app/static/js/chat/chat-agents.js
  - application/single_app/static/js/chat/chat-retry.js
  - application/single_app/config.py
- **Change summary**:
  - Normalize `activeGroupId` by treating "none", "null", and "undefined" as empty.
  - Ensures personal agents are included when no real group is active.

## Testing Approach
- Added functional test: functional_tests/test_personal_agent_dropdown_in_chats_fix.py
- Test validates the normalization guard exists in both chat dropdown scripts.

## Impact Analysis
- Personal agents now appear in the chat dropdown when no active group is selected.
- Group/global behavior remains unchanged when a real active group ID is present.

## Validation
- Open chat page with no active group.
- Confirm personal + global agents appear in the dropdown.
- Switch to a valid active group and confirm group + global agents appear.
