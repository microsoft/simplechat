# Enhanced Citations Blob And Collaboration Fix

Fixed/Implemented in version: **0.241.048**

## Issue Description

Enhanced citations regressed in two visible ways after the recent inline visualization changes:

1. Tabular previews started returning HTTP 500 for blob-backed CSV and XLSX citations, so the modal could only show the download fallback instead of the in-browser preview.
2. Agent citation artifacts inside collaborative conversations started returning `Conversation not found`, which prevented inline Azure Maps artifacts from hydrating and left repeated 404 errors in the browser console.
3. Agent citation links and inline artifact hydration depended on the active chat conversation id instead of the message’s own conversation context, which made artifact lookups more fragile whenever messages were rendered outside the standard single-user flow.

## Root Cause Analysis

- The enhanced citations route still defined helper logic that rebuilt blob paths locally, but the newer document revision model now relies on persisted blob metadata from `get_document_blob_storage_info(...)` so archived and current-alias citations resolve consistently.
- The tabular preview path and the shared content-serving path both depended on that stale helper flow, which broke once the direct helper import disappeared from the route.
- Collaborative conversations mirror compact agent citation records, but the full externalized artifact payload still lives in the hidden source conversation stored in the standard chat containers.
- The frontend renderer attached the current active conversation id to agent citation links instead of the message-scoped conversation id, which made artifact hydration overly dependent on global state.

## Files Modified

1. `application/single_app/route_enhanced_citations.py`
2. `application/single_app/route_frontend_conversations.py`
3. `application/single_app/static/js/chat/chat-messages.js`
4. `functional_tests/test_enhanced_citations_blob_and_collaboration_fix.py`
5. `application/single_app/config.py`

## Code Changes Summary

1. Added a shared `_resolve_document_blob_reference(...)` helper in the enhanced citations route so preview and content endpoints resolve persisted blob references through `get_document_blob_storage_info(...)`.
2. Removed the stale route-local blob path reconstruction logic that could diverge from the current document revision storage model.
3. Updated the agent citation artifact endpoint to recognize collaborative conversations, validate collaboration access, and read artifact payloads from the hidden source conversation when needed.
4. Added a message-scoped conversation id resolver in the chat renderer so agent citation links and inline Azure Maps hydration use the correct conversation context instead of only relying on global selection state.
5. Added a focused functional regression covering persisted blob references, collaboration artifact hydration, message-scoped conversation ids, and the shipped version/documentation alignment.

## Testing Approach

1. Added `functional_tests/test_enhanced_citations_blob_and_collaboration_fix.py` to lock in the backend and frontend regression markers for this fix.
2. Planned validation includes running the focused functional regression and checking diagnostics for the touched Python and JavaScript files.

## Validation

### Before

1. `/api/enhanced_citations/tabular_preview` could return HTTP 500 for blob-backed tabular citations.
2. Blob-backed enhanced citations could fall back to text or download-only behavior because the route was no longer resolving the persisted blob metadata helper.
3. Collaborative agent citation artifacts could 404 even when the source payload existed.

### After

1. Tabular preview and direct enhanced citation rendering resolve persisted blob references consistently for current and historical document revisions.
2. Collaborative conversations can hydrate externalized agent citation artifacts through the hidden source conversation backing store.
3. Agent citation links and inline artifact hydration use the message’s conversation context, reducing reliance on whichever chat is currently active.

## Related Tests

1. `functional_tests/test_enhanced_citations_blob_and_collaboration_fix.py`