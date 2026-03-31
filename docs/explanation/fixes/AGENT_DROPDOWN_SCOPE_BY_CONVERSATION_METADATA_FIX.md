# Agent Dropdown Scope by Conversation Metadata Fix (0.236.063)

## Issue Description
Personal agents were hidden in chat even when the current conversation was personal. Filtering relied on global group state rather than the active conversation scope, so group context suppressed personal agents.

## Root Cause Analysis
The agent dropdown used `activeGroupId` to decide scope. The chat page always renders an active group ID, so personal conversations were mistakenly treated as group scope. The UI already stores the conversation scope in `data-chat-type`, but the dropdown ignored it.

## Version Implemented
Fixed/Implemented in version: **0.236.063**

## Technical Details
- **Files modified**:
  - application/single_app/static/js/chat/chat-agents.js
  - application/single_app/static/js/chat/chat-retry.js
  - application/single_app/config.py
- **Change summary**:
  - Scope is derived from the active conversation's `data-chat-type`.
  - New conversations with no metadata show all agents.
  - Group scope shows group + global agents only; other scopes show personal + global.

## Testing Approach
- Added functional test: functional_tests/test_agent_dropdown_scope_by_conversation_metadata.py
- Test validates the metadata-based scope logic is present in both chat dropdown scripts.

## Impact Analysis
- Personal agents are visible in personal conversations.
- Group agents are shown only in group conversations.
- New conversations default to showing all agents.

## Validation
- Start a new chat: personal + group + global agents appear.
- Open a group chat: only group + global agents appear.
- Open a personal chat: only personal + global agents appear.
