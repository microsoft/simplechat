# Scope Lock Agent Unlock Fix

Fixed in version: **0.241.052**

## Issue Description

After unlocking a conversation scope, workspace documents and prompts became broadly available again, but the agent pickers still behaved as if the conversation was locked to its original workspace context. That left valid personal or group agents hidden or unavailable even though the scope unlock had already succeeded.

## Root Cause Analysis

- The main chat agent dropdown still applied its existing-conversation metadata guard whenever a conversation had a concrete `data-chat-type`, even after `scope_locked` had been explicitly set to `false`.
- The scope lock toggle refreshed documents and tags, but it never dispatched the shared scope-change event that the agent dropdown listens to for rebuilds.
- The retry modal duplicated similar conversation-scope filtering, so it could also keep agents locked out after an explicit unlock.

## Version Implemented

- **0.241.052**

## Files Modified

- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/static/js/chat/chat-agents.js`
- `application/single_app/static/js/chat/chat-retry.js`
- `application/single_app/config.py`
- `functional_tests/test_scope_lock_agent_unlock_fix.py`

## Code Changes Summary

- Added a shared explicit-unlock guard in `chat-agents.js` so existing conversations only force conversation-type agent filtering while the scope is still locked or auto-scoped.
- Updated `toggleScopeLock(...)` in `chat-documents.js` to run the normal scope refresh pipeline and notify listeners with `chat:scope-changed` after lock or unlock.
- Updated the retry modal agent loader to respect the explicit unlock state and include agents from the currently effective scope selections.

## Testing Approach

- Added `functional_tests/test_scope_lock_agent_unlock_fix.py`.
- The regression verifies the main agent picker unlock guard, the post-toggle scope refresh dispatch, the retry picker unlock handling, and version/documentation alignment.

## Impact Analysis

- Explicitly unlocked conversations now refresh agent availability immediately instead of leaving the picker in a stale locked state.
- Agent availability now matches the effective workspace scope after unlock, which keeps agents aligned with documents and prompts.
- Retry workflows use the same unlock-aware agent filtering, reducing inconsistencies between the main composer and retry modal.

## Validation

- Before: unlocking scope restored documents and prompts but left many agent options hidden or disabled because the agent UI still enforced the original conversation workspace.
- After: explicit unlocks trigger a scope refresh event and both agent pickers honor the unlocked effective scope instead of the stale conversation-only guard.