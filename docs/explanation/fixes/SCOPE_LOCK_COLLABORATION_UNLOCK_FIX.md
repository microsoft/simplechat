# Scope Lock Collaboration Unlock Fix

Fixed in version: **0.241.051**

## Issue Description

The chat scope lock modal could fail to unlock a collaborative conversation even though the same conversation was otherwise active and accessible in the UI. The browser console showed a 404 on `/api/conversations/<conversation_id>/scope_lock` with the backend response `Conversation not found`.

## Root Cause Analysis

- The shared scope lock route only read from `cosmos_conversations_container`, which covers standard single-user chat conversations.
- Collaborative conversations live in `cosmos_collaboration_conversations_container`, so collaboration ids bypassed the normal lookup and fell straight into the 404 path.
- Even if the collaboration document were updated independently, the hidden source conversation used for mirrored AI responses also needed to stay synchronized for future stream and export flows.

## Version Implemented

- **0.241.051**

## Files Modified

- `application/single_app/route_backend_conversations.py`
- `application/single_app/config.py`
- `functional_tests/test_scope_lock_collaboration_unlock_fix.py`

## Code Changes Summary

- Added a scope-lock conversation resolver that first checks the standard conversation container and then falls back to collaborative conversations.
- Reused collaboration authorization so accepted participants can toggle scope lock without weakening access checks.
- Synced scope lock updates back into the hidden source conversation metadata so collaborative AI response mirroring keeps the same `scope_locked` and `locked_contexts` state.

## Testing Approach

- Added `functional_tests/test_scope_lock_collaboration_unlock_fix.py`.
- The regression checks the collaboration fallback path, the preserved `locked_contexts` response contract, and version/documentation alignment.

## Impact Analysis

- Unlocking and re-locking scope now works for collaborative conversations instead of failing with a false 404.
- Existing single-user conversation behavior remains unchanged.
- Collaborative metadata stays consistent between the visible collaboration conversation and its hidden source conversation.

## Validation

- Before: collaborative scope unlock requests returned `Conversation not found` from the shared scope lock route.
- After: the route resolves collaborative conversations, updates the collaboration record, syncs the source conversation, and returns the expected success payload.