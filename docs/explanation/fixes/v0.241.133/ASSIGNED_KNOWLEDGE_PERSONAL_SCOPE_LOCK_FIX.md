# Assigned Knowledge Personal Scope Lock Fix v0.241.133

Fixed in version: **0.241.133**

## Issue Description

Personal agents with Assigned Knowledge from a public workspace could be treated as public-workspace conversations after the first grounded response. When workspace scope lock was enabled, the conversation then locked to the public workspace and the personal agent could become unavailable for follow-up use.

## Root Cause Analysis

The streaming chat path rebuilt selected-agent metadata after the initial request metadata was created. That later metadata did not preserve the `assigned_knowledge_enabled` flag used by conversation metadata collection to keep personal assigned-knowledge agents anchored to the personal workspace.

The frontend also did not reflect the personal agent owner scope when applying Assigned Knowledge, so the scope selector could show only assigned source workspaces before the first response.

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/static/js/chat/chat-documents.js`
- `functional_tests/test_chat_scope_selector_sync.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added a shared route helper for selected-agent metadata so streaming, non-streaming, and document-action chat paths preserve `assigned_knowledge_enabled` consistently.
- Updated Assigned Knowledge frontend scope application to select the agent owner scope along with assigned source scopes.
- Kept Assigned Knowledge retrieval behavior unchanged: assigned sources still control what the agent searches, and user document selection remains disabled unless user workspace context is enabled for the agent.
- Updated `config.py` from version `0.241.132` to `0.241.133` for fix tracking.

### Testing Approach

- Added functional coverage in `functional_tests/test_chat_scope_selector_sync.py` to verify route metadata preservation and frontend assigned-knowledge scope selection wiring.
- Existing Assigned Knowledge policy coverage continues to validate that personal agents with public Assigned Knowledge keep personal as primary context and include the assigned public workspace as a locked context.

## Impact Analysis

- Personal agents remain usable after a public Assigned Knowledge response.
- Scope lock can include both the personal owner scope and assigned public workspace without allowing users to add personal documents when the agent's user workspace context option is disabled.
- Public Assigned Knowledge source visibility and retrieval restrictions are preserved.

## Validation

### Expected Before/After Behavior

Before the fix, a personal agent using assigned public knowledge could lock the conversation as public after the first response.

After the fix, the conversation remains personal-owned, with the assigned public workspace represented as locked secondary context.

### Test Results

Validation is performed by the focused functional test and syntax checks for the changed Python and JavaScript files.